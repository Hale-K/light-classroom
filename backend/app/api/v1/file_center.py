"""文件中心：导入 / 导出 / 下载。"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.org import Class, Grade, Student, User
from app.models.transfer import FileTransferJob
from app.services.file_center.jobs import JOB_TYPE_LABELS, JOB_TYPES, direction_of, dispatch_job, job_to_dict
from app.services.file_center.timetable_pack_xlsx import normalize_pack_sheets, pack_title_and_filename
from app.services.storage import minio_client

router = APIRouter(prefix="/file-center", tags=["文件中心"])


class ExportTimetableIn(BaseModel):
    academic_year: str
    term: str = "1"
    class_ids: list[int] | None = Field(default=None, description="不传或空=全部班级")
    periods_per_day: int = 9
    evening_start_period: int | None = None
    sheets: list[str] | None = Field(
        default=None,
        description="可选：cover / teacher_relation / teacher_hours / teacher_grid / class_timetables / student_timetables",
    )
    student_zip: bool = Field(default=False, description="为每名学生生成独立课表并打包为 ZIP")


class ExportStudentsIn(BaseModel):
    grade_id: int | None = None
    class_id: int | None = None
    unassigned_only: bool = False


@router.get("/job-types", summary="导入导出类型字典")
async def list_job_types(user=Depends(get_current_user)):
    data = [
        {
            "value": key,
            "label": label,
            "direction": direction_of(key),
        }
        for key, label in JOB_TYPE_LABELS.items()
    ]
    return {"code": 0, "message": "ok", "data": data}


@router.get("/jobs", summary="导入导出任务列表")
async def list_jobs(
    direction: str | None = Query(default=None, description="import / export"),
    job_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    stmt = select(FileTransferJob).where(FileTransferJob.tenant_id == tenant_id)
    if direction in {"import", "export"}:
        stmt = stmt.where(FileTransferJob.direction == direction)
    if job_type:
        stmt = stmt.where(FileTransferJob.job_type == job_type)
    if status:
        stmt = stmt.where(FileTransferJob.status == status)
    stmt = stmt.order_by(FileTransferJob.created_at.desc()).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())
    return {"code": 0, "message": "ok", "data": [job_to_dict(row) for row in rows]}


@router.get("/jobs/{job_id}", summary="任务详情")
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    job = await session.get(FileTransferJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"code": 0, "message": "ok", "data": job_to_dict(job)}


@router.get("/jobs/{job_id}/download", summary="获取下载地址")
async def download_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    job = await session.get(FileTransferJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status != "success" or not job.object_key:
        raise HTTPException(status_code=409, detail="文件尚未就绪")
    try:
        url = minio_client.presigned_get_url(job.object_key, expires_seconds=3600)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成下载链接失败：{exc}") from exc
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "url": url,
            "file_name": job.file_name,
            "file_size": job.file_size,
        },
    }


@router.post("/exports/timetable", summary="异步导出课表")
async def export_timetable(
    body: ExportTimetableIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    class_ids = list(body.class_ids or [])
    class_stmt = select(Class).where(Class.tenant_id == tenant_id)
    if class_ids:
        class_stmt = class_stmt.where(Class.id.in_(class_ids))
    class_models = list((await session.execute(class_stmt)).scalars().all())
    count = len(class_models)
    if class_ids:
        scope = f"{count} 个班"
    else:
        scope = "全部班级"
        class_ids = []
    grade_ids = {cls.grade_id for cls in class_models if cls.grade_id}
    grade_names: list[str] = []
    if grade_ids:
        grade_names = list(
            (
                await session.execute(
                    select(Grade.name).where(Grade.tenant_id == tenant_id, Grade.id.in_(grade_ids))
                )
            ).scalars().all()
        )
    sheets = sorted(normalize_pack_sheets(body.sheets))
    if not sheets:
        raise HTTPException(status_code=422, detail="请至少勾选一种工作表")
    _title, file_name = pack_title_and_filename(grade_names)
    if body.student_zip:
        file_name = f"学生课表_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"

    job_id = uuid.uuid4().hex
    job = FileTransferJob(
        id=job_id,
        tenant_id=tenant_id,
        job_type="export_timetable",
        direction="export",
        status="queued",
        progress=0,
        total=int(count or 0),
        operator_id=user.id,
        operator_name=user.name or "",
        scope=scope,
        file_name=file_name,
        meta_json=json.dumps(
            {
                "academic_year": body.academic_year,
                "term": body.term,
                "class_ids": class_ids,
                "periods_per_day": body.periods_per_day,
                "evening_start_period": body.evening_start_period,
                "sheets": sheets,
                "student_zip": body.student_zip,
            },
            ensure_ascii=False,
        ),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    asyncio.create_task(dispatch_job(job_id, "export_timetable"))
    return {"code": 0, "message": "导出任务已创建", "data": job_to_dict(job)}


@router.post("/exports/students", summary="异步导出学生档案")
async def export_students(
    body: ExportStudentsIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    stmt = select(func.count()).select_from(Student).where(Student.tenant_id == tenant_id)
    scope_parts: list[str] = []
    if body.grade_id:
        grade = await session.get(Grade, body.grade_id)
        if grade is None or grade.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="年级不存在")
        stmt = stmt.where(Student.grade_id == body.grade_id)
        scope_parts.append(grade.name)
    if body.class_id:
        cls = await session.get(Class, body.class_id)
        if cls is None or cls.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="班级不存在")
        stmt = stmt.where(Student.class_id == body.class_id)
        scope_parts.append(cls.name)
    if body.unassigned_only:
        stmt = stmt.where(Student.class_id.is_(None))
        scope_parts.append("待分班")
    scope = "、".join(scope_parts) if scope_parts else "全部学生"
    count = int((await session.execute(stmt)).scalar_one() or 0)
    file_name = f"学生档案_{scope}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv".replace("/", "-")

    job_id = uuid.uuid4().hex
    job = FileTransferJob(
        id=job_id,
        tenant_id=tenant_id,
        job_type="export_students",
        direction="export",
        status="queued",
        progress=0,
        total=count,
        operator_id=user.id,
        operator_name=user.name or "",
        scope=scope,
        file_name=file_name,
        meta_json=json.dumps(
            {
                "grade_id": body.grade_id,
                "class_id": body.class_id,
                "unassigned_only": body.unassigned_only,
            },
            ensure_ascii=False,
        ),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    asyncio.create_task(dispatch_job(job_id, "export_students"))
    return {"code": 0, "message": "导出任务已创建", "data": job_to_dict(job)}


@router.post("/imports", summary="上传并异步导入")
async def create_import(
    job_type: str = Form(..., description="import_students / import_course_hours / import_teaching_assignments"),
    scope: str = Form(default=""),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    if job_type not in JOB_TYPES or direction_of(job_type) != "import":
        raise HTTPException(status_code=422, detail="不支持的导入类型")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="文件为空")
    job_id = uuid.uuid4().hex
    safe_name = (file.filename or "upload.bin").replace("\\", "_").replace("/", "_")
    object_key = f"imports/{tenant_id}/{job_id}/{safe_name}"
    try:
        size = minio_client.put_bytes(
            object_key,
            raw,
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"上传到对象存储失败：{exc}") from exc

    job = FileTransferJob(
        id=job_id,
        tenant_id=tenant_id,
        job_type=job_type,
        direction="import",
        status="queued",
        progress=0,
        total=1,
        operator_id=user.id,
        operator_name=user.name or "",
        scope=scope or JOB_TYPE_LABELS.get(job_type, job_type),
        file_name=safe_name,
        object_key=object_key,
        file_size=size,
        meta_json=json.dumps({"content_type": file.content_type}, ensure_ascii=False),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    asyncio.create_task(dispatch_job(job_id, job_type))
    return {"code": 0, "message": "导入任务已创建", "data": job_to_dict(job)}
