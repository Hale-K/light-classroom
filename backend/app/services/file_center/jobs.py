"""文件中心任务执行。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.org import Class, CourseHourPlan, Grade, Schedule, Student, Subject, TeachingAssignment, User
from app.models.transfer import FileTransferJob
from app.services.file_center.timetable_pack_xlsx import (
    PackSlot,
    build_timetable_pack_xlsx,
    normalize_pack_sheets,
    pack_title_and_filename,
    plan_evening_hours,
)
from app.services.storage import minio_client


JOB_TYPE_LABELS = {
    "export_timetable": "导出排课完整包",
    "export_students": "导出学生",
    "import_students": "导入学生",
    "import_course_hours": "导入课时",
    "import_teaching_assignments": "导入任教关系",
}

JOB_TYPES = list(JOB_TYPE_LABELS.keys())


def direction_of(job_type: str) -> str:
    return "export" if job_type.startswith("export_") else "import"


def job_to_dict(job: FileTransferJob) -> dict[str, Any]:
    duration_ms = None
    if job.started_at and job.finished_at:
        duration_ms = int((job.finished_at - job.started_at).total_seconds() * 1000)
    elif job.started_at and job.status == "running":
        duration_ms = int((datetime.utcnow() - job.started_at).total_seconds() * 1000)
    return {
        "id": job.id,
        "job_type": job.job_type,
        "job_type_label": JOB_TYPE_LABELS.get(job.job_type, job.job_type),
        "direction": job.direction,
        "status": job.status,
        "progress": job.progress,
        "processed": job.processed,
        "total": job.total,
        "operator_id": job.operator_id,
        "operator_name": job.operator_name,
        "scope": job.scope,
        "file_name": job.file_name,
        "object_key": job.object_key,
        "file_size": job.file_size,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration_ms": duration_ms,
        "downloadable": bool(job.status == "success" and job.object_key),
    }


async def _patch_job(session: AsyncSession, job_id: str, **fields: Any) -> FileTransferJob | None:
    job = await session.get(FileTransferJob, job_id)
    if job is None:
        return None
    for key, value in fields.items():
        setattr(job, key, value)
    job.updated_at = datetime.utcnow()
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def run_export_timetable(job_id: str) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(FileTransferJob, job_id)
        if job is None:
            return
        meta = json.loads(job.meta_json or "{}")
        academic_year = meta.get("academic_year") or ""
        term = meta.get("term") or "1"
        class_ids = meta.get("class_ids") or []
        evening_start = int(meta.get("evening_start_period") or 10)
        include_sheets = normalize_pack_sheets(meta.get("sheets"))
        try:
            if not include_sheets:
                raise ValueError("请至少勾选一种工作表")
            await _patch_job(
                session,
                job_id,
                status="running",
                started_at=datetime.utcnow(),
                progress=5,
            )
            class_stmt = select(Class).where(Class.tenant_id == job.tenant_id).order_by(Class.id)
            if class_ids:
                class_stmt = class_stmt.where(Class.id.in_(class_ids))
            class_models = list((await session.execute(class_stmt)).scalars().all())
            if not class_models:
                raise ValueError("没有可导出的班级")
            class_rows = [(int(cls.id), cls.name) for cls in class_models if cls.id is not None]
            selected_ids = [cid for cid, _ in class_rows]
            total = len(class_rows)

            grade_ids = {cls.grade_id for cls in class_models if cls.grade_id}
            grade_names = []
            if grade_ids:
                grade_names = [
                    name
                    for name in (
                        await session.execute(
                            select(Grade.name).where(
                                Grade.tenant_id == job.tenant_id,
                                Grade.id.in_(grade_ids),
                            )
                        )
                    ).scalars().all()
                ]
            pack_title, default_name = pack_title_and_filename(grade_names)
            if not (job.file_name or "").lower().endswith(".xlsx"):
                job.file_name = default_name
                session.add(job)
                await session.commit()

            subject_rows = list(
                (
                    await session.execute(
                        select(Subject).where(Subject.tenant_id == job.tenant_id)
                    )
                ).scalars().all()
            )
            subject_names = {int(s.id): s.name for s in subject_rows if s.id is not None}
            activity_subject_ids = {
                int(s.id)
                for s in subject_rows
                if s.id is not None and s.name in {"自主学习", "班主任晚课"}
            }

            teacher_ids: set[int] = set()
            schedules = list(
                (
                    await session.execute(
                        select(Schedule).where(
                            Schedule.tenant_id == job.tenant_id,
                            Schedule.class_id.in_(selected_ids),
                            Schedule.academic_year == academic_year,
                            Schedule.term == term,
                        )
                    )
                ).scalars().all()
            )
            for row in schedules:
                if row.teacher_id:
                    teacher_ids.add(int(row.teacher_id))

            ta_rows = list(
                (
                    await session.execute(
                        select(TeachingAssignment).where(
                            TeachingAssignment.tenant_id == job.tenant_id,
                            TeachingAssignment.academic_year == academic_year,
                            TeachingAssignment.term == term,
                            TeachingAssignment.class_id.in_(selected_ids),
                        )
                    )
                ).scalars().all()
            )
            for row in ta_rows:
                if row.teacher_id:
                    teacher_ids.add(int(row.teacher_id))

            teacher_names = {
                int(uid): name
                for uid, name in (
                    await session.execute(
                        select(User.id, User.name).where(
                            User.tenant_id == job.tenant_id,
                            User.id.in_(teacher_ids) if teacher_ids else False,
                        )
                    )
                ).all()
            } if teacher_ids else {}

            await _patch_job(session, job_id, progress=30, processed=0, total=total)

            class_name_map = dict(class_rows)
            slots: list[PackSlot] = []
            for row in schedules:
                parity = row.week_parity.value if hasattr(row.week_parity, "value") else str(row.week_parity)
                sid = int(row.subject_id or 0)
                tid = int(row.teacher_id) if row.teacher_id else None
                slots.append(
                    PackSlot(
                        class_id=int(row.class_id),
                        class_name=class_name_map.get(int(row.class_id), str(row.class_id)),
                        subject_id=sid,
                        subject_name=subject_names.get(sid, ""),
                        teacher_id=tid,
                        teacher_name=teacher_names.get(tid or 0, ""),
                        weekday=int(row.weekday),
                        period=int(row.period),
                        week_parity=parity or "all",
                    )
                )

            plan_rows = list(
                (
                    await session.execute(
                        select(CourseHourPlan).where(
                            CourseHourPlan.tenant_id == job.tenant_id,
                            CourseHourPlan.academic_year == academic_year,
                            CourseHourPlan.term == term,
                            CourseHourPlan.class_id.in_(selected_ids),
                        )
                    )
                ).scalars().all()
            )
            plan_by_cs: dict[tuple[int, int], dict[str, float]] = {}
            for plan in plan_rows:
                key = (int(plan.class_id), int(plan.subject_id))
                evening_parity = (
                    plan.evening_parity.value
                    if hasattr(plan.evening_parity, "value")
                    else str(plan.evening_parity or "all")
                )
                plan_by_cs[key] = {
                    "weekday": float(plan.weekday_periods or 0),
                    "saturday": float(plan.saturday_periods or 0),
                    "evening": plan_evening_hours(
                        plan.evening_periods_odd,
                        plan.evening_periods_even,
                        evening_parity,
                    ),
                }

            teaching_assignments = [
                {
                    "teacher_id": int(row.teacher_id) if row.teacher_id else None,
                    "subject_id": int(row.subject_id),
                    "class_id": int(row.class_id),
                    "teacher_name": teacher_names.get(int(row.teacher_id), "") if row.teacher_id else "",
                    "subject_name": subject_names.get(int(row.subject_id), ""),
                }
                for row in ta_rows
            ]

            await _patch_job(session, job_id, progress=70, processed=total, total=total)
            payload = build_timetable_pack_xlsx(
                pack_title=pack_title,
                academic_year=academic_year,
                term=term,
                scope_label=job.scope or f"{total} 个班",
                evening_start=evening_start,
                slots=slots,
                class_rows=class_rows if "class_timetables" in include_sheets else [],
                plan_by_cs=plan_by_cs,
                teaching_assignments=teaching_assignments,
                activity_subject_ids=activity_subject_ids,
                include_sheets=include_sheets,
            )
            file_name = job.file_name or default_name
            object_key = f"exports/{job.tenant_id}/{job_id}/{file_name}"
            size = minio_client.put_bytes(
                object_key,
                payload,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            await _patch_job(
                session,
                job_id,
                status="success",
                progress=100,
                processed=total,
                total=total,
                file_name=file_name,
                object_key=object_key,
                file_size=size,
                finished_at=datetime.utcnow(),
                error_message=None,
            )
        except Exception as exc:
            logger.exception(f"export_timetable failed job={job_id}")
            await _patch_job(
                session,
                job_id,
                status="failed",
                progress=100,
                finished_at=datetime.utcnow(),
                error_message=str(exc),
            )


def _csv_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return f'"{text.replace(chr(34), chr(34) + chr(34))}"'


async def run_export_students(job_id: str) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(FileTransferJob, job_id)
        if job is None:
            return
        meta = json.loads(job.meta_json or "{}")
        grade_id = meta.get("grade_id")
        class_id = meta.get("class_id")
        unassigned_only = bool(meta.get("unassigned_only"))
        try:
            await _patch_job(
                session,
                job_id,
                status="running",
                started_at=datetime.utcnow(),
                progress=10,
            )
            stmt = select(Student).where(Student.tenant_id == job.tenant_id)
            if grade_id:
                stmt = stmt.where(Student.grade_id == int(grade_id))
            if class_id:
                stmt = stmt.where(Student.class_id == int(class_id))
            if unassigned_only:
                stmt = stmt.where(Student.class_id.is_(None))
            stmt = stmt.order_by(Student.roster_order, Student.id)
            students = list((await session.execute(stmt)).scalars().all())
            class_map = {
                cid: name
                for cid, name in (
                    await session.execute(
                        select(Class.id, Class.name).where(Class.tenant_id == job.tenant_id)
                    )
                ).all()
            }
            grade_map = {
                gid: name
                for gid, name in (
                    await session.execute(
                        select(Grade.id, Grade.name).where(Grade.tenant_id == job.tenant_id)
                    )
                ).all()
            }
            await _patch_job(session, job_id, progress=40, total=len(students), processed=0)
            headers = ["学号", "姓名", "性别", "年级", "行政班", "家长电话", "身高", "状态"]
            lines = [",".join(headers)]
            gender_label = {"male": "男", "female": "女"}
            status_label = {
                "studying": "在读",
                "leave": "休学",
                "transferred": "转出",
            }
            for index, row in enumerate(students, start=1):
                gender = row.gender.value if hasattr(row.gender, "value") else str(row.gender or "")
                status = row.status.value if hasattr(row.status, "value") else str(row.status or "")
                lines.append(
                    ",".join(
                        [
                            _csv_escape(row.student_no),
                            _csv_escape(row.name),
                            _csv_escape(gender_label.get(gender, gender)),
                            _csv_escape(grade_map.get(row.grade_id or 0, "")),
                            _csv_escape(class_map.get(row.class_id or 0, "待分班") if row.class_id else "待分班"),
                            _csv_escape(row.parent_phone),
                            _csv_escape(row.height_cm if row.height_cm is not None else ""),
                            _csv_escape(status_label.get(status, status)),
                        ]
                    )
                )
                if index % 200 == 0 or index == len(students):
                    progress = 40 + int(index / max(len(students), 1) * 50)
                    await _patch_job(
                        session,
                        job_id,
                        progress=min(progress, 90),
                        processed=index,
                        total=len(students),
                    )
            payload = ("\ufeff" + "\n".join(lines)).encode("utf-8")
            object_key = f"exports/{job.tenant_id}/{job_id}/{job.file_name}"
            size = minio_client.put_bytes(object_key, payload, content_type="text/csv; charset=utf-8")
            await _patch_job(
                session,
                job_id,
                status="success",
                progress=100,
                processed=len(students),
                total=len(students),
                object_key=object_key,
                file_size=size,
                finished_at=datetime.utcnow(),
                error_message=None,
            )
        except Exception as exc:
            logger.exception(f"export_students failed job={job_id}")
            await _patch_job(
                session,
                job_id,
                status="failed",
                progress=100,
                finished_at=datetime.utcnow(),
                error_message=str(exc),
            )


async def run_import_store_only(job_id: str) -> None:
    """通用导入：校验 MinIO 文件存在后标记成功（业务落库按类型后续补齐）。"""
    async with AsyncSessionLocal() as session:
        job = await session.get(FileTransferJob, job_id)
        if job is None:
            return
        try:
            await _patch_job(
                session,
                job_id,
                status="running",
                started_at=datetime.utcnow(),
                progress=20,
                total=1,
            )
            if not job.object_key:
                raise ValueError("缺少上传文件")
            data = minio_client.get_bytes(job.object_key)
            if not data:
                raise ValueError("上传文件为空")
            await _patch_job(
                session,
                job_id,
                status="success",
                progress=100,
                processed=1,
                total=1,
                file_size=len(data),
                finished_at=datetime.utcnow(),
                error_message=None,
            )
        except Exception as exc:
            logger.exception(f"import job failed job={job_id}")
            await _patch_job(
                session,
                job_id,
                status="failed",
                progress=100,
                finished_at=datetime.utcnow(),
                error_message=str(exc),
            )


async def dispatch_job(job_id: str, job_type: str) -> None:
    if job_type == "export_timetable":
        await run_export_timetable(job_id)
    elif job_type == "export_students":
        await run_export_students(job_id)
    else:
        await run_import_store_only(job_id)
