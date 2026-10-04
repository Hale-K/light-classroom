"""New-gaokao subject choice, teaching-class formation, and walk scheduling API."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.gaokao import (
    GaokaoScheme,
    StudentSubjectChoice,
    TeachingClass,
    TeachingClassSchedule,
    TeachingClassStudent,
)
from app.models.facility import Room
from app.models.org import Class, Grade, Student, Subject, TeachingAssignment, Tenant, User
from app.services.academic.gaokao import (
    SubjectChoice,
    SubjectChoicePolicy,
    form_teaching_classes,
    generate_walk_schedule,
    get_subject_choice_strategy,
    resolve_selection_phase,
    validate_scheme_configuration,
)

router = APIRouter(prefix="/gaokao", tags=["新高考走班"])


class SchemeIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    province: str | None = Field(default=None, max_length=50)
    mode: str | None = Field(default=None, pattern=r"^(3\+1\+2|3\+3|traditional)$")
    entry_year: int = Field(ge=2014, le=2100)
    required_subject_ids: list[int] = Field(min_length=3, max_length=4)
    primary_subject_ids: list[int] = Field(default_factory=list, max_length=2)
    secondary_subject_ids: list[int] = Field(default_factory=list, max_length=7)
    strategy_config: dict[str, Any] = Field(default_factory=dict)


class ChoiceIn(BaseModel):
    scheme_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    effective_term: str = Field(default="1", min_length=1, max_length=20)
    primary_subject_id: int | None = None
    secondary_subject_ids: list[int] = Field(default_factory=list, max_length=3)
    selected_subject_ids: list[int] = Field(default_factory=list, max_length=7)
    stream: str | None = Field(default=None, max_length=20)
    round_no: int = Field(default=1, ge=1, le=20)
    status: str = Field(default="confirmed", pattern=r"^(draft|confirmed|changed)$")


class GenerateTeachingClassesIn(BaseModel):
    grade_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    capacity: int = Field(default=40, ge=20, le=60)
    weekly_periods: int = Field(default=3, ge=1, le=12)
    primary_delivery_mode: str | None = Field(
        default=None,
        pattern=r"^(administrative|teaching_class)$",
        description="首选科目默认在行政班授课，也可按年级改为走班",
    )


class GenerateWalkScheduleIn(BaseModel):
    grade_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    days: int = Field(default=5, ge=1, le=7)
    periods_per_day: int = Field(default=8, ge=1, le=12)
    forbidden_slots: list[tuple[int, int]] = Field(default_factory=list, max_length=84)


class ChoiceReviewIn(BaseModel):
    action: str = Field(pattern=r"^(approve|reject)$")


class ChoiceBatchReviewIn(BaseModel):
    choice_ids: list[int] = Field(min_length=1, max_length=500)


def _choice_policy(
    scheme: GaokaoScheme,
    primary_delivery_mode: str | None = None,
) -> SubjectChoicePolicy:
    config = scheme.strategy_config or {}
    stream_subject_ids = {
        str(name): tuple(int(item) for item in subject_ids)
        for name, subject_ids in config.get("stream_subject_ids", {}).items()
    }
    return SubjectChoicePolicy(
        primary_subject_ids=set(scheme.primary_subject_ids),
        secondary_subject_ids=set(scheme.secondary_subject_ids),
        elective_subject_ids=set(config.get("elective_subject_ids", scheme.secondary_subject_ids)),
        elective_count=int(config.get("elective_count", 3)),
        stream_subject_ids=stream_subject_ids,
        primary_delivery_mode=(
            primary_delivery_mode
            or str(config.get("primary_delivery_mode", "administrative"))
        ),
    )


def _subject_choice(source: ChoiceIn | StudentSubjectChoice) -> SubjectChoice:
    return SubjectChoice(
        primary_subject_id=source.primary_subject_id,
        secondary_subject_ids=tuple(source.secondary_subject_ids),
        selected_subject_ids=tuple(source.selected_subject_ids),
        stream=source.stream,
    )


def _selected_subject_ids(source: ChoiceIn | StudentSubjectChoice, scheme: GaokaoScheme) -> tuple[int, ...]:
    strategy = get_subject_choice_strategy(scheme.mode)
    return strategy.selected_subject_ids(_subject_choice(source), _choice_policy(scheme))


def _resolve_scheme_mode(
    requested_mode: str | None,
    current_mode: str | None,
    school_default_mode: str,
) -> str:
    """New cohorts inherit once; existing cohorts retain their stored snapshot."""
    return requested_mode or current_mode or school_default_mode


async def _grade_student_ids(session: AsyncSession, tenant_id: int, grade_id: int) -> list[int]:
    class_ids = list((await session.execute(select(Class.id).where(
        Class.tenant_id == tenant_id, Class.grade_id == grade_id,
    ))).scalars().all())
    if not class_ids:
        return []
    return list((await session.execute(select(Student.id).where(
        Student.tenant_id == tenant_id, Student.class_id.in_(class_ids),
    ))).scalars().all())


async def _overview(
    session: AsyncSession,
    tenant_id: int,
    *,
    grade_id: int | None,
    academic_year: str,
    term: str,
):
    scheme = (await session.execute(select(GaokaoScheme).where(
        GaokaoScheme.tenant_id == tenant_id, GaokaoScheme.is_active == True,  # noqa: E712
    ).order_by(GaokaoScheme.entry_year.desc()))).scalars().first()
    subjects = list((await session.execute(select(Subject).order_by(Subject.id))).scalars().all())
    subject_names = {item.id: item.name for item in subjects}
    grades = list((await session.execute(select(Grade).where(Grade.tenant_id == tenant_id).order_by(Grade.level))).scalars().all())

    if grade_id is None and grades:
        grade_id = grades[0].id
    selected_grade = next((item for item in grades if item.id == grade_id), None)
    workflow = resolve_selection_phase(selected_grade.level, term) if selected_grade else None
    student_ids = await _grade_student_ids(session, tenant_id, grade_id) if grade_id else []
    choices = []
    if student_ids:
        choices = list((await session.execute(select(StudentSubjectChoice).where(
            StudentSubjectChoice.tenant_id == tenant_id,
            StudentSubjectChoice.student_id.in_(student_ids),
            StudentSubjectChoice.academic_year == academic_year,
            StudentSubjectChoice.effective_term == term,
            StudentSubjectChoice.status.in_(["confirmed", "locked"]),
        ))).scalars().all())

    choice_scheme_ids = {item.scheme_id for item in choices}
    choice_schemes = list((await session.execute(select(GaokaoScheme).where(
        GaokaoScheme.id.in_(choice_scheme_ids),
    ))).scalars().all()) if choice_scheme_ids else []
    schemes_by_id = {item.id: item for item in choice_schemes}
    combination_counts: Counter[str] = Counter()
    combination_samples: dict[str, dict[str, Any]] = {}
    subject_counts: Counter[int] = Counter()
    walk_subject_counts: Counter[int] = Counter()
    for choice in choices:
        choice_scheme = schemes_by_id[choice.scheme_id]
        strategy = get_subject_choice_strategy(choice_scheme.mode)
        policy = _choice_policy(choice_scheme)
        selected = strategy.selected_subject_ids(_subject_choice(choice), policy)
        walk_selected = strategy.teaching_class_subject_ids(_subject_choice(choice), policy)
        key = strategy.combination_key(_subject_choice(choice), policy)
        combination_counts[key] += 1
        subject_counts.update(selected)
        walk_subject_counts.update(walk_selected)
        combination_samples[key] = {
            "key": key,
            "label": choice.stream or "+".join(subject_names.get(item, "?") for item in selected),
            "primary_subject_id": choice.primary_subject_id,
            "secondary_subject_ids": choice.secondary_subject_ids,
            "selected_subject_ids": list(selected),
            "stream": choice.stream,
            "mode": choice_scheme.mode,
        }

    teaching_stmt = select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id,
        TeachingClass.academic_year == academic_year,
        TeachingClass.term == term,
    )
    if grade_id:
        teaching_stmt = teaching_stmt.where(TeachingClass.grade_id == grade_id)
    teaching_classes = list((await session.execute(teaching_stmt.order_by(
        TeachingClass.subject_id, TeachingClass.sequence,
    ))).scalars().all())
    teaching_ids = [item.id for item in teaching_classes]
    members = list((await session.execute(select(TeachingClassStudent).where(
        TeachingClassStudent.teaching_class_id.in_(teaching_ids),
    ))).scalars().all()) if teaching_ids else []
    schedules = list((await session.execute(select(TeachingClassSchedule).where(
        TeachingClassSchedule.teaching_class_id.in_(teaching_ids),
    ))).scalars().all()) if teaching_ids else []
    member_counts = Counter(item.teaching_class_id for item in members)
    schedule_counts = Counter(item.teaching_class_id for item in schedules)
    teachers = list((await session.execute(select(User).where(User.tenant_id == tenant_id))).scalars().all())
    teacher_names = {item.id: item.name for item in teachers}
    class_counts = Counter(item.subject_id for item in teaching_classes)

    teacher_subjects: dict[int, set[int]] = defaultdict(set)
    assignments = list((await session.execute(select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id,
    ))).scalars().all())
    for assignment in assignments:
        teacher_subjects[assignment.subject_id].add(assignment.teacher_id)

    combinations = [{
        **combination_samples[key],
        "count": count,
    } for key, count in sorted(combination_counts.items(), key=lambda item: (-item[1], item[0]))]
    subject_demand = [{
        "subject_id": subject_id,
        "subject_name": subject_names.get(subject_id, "未知学科"),
        "student_count": count,
        "delivery_mode": "teaching_class" if walk_subject_counts[subject_id] else "administrative",
        "walk_student_count": walk_subject_counts[subject_id],
        "recommended_class_count": (walk_subject_counts[subject_id] + 39) // 40,
        "teaching_class_count": class_counts[subject_id],
        "teacher_count": len(teacher_subjects[subject_id]),
    } for subject_id, count in sorted(subject_counts.items())]
    class_data = [{
        **item.model_dump(),
        "subject_name": subject_names.get(item.subject_id, "未知学科"),
        "teacher_name": teacher_names.get(item.teacher_id, "待分配"),
        "student_count": member_counts[item.id],
        "scheduled_periods": schedule_counts[item.id],
    } for item in teaching_classes]
    workflow_warnings: list[str] = []
    if workflow and workflow.code == "exploration" and choices:
        workflow_warnings.append(
            f"探索阶段已有 {len(choices)} 份正式确认选科，应改为意向数据或调整生效学期"
        )
    if workflow and not workflow.can_generate_teaching_classes and teaching_classes:
        workflow_warnings.append(
            f"当前阶段存在 {len(teaching_classes)} 个存量教学班，请迁移到正式生效学期后再重建"
        )
    if workflow and not workflow.can_generate_schedule and schedules:
        workflow_warnings.append(
            f"当前阶段存在 {len(schedules)} 节存量走班课，应迁移到高二正式实施学期"
        )
    return {
        "scheme": scheme.model_dump() if scheme else None,
        "grades": [item.model_dump() for item in grades],
        "workflow": workflow.__dict__ if workflow else None,
        "workflow_warnings": workflow_warnings,
        "stats": {
            "student_count": len(student_ids),
            "confirmed_count": len(choices),
            "coverage_rate": round(len(choices) / len(student_ids) * 100, 1) if student_ids else 0,
            "combination_count": len(combination_counts),
            "teaching_class_count": len(teaching_classes),
            "schedule_period_count": len(schedules),
        },
        "combinations": combinations,
        "subject_demand": subject_demand,
        "teaching_classes": class_data,
    }


@router.get("/overview", summary="新高考选科与走班概览")
async def overview(
    academic_year: str,
    term: str = "1",
    grade_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    return {"code": 0, "message": "ok", "data": await _overview(
        session, tenant_id, grade_id=grade_id, academic_year=academic_year, term=term,
    )}


@router.get("/choices", summary="查询学生选科审核列表")
async def choices_for_review(
    academic_year: str,
    term: str = "1",
    grade_id: int | None = None,
    status_filter: str | None = "confirmed",
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    stmt = select(StudentSubjectChoice, Student).join(
        Student, Student.id == StudentSubjectChoice.student_id,
    ).where(
        StudentSubjectChoice.tenant_id == tenant_id,
        StudentSubjectChoice.academic_year == academic_year,
        StudentSubjectChoice.effective_term == term,
        Student.tenant_id == tenant_id,
    )
    if grade_id is not None:
        stmt = stmt.where(Student.grade_id == grade_id)
    if user.role == "teacher":
        class_ids = list((await session.execute(select(Class.id).where(
            Class.tenant_id == tenant_id,
            or_(Class.head_teacher_id == user.id, Class.deputy_head_teacher_id == user.id),
        ))).scalars().all())
        if not class_ids:
            return {"code": 0, "message": "ok", "data": []}
        stmt = stmt.where(Student.class_id.in_(class_ids))
    if status_filter:
        stmt = stmt.where(StudentSubjectChoice.status == status_filter)
    rows = (await session.execute(stmt.order_by(Student.grade_id, Student.student_no, Student.id))).all()
    subject_ids = {subject_id for choice, _student in rows for subject_id in (
        [choice.primary_subject_id] if choice.primary_subject_id else []
    ) + list(choice.secondary_subject_ids or [])}
    subjects = list((await session.execute(select(Subject).where(Subject.id.in_(subject_ids)))).scalars().all()) if subject_ids else []
    names = {item.id: item.name for item in subjects}
    return {"code": 0, "message": "ok", "data": [{
        "id": choice.id,
        "student_id": student.id,
        "student_no": student.student_no,
        "student_name": student.name,
        "grade_id": student.grade_id,
        "primary_subject_id": choice.primary_subject_id,
        "primary_subject_name": names.get(choice.primary_subject_id, "") if choice.primary_subject_id else "",
        "secondary_subject_ids": choice.secondary_subject_ids,
        "secondary_subject_names": [names.get(item, f"科目#{item}") for item in choice.secondary_subject_ids],
        "status": choice.status,
        "round_no": choice.round_no,
        "updated_at": choice.updated_at,
    } for choice, student in rows]}


@router.patch("/choices/{choice_id}/review", summary="审核学生选科")
async def review_choice(
    choice_id: int,
    body: ChoiceReviewIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    choice = await session.get(StudentSubjectChoice, choice_id)
    if choice is None or choice.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="选科记录不存在")
    if user.role == "teacher":
        student = await session.get(Student, choice.student_id)
        class_item = await session.get(Class, student.class_id) if student and student.class_id else None
        if class_item is None or user.id not in {class_item.head_teacher_id, class_item.deputy_head_teacher_id}:
            raise HTTPException(status_code=403, detail="只有该学生的班主任或副班主任可以审核")
    if choice.status == "locked":
        raise HTTPException(status_code=409, detail="选科已锁定，不能重复审核")
    if body.action == "approve":
        choice.status = "locked"
        message = "选科审核通过并已锁定"
    else:
        choice.status = "rejected"
        message = "选科已驳回，学生可以重新提交"
    await session.commit()
    await session.refresh(choice)
    return {"code": 0, "message": message, "data": choice.model_dump()}


@router.post("/choices/batch-approve", summary="批量审核通过学生选科")
async def batch_approve_choices(
    body: ChoiceBatchReviewIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    choices = list((await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == tenant_id,
        StudentSubjectChoice.id.in_(body.choice_ids),
    ))).scalars().all())
    if len(choices) != len(set(body.choice_ids)):
        raise HTTPException(status_code=404, detail="部分选科记录不存在")
    student_by_id = {item.id: item for item in (await session.execute(select(Student).where(
        Student.tenant_id == tenant_id,
        Student.id.in_([item.student_id for item in choices]),
    ))).scalars().all()}
    if user.role == "teacher":
        class_ids = {item.class_id for item in student_by_id.values() if item.class_id}
        classes = list((await session.execute(select(Class).where(
            Class.tenant_id == tenant_id, Class.id.in_(class_ids) if class_ids else False,
        ))).scalars().all())
        allowed_class_ids = {item.id for item in classes if user.id in {item.head_teacher_id, item.deputy_head_teacher_id}}
        if any(student_by_id[item.student_id].class_id not in allowed_class_ids for item in choices):
            raise HTTPException(status_code=403, detail="批量审核只能处理本人班级的学生")
    updated = 0
    skipped = 0
    for choice in choices:
        if choice.status == "confirmed":
            choice.status = "locked"
            updated += 1
        else:
            skipped += 1
    await session.commit()
    return {"code": 0, "message": "批量审核完成", "data": {"updated": updated, "skipped": skipped}}


@router.post("/schemes", summary="创建或更新新高考方案")
async def upsert_scheme(
    body: SchemeIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    subject_ids = set((await session.execute(select(Subject.id).where(
        (Subject.tenant_id.is_(None)) | (Subject.tenant_id == tenant_id),
    ))).scalars().all())
    configured = set(body.required_subject_ids + body.primary_subject_ids + body.secondary_subject_ids)
    configured.update(int(item) for item in body.strategy_config.get("elective_subject_ids", []))
    configured.update(
        int(item)
        for values in body.strategy_config.get("stream_subject_ids", {}).values()
        for item in values
    )
    if not configured.issubset(subject_ids):
        raise HTTPException(status_code=422, detail="方案中包含不存在的学科")
    item = (await session.execute(select(GaokaoScheme).where(
        GaokaoScheme.tenant_id == tenant_id, GaokaoScheme.entry_year == body.entry_year,
    ))).scalar_one_or_none()
    school = await session.get(Tenant, tenant_id)
    if school is None:
        raise HTTPException(status_code=404, detail="学校不存在")
    values = body.model_dump(exclude_none=True)
    values["mode"] = _resolve_scheme_mode(body.mode, item.mode if item else None, school.gaokao_mode)
    try:
        validate_scheme_configuration(
            values["mode"],
            body.required_subject_ids,
            body.primary_subject_ids,
            body.secondary_subject_ids,
            body.strategy_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if item is None:
        item = GaokaoScheme(tenant_id=tenant_id, **values)
        session.add(item)
    else:
        for key, value in values.items():
            setattr(item, key, value)
        item.is_active = True
    await session.commit()
    await session.refresh(item)
    return {"code": 0, "message": "ok", "data": item.model_dump()}


@router.patch("/students/{student_id}/choice", summary="维护学生选科")
async def save_choice(
    student_id: int,
    body: ChoiceIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    student = await session.get(Student, student_id)
    scheme = await session.get(GaokaoScheme, body.scheme_id)
    if not student or student.tenant_id != tenant_id or not scheme or scheme.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="学生或新高考方案不存在")
    try:
        selected_subject_ids = _selected_subject_ids(body, scheme)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    values = body.model_dump()
    values["selected_subject_ids"] = list(selected_subject_ids)
    item = (await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == tenant_id,
        StudentSubjectChoice.student_id == student_id,
        StudentSubjectChoice.academic_year == body.academic_year,
        StudentSubjectChoice.effective_term == body.effective_term,
    ))).scalar_one_or_none()
    if item is None:
        item = StudentSubjectChoice(tenant_id=tenant_id, student_id=student_id, **values)
        session.add(item)
    else:
        for key, value in values.items():
            setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return {"code": 0, "message": "ok", "data": item.model_dump()}


@router.post("/teaching-classes/generate", summary="按学生选科生成教学班")
async def generate_teaching_classes(
    body: GenerateTeachingClassesIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    grade = await session.get(Grade, body.grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="年级不存在")
    phase = resolve_selection_phase(grade.level, body.term)
    if not phase.can_generate_teaching_classes:
        raise HTTPException(status_code=422, detail=f"当前处于{phase.label}阶段，尚不能生成教学班")
    student_ids = await _grade_student_ids(session, tenant_id, body.grade_id)
    choices = list((await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == tenant_id,
        StudentSubjectChoice.student_id.in_(student_ids),
        StudentSubjectChoice.academic_year == body.academic_year,
        StudentSubjectChoice.effective_term == body.term,
        StudentSubjectChoice.status.in_(["confirmed", "locked"]),
    ).order_by(StudentSubjectChoice.student_id))).scalars().all()) if student_ids else []
    if len(choices) != len(student_ids):
        raise HTTPException(
            status_code=422,
            detail=f"当前年级有 {len(student_ids) - len(choices)} 名学生未完成确认选科",
        )
    scheme_ids = {item.scheme_id for item in choices}
    schemes = list((await session.execute(select(GaokaoScheme).where(
        GaokaoScheme.tenant_id == tenant_id,
        GaokaoScheme.id.in_(scheme_ids),
    ))).scalars().all()) if scheme_ids else []
    schemes_by_id = {item.id: item for item in schemes}
    if len(schemes_by_id) != len(scheme_ids):
        raise HTTPException(status_code=422, detail="部分学生选科对应的高考方案不存在")
    drafts = form_teaching_classes([{
        "student_id": item.student_id,
        "subject_ids": get_subject_choice_strategy(
            schemes_by_id[item.scheme_id].mode,
        ).teaching_class_subject_ids(
            _subject_choice(item),
            _choice_policy(
                schemes_by_id[item.scheme_id],
                body.primary_delivery_mode,
            ),
        ),
    } for item in choices], capacity=body.capacity)

    admin_class_ids = list((await session.execute(select(Class.id).where(
        Class.tenant_id == tenant_id, Class.grade_id == body.grade_id,
    ))).scalars().all())
    assignments = list((await session.execute(select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.class_id.in_(admin_class_ids),
        TeachingAssignment.academic_year == body.academic_year,
        TeachingAssignment.term == body.term,
    ))).scalars().all()) if admin_class_ids else []
    teachers_by_subject: dict[int, list[int]] = defaultdict(list)
    for assignment in assignments:
        if assignment.teacher_id is not None and assignment.teacher_id not in teachers_by_subject[assignment.subject_id]:
            teachers_by_subject[assignment.subject_id].append(assignment.teacher_id)
    required_subject_ids = {draft.subject_id for draft in drafts}
    missing_teacher_subject_ids = sorted(
        subject_id for subject_id in required_subject_ids
        if not teachers_by_subject.get(subject_id)
    )
    if missing_teacher_subject_ids:
        names = {
            item.id: item.name for item in (await session.execute(select(Subject).where(
                Subject.id.in_(missing_teacher_subject_ids),
            ))).scalars().all()
        }
        missing_names = [names.get(item, f"学科#{item}") for item in missing_teacher_subject_ids]
        raise HTTPException(status_code=422, detail=f"以下走班学科尚未配置任课教师：{'、'.join(missing_names)}")

    rooms = list((await session.execute(select(Room).where(
        Room.tenant_id == tenant_id,
        Room.room_type == "classroom",
        Room.is_schedulable.is_(True),
        Room.status == "available",
        Room.capacity >= body.capacity,
    ).order_by(Room.id))).scalars().all())
    if not rooms:
        raise HTTPException(status_code=422, detail=f"没有找到容量不小于{body.capacity}且可排课的普通教室")
    if len(rooms) < len(drafts):
        raise HTTPException(status_code=422, detail=f"可排课教室只有{len(rooms)}间，无法为{len(drafts)}个教学班建立资源方案")
    # 所有资源校验通过后才替换旧教学班，避免失败重生成把已有结果删除。
    old_classes = list((await session.execute(select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id,
        TeachingClass.grade_id == body.grade_id,
        TeachingClass.academic_year == body.academic_year,
        TeachingClass.term == body.term,
    ))).scalars().all())
    old_ids = [item.id for item in old_classes]
    if old_ids:
        await session.execute(delete(TeachingClassSchedule).where(TeachingClassSchedule.teaching_class_id.in_(old_ids)))
        await session.execute(delete(TeachingClassStudent).where(TeachingClassStudent.teaching_class_id.in_(old_ids)))
        await session.execute(delete(TeachingClass).where(TeachingClass.id.in_(old_ids)))
    subject_names = {
        item.id: item.name for item in (await session.execute(select(Subject))).scalars().all()
    }

    created_classes: list[TeachingClass] = []
    member_count = 0
    for draft_index, draft in enumerate(drafts):
        teachers = teachers_by_subject[draft.subject_id]
        teacher_id = teachers[(draft.sequence - 1) % len(teachers)] if teachers else None
        room = rooms[draft_index]
        teaching_class = TeachingClass(
            tenant_id=tenant_id,
            grade_id=body.grade_id,
            subject_id=draft.subject_id,
            name=f"{grade.name}{subject_names.get(draft.subject_id, '选科')}走班{draft.sequence:02d}",
            academic_year=body.academic_year,
            term=body.term,
            sequence=draft.sequence,
            capacity=body.capacity,
            weekly_periods=body.weekly_periods,
            teacher_id=teacher_id,
            room=room.name,
            status="generated",
        )
        session.add(teaching_class)
        await session.flush()
        session.add_all([
            TeachingClassStudent(
                tenant_id=tenant_id,
                teaching_class_id=teaching_class.id,
                student_id=student_id,
            ) for student_id in draft.student_ids
        ])
        created_classes.append(teaching_class)
        member_count += len(draft.student_ids)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "created": len(created_classes),
        "memberships": member_count,
        "student_count": len(student_ids),
        "subject_count": len({item.subject_id for item in created_classes}),
    }}


@router.post("/schedules/generate", summary="生成走班课表")
async def generate_schedules(
    body: GenerateWalkScheduleIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    grade = await session.get(Grade, body.grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="年级不存在")
    phase = resolve_selection_phase(grade.level, body.term)
    if not phase.can_generate_schedule:
        raise HTTPException(status_code=422, detail=f"当前处于{phase.label}阶段，走班课表从高二正式生效")
    teaching_classes = list((await session.execute(select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id,
        TeachingClass.grade_id == body.grade_id,
        TeachingClass.academic_year == body.academic_year,
        TeachingClass.term == body.term,
    ).order_by(TeachingClass.subject_id, TeachingClass.sequence))).scalars().all())
    if not teaching_classes:
        raise HTTPException(status_code=422, detail="请先根据学生选科生成教学班")
    teaching_ids = [item.id for item in teaching_classes]
    members = list((await session.execute(select(TeachingClassStudent).where(
        TeachingClassStudent.teaching_class_id.in_(teaching_ids),
    ))).scalars().all())
    students_by_class: dict[int, list[int]] = defaultdict(list)
    for member in members:
        students_by_class[member.teaching_class_id].append(member.student_id)
    result = generate_walk_schedule([{
        "id": item.id,
        "teacher_id": item.teacher_id,
        "room_key": item.room,
        "student_ids": students_by_class[item.id],
        "weekly_periods": item.weekly_periods,
    } for item in teaching_classes], days=body.days, periods_per_day=body.periods_per_day,
        forbidden_slots={tuple(slot) for slot in body.forbidden_slots})
    await session.execute(delete(TeachingClassSchedule).where(
        TeachingClassSchedule.teaching_class_id.in_(teaching_ids),
    ))
    class_map = {item.id: item for item in teaching_classes}
    records = [TeachingClassSchedule(
        tenant_id=tenant_id,
        teaching_class_id=item.teaching_class_id,
        teacher_id=item.teacher_id,
        subject_id=class_map[item.teaching_class_id].subject_id,
        academic_year=body.academic_year,
        term=body.term,
        weekday=item.weekday,
        period=item.period,
        room=class_map[item.teaching_class_id].room,
    ) for item in result.items]
    session.add_all(records)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "created": len(records),
        "teaching_class_count": len(teaching_classes),
        "unplaced": result.unplaced,
    }}


@router.get("/schedules", summary="查询走班课表")
async def list_schedules(
    academic_year: str,
    term: str = "1",
    grade_id: int | None = None,
    teaching_class_id: int | None = None,
    student_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    class_stmt = select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id,
        TeachingClass.academic_year == academic_year,
        TeachingClass.term == term,
    )
    if grade_id is not None:
        class_stmt = class_stmt.where(TeachingClass.grade_id == grade_id)
    if teaching_class_id is not None:
        class_stmt = class_stmt.where(TeachingClass.id == teaching_class_id)
    classes = list((await session.execute(class_stmt)).scalars().all())
    class_ids = [item.id for item in classes]
    if student_id is not None and class_ids:
        class_ids = list((await session.execute(select(TeachingClassStudent.teaching_class_id).where(
            TeachingClassStudent.student_id == student_id,
            TeachingClassStudent.teaching_class_id.in_(class_ids),
        ))).scalars().all())
    schedules = list((await session.execute(select(TeachingClassSchedule).where(
        TeachingClassSchedule.teaching_class_id.in_(class_ids),
    ).order_by(TeachingClassSchedule.weekday, TeachingClassSchedule.period))).scalars().all()) if class_ids else []
    class_map = {item.id: item for item in classes}
    subjects = {item.id: item.name for item in (await session.execute(select(Subject))).scalars().all()}
    teachers = {item.id: item.name for item in (await session.execute(select(User).where(
        User.tenant_id == tenant_id,
    ))).scalars().all()}
    return {"code": 0, "message": "ok", "data": [{
        **item.model_dump(),
        "teaching_class_name": class_map[item.teaching_class_id].name,
        "subject_name": subjects.get(item.subject_id, "未知学科"),
        "teacher_name": teachers.get(item.teacher_id, "待分配"),
    } for item in schedules]}
