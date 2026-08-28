"""学生档案全量/增量导入：先校验，确认后异步落库。"""
from __future__ import annotations

import asyncio
import uuid
import zipfile
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import AsyncSessionLocal, get_session
from app.models.enums import EnrollmentStatus, Gender
from app.models.org import Class, EnrollmentBatch, Grade, Student, TenantConfig
from app.services.student_grade_membership import sync_student_grade_membership
from app.services.student_import import ImportContext, context_from_config, normalize_gender, parse_rows

router = APIRouter(prefix="/org/students/import", tags=["学生档案导入"])

_pending: dict[str, dict[str, Any]] = {}
_tasks: dict[str, dict[str, Any]] = {}


class ConfirmImportIn(BaseModel):
    token: str


def _value(row: dict[str, Any], *names: str) -> str:
    for name in names:
        if row.get(name) is not None:
            return str(row[name]).strip()
    return ""


async def _current_context(session: AsyncSession, tenant_id: int) -> ImportContext:
    config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "academic_years",
    ))).scalars().first()
    try:
        return context_from_config(config.config_value if config else None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _validate_rows(
    rows: list[dict[str, Any]],
    import_type: Literal["full", "incremental"],
    context: ImportContext,
    session: AsyncSession,
    tenant_id: int,
) -> list[dict[str, Any]]:
    grades = list((await session.execute(select(Grade))).scalars().all())
    classes = list((await session.execute(select(Class))).scalars().all())
    grade_by_name = {item.name.strip(): item for item in grades}
    class_by_name = {item.name.strip(): item for item in classes}
    existing_nos = {
        item[0] for item in (await session.execute(select(Student.student_no).where(Student.tenant_id == tenant_id))).all()
        if item[0]
    }
    seen: set[str] = set()
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        student_no = _value(row, "学号", "student_no")
        name = _value(row, "姓名", "name")
        gender = normalize_gender(_value(row, "性别", "gender"))
        class_name = _value(row, "行政班", "班级", "class_name")
        row_errors: list[str] = []
        if not student_no:
            row_errors.append("学号不能为空")
        elif student_no in seen:
            row_errors.append("文件内学号重复")
        # 全量导入允许更新已存在学生；重复学号不是错误，结果中会按“更新”统计。
        if not name:
            row_errors.append("姓名不能为空")
        if not gender:
            row_errors.append("性别必须是男或女")
        target_class = class_by_name.get(class_name) if class_name else None
        if import_type == "full":
            if not class_name:
                row_errors.append("全量导入必须填写行政班")
            elif target_class is None:
                row_errors.append("行政班不存在，请使用当前届别已生成的班级")
            elif target_class.cohort_label not in {None, context.cohort_label}:
                row_errors.append("行政班不属于当前配置届别")
        seen.add(student_no)
        if row_errors:
            errors.append({"row": index, "student_no": student_no, "name": name, "errors": row_errors})
    return errors


@router.post("/validate", summary="校验学生导入文件")
async def validate_import(
    import_type: Literal["full", "incremental"],
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    tenant_id: int = Depends(get_current_tenant),
    user=Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=422, detail="请选择导入文件")
    data = await file.read()
    try:
        rows = parse_rows(file.filename, data)
    except (ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not rows:
        raise HTTPException(status_code=422, detail="导入文件没有有效数据")
    context = await _current_context(session, tenant_id)
    errors = await _validate_rows(rows, import_type, context, session, tenant_id)
    token = uuid.uuid4().hex
    _pending[token] = {"rows": rows, "import_type": import_type, "context": context, "tenant_id": tenant_id, "user_id": user.id}
    return {"code": 0, "message": "ok", "data": {
        "token": token, "import_type": import_type, "total": len(rows), "valid": len(rows) - len(errors),
        "errors": errors, "context": {"entry_year": context.entry_year, "academic_year": context.academic_year, "term": context.term},
    }}


async def _run_import(task_id: str, pending: dict[str, Any]) -> None:
    state = _tasks[task_id]
    rows = pending["rows"]
    context: ImportContext = pending["context"]
    async with AsyncSessionLocal() as session:
        batch = EnrollmentBatch(
            tenant_id=pending["tenant_id"], source=f"student_{pending['import_type']}",
            file_name=pending.get("file_name"), total_count=len(rows), created_by=pending["user_id"],
            errors={"context": {"entry_year": context.entry_year, "academic_year": context.academic_year, "term": context.term}},
        )
        session.add(batch)
        await session.flush()
        existing = {item.student_no: item for item in (await session.execute(select(Student).where(Student.tenant_id == pending["tenant_id"]))).scalars().all() if item.student_no}
        success = 0
        failures: list[dict[str, Any]] = []
        memberships_to_sync: list[Student] = []
        for index, row in enumerate(rows, start=2):
            try:
                student_no = _value(row, "学号", "student_no")
                student = existing.get(student_no)
                if pending["import_type"] == "incremental" and student is not None:
                    state["processed"] = index - 1
                    continue
                if student is None:
                    student = Student(tenant_id=pending["tenant_id"], student_no=student_no)
                student.name = _value(row, "姓名", "name")
                student.gender = Gender(normalize_gender(_value(row, "性别", "gender")) or "male")
                height = _value(row, "身高", "height_cm")
                student.height_cm = float(height) if height else None
                student.parent_phone = _value(row, "家长电话", "parent_phone") or None
                if pending["import_type"] == "full":
                    class_name = _value(row, "行政班", "班级", "class_name")
                    target = (await session.execute(select(Class).where(Class.name == class_name))).scalars().first()
                    if target is not None:
                        student.class_id, student.grade_id, student.campus_id = target.id, target.grade_id, target.campus_id
                session.add(student)
                existing[student_no] = student
                if student.grade_id is not None:
                    memberships_to_sync.append(student)
                success += 1
            except Exception as exc:  # per-row isolation; task continues
                failures.append({"row": index, "error": str(exc)})
            state["processed"] = index - 1
            if index % 100 == 0:
                await session.flush()
        await session.flush()
        for student in memberships_to_sync:
            try:
                await sync_student_grade_membership(
                    session, tenant_id=pending["tenant_id"], student=student,
                    grade_id=student.grade_id, academic_year=context.academic_year,
                )
            except ValueError as exc:
                failures.append({"row": None, "error": str(exc), "student_no": student.student_no})
        batch.success_count = success
        batch.fail_count = len(failures)
        batch.status = EnrollmentStatus.partial if failures else EnrollmentStatus.finished
        batch.errors = {**(batch.errors or {}), "rows": failures}
        await session.commit()
        state.update({"status": "finished", "success": success, "failed": len(failures), "errors": failures})


@router.post("/confirm", summary="确认并异步导入学生")
async def confirm_import(body: ConfirmImportIn, user=Depends(get_current_user)):
    pending = _pending.pop(body.token, None)
    if pending is None:
        raise HTTPException(status_code=404, detail="导入预览已失效，请重新上传")
    task_id = uuid.uuid4().hex
    _tasks[task_id] = {"task_id": task_id, "status": "running", "processed": 0, "total": len(pending["rows"]), "success": 0, "failed": 0}
    asyncio.create_task(_run_import(task_id, pending))
    return {"code": 0, "message": "导入任务已创建", "data": _tasks[task_id]}


@router.get("/tasks/{task_id}", summary="查询学生导入进度")
async def import_task(task_id: str, user=Depends(get_current_user)):
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return {"code": 0, "message": "ok", "data": task}
