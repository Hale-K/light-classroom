"""组织学籍 API - 年级 / 班级 / 学生（A8）

- 所有查询自动被多租户中间件注入 tenant_id 过滤（见 app/db/session.py）
- 新增写入需显式带 tenant_id（由当前登录用户上下文供给）
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, func, update, or_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user, get_current_tenant, require_management_user
from app.models.facility import Campus, Room, RoomCohortAllocation
from app.models.org import Grade, Class, OrganizationUnit, Student, StudentGradeMembership, StudentClassMembership, Subject, TeachingAssignment, User
from app.models.gaokao import StudentSubjectChoice
from app.models.enums import Gender, StudentStatus, UserStatus
from app.models.rbac import Role, UserRole
from app.services.academic.head_teacher import summarize_head_teacher_assignment
from app.services.org.naming import normalize_entity_name
from app.services.org.cohort import cohort_labels_match, current_academic_year, current_term, expected_cohort_label, normalize_cohort_label
from app.services.academic.student_membership import sync_student_grade_membership

router = APIRouter(prefix="/org", tags=["组织学籍"], dependencies=[Depends(require_management_user)])


# ---------- Pydantic 请求/响应模型 ----------
class GradeIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    level: int = Field(ge=1, le=3)
    campus_id: int | None = None


class ClassIn(BaseModel):
    grade_id: int
    name: str = Field(min_length=1, max_length=50)
    campus_id: int | None = None
    home_room_id: int | None = None
    class_type: str = Field(default="regular", min_length=1, max_length=30)
    planned_student_count: int | None = Field(default=None, ge=1, le=5000)
    head_teacher_id: int | None = None
    deputy_head_teacher_id: int | None = None
    cohort_label: str | None = Field(default=None, max_length=30, description="届(毕业年);缺省按当前学年+年级自动推导")
    academic_year: str | None = Field(default=None, min_length=9, max_length=20)
    term: str | None = Field(default=None, pattern=r"^(1|2)$")


class StudentIn(BaseModel):
    campus_id: int | None = None
    grade_id: int | None = None
    class_id: int | None = None
    name: str = Field(min_length=1, max_length=50)
    gender: Gender
    id_card: str | None = None
    birth_date: str | None = None
    parent_phone: str | None = None
    height_cm: float | None = Field(default=None, ge=80, le=250)
    student_no: str | None = None
    roster_order: int = 0


class StudentSimulationIn(BaseModel):
    """批量生成用于排课/分班演示的学生档案。"""
    cohort_label: str = Field(min_length=1, max_length=30)
    grade_id: int
    male_count: int = Field(default=0, ge=0, le=5000)
    female_count: int = Field(default=0, ge=0, le=5000)

    @model_validator(mode="after")
    def require_students(self):
        if self.male_count + self.female_count <= 0:
            raise ValueError("男生和女生人数至少填写一项")
        return self


class ClassAssignmentIn(BaseModel):
    class_id: int | None = None
    student_ids: list[int] = Field(min_length=1)
    academic_year: str | None = None
    term: str | None = Field(default=None, pattern=r"^(1|2)$")
    grade_id: int | None = None
    cohort_label: str | None = None


class AutoClassAssignmentIn(BaseModel):
    grade_id: int
    class_ids: list[int] = Field(min_length=1)
    strategy: Literal["snake", "stable", "subject_choice"] = "snake"
    balance_gender: bool = True
    overwrite_existing: bool = False


class ClassResourcePlanIn(BaseModel):
    home_room_id: int | None = None
    class_type: str = Field(min_length=1, max_length=30)


class StudentStatusUpdateIn(BaseModel):
    status: StudentStatus


class HeadTeacherAssignmentIn(BaseModel):
    teacher_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(min_length=1, max_length=20)


# ---------- 年级 ----------
@router.get("/grades", summary="年级列表")
async def list_grades(session: AsyncSession = Depends(get_session),
                      user=Depends(get_current_user)):
    result = await session.execute(
        select(Grade, Campus.name.label("campus_name"))
        .join(Campus, Grade.campus_id == Campus.id, isouter=True)
        .order_by(Grade.level, Grade.id),
    )
    data = []
    for grade, campus_name in result.all():
        row = grade.model_dump()
        row["campus_name"] = campus_name
        data.append(row)
    return {"code": 0, "message": "ok", "data": data}


@router.post("/grades", summary="新建年级", status_code=201)
async def create_grade(body: GradeIn, session: AsyncSession = Depends(get_session),
                       user=Depends(get_current_user),
                       tenant_id: int = Depends(get_current_tenant)):
    name = normalize_entity_name(body.name) or ""
    duplicate = (await session.execute(select(Grade.id).where(
        Grade.tenant_id == tenant_id, Grade.name == name,
    ))).scalar()
    if duplicate:
        raise HTTPException(status_code=422, detail=f"年级「{name}」已存在")
    grade_data = body.model_dump()
    grade_data["name"] = name
    grade = Grade(**grade_data, tenant_id=tenant_id)
    session.add(grade)
    await session.commit()
    await session.refresh(grade)
    return {"code": 0, "message": "ok", "data": grade.model_dump()}


# ---------- 班级 ----------
@router.get("/classes", summary="班级列表")
async def list_classes(grade_id: int | None = None,
                       academic_year: str | None = None,
                       term: str | None = None,
                       session: AsyncSession = Depends(get_session),
                       user=Depends(get_current_user),
                       tenant_id: int = Depends(get_current_tenant)):
    # 行政班是届别快照数据。列表不能只按 grade_id 查询，否则同一年级
    # 的历史届别（例如旧的 2029 届）会混入当前班级管理页面。
    stmt = select(Class).order_by(Class.grade_id, Class.id)
    if grade_id is not None:
        stmt = stmt.where(Class.grade_id == grade_id)
        grade = (await session.execute(select(Grade).where(
            Grade.tenant_id == tenant_id, Grade.id == grade_id,
        ))).scalar_one_or_none()
        if grade is not None:
            active_cohort = expected_cohort_label(
                academic_year or await current_academic_year(session, tenant_id),
                grade.level,
            )
            # Older records may retain the display suffix (for example, "2026届").
            # Filter after loading so both canonical and display labels remain visible.
            classes = list((await session.execute(stmt)).scalars().all())
            classes = [item for item in classes if cohort_labels_match(item.cohort_label, active_cohort)]
        else:
            classes = list((await session.execute(stmt)).scalars().all())
    elif academic_year:
        # 未指定具体年级时，按当前学年筛掉其它届别；不同年级的目标届别
        # 可能不同，因此在结果组装后再按各年级 level 过滤。
        pass
    if grade_id is None:
        classes = list((await session.execute(stmt)).scalars().all())
    if academic_year:
        classes = [item for item in classes if item.academic_year == academic_year]
    if term:
        classes = [item for item in classes if item.term == term]
    if grade_id is None and academic_year:
        grade_ids = {item.grade_id for item in classes}
        grades = list((await session.execute(select(Grade).where(
            Grade.tenant_id == tenant_id, Grade.id.in_(grade_ids) if grade_ids else False,
        ))).scalars().all())
        cohort_by_grade = {
            item.id: expected_cohort_label(academic_year, item.level) for item in grades
        }
        classes = [item for item in classes if item.cohort_label == cohort_by_grade.get(item.grade_id)]
    allocations = (await session.execute(
        select(
            RoomCohortAllocation.room_id,
            RoomCohortAllocation.academic_year,
            RoomCohortAllocation.term,
            RoomCohortAllocation.cohort_label,
        ).where(
            RoomCohortAllocation.tenant_id == tenant_id,
            RoomCohortAllocation.status == "active",
        )
    )).all()
    allocated_cohorts_by_room_scope: dict[tuple[int, str, str], set[str]] = {}
    for room_id, allocation_year, allocation_term, allocation_cohort in allocations:
        allocated_cohorts_by_room_scope.setdefault(
            (room_id, allocation_year, allocation_term), set(),
        ).add(allocation_cohort)
    counts = dict((await session.execute(
        select(StudentClassMembership.class_id, func.count(StudentClassMembership.student_id))
        .where(
            StudentClassMembership.tenant_id == tenant_id,
            StudentClassMembership.status == "active",
            StudentClassMembership.class_id.in_([item.id for item in classes]) if classes else False,
        )
        .group_by(StudentClassMembership.class_id)
    )).all())
    # 按班级自身的学年、学期读取已确认选科，不能用历史选科标记当前班级。
    primary_subjects_by_class: dict[int, set[str]] = {}
    if classes:
        choice_rows = (await session.execute(
            select(StudentClassMembership.class_id, Subject.name)
            .join(Student, StudentClassMembership.student_id == Student.id)
            .join(Class, StudentClassMembership.class_id == Class.id)
            .join(StudentSubjectChoice, (
                (StudentSubjectChoice.student_id == Student.id)
                & (StudentSubjectChoice.tenant_id == tenant_id)
                & (StudentSubjectChoice.academic_year == Class.academic_year)
                & (StudentSubjectChoice.effective_term == Class.term)
                & StudentSubjectChoice.status.in_(["confirmed", "locked"])
            ))
            .join(Subject, StudentSubjectChoice.primary_subject_id == Subject.id)
            .where(Student.tenant_id == tenant_id, Class.tenant_id == tenant_id,
                   StudentClassMembership.class_id.in_([item.id for item in classes]),
                   StudentClassMembership.status == "active")
            .distinct()
        )).all()
        for class_id, subject_name in choice_rows:
            primary_subjects_by_class.setdefault(class_id, set()).add(subject_name)
    head_teacher_ids = {item.head_teacher_id for item in classes if item.head_teacher_id}
    teacher_names = {}
    if head_teacher_ids:
        teacher_names = dict((await session.execute(
            select(User.id, User.name).where(User.id.in_(head_teacher_ids))
        )).all())
    assignment_rows = []
    subject_names = {}
    if head_teacher_ids and academic_year and term:
        assignments = list((await session.execute(
            select(TeachingAssignment).where(
                TeachingAssignment.teacher_id.in_(head_teacher_ids),
                TeachingAssignment.academic_year == academic_year,
                TeachingAssignment.term == term,
            )
        )).scalars().all())
        assignment_rows = [item.model_dump() for item in assignments]
        subject_ids = {item.subject_id for item in assignments}
        if subject_ids:
            subject_names = dict((await session.execute(
                select(Subject.id, Subject.name).where(Subject.id.in_(subject_ids))
            )).all())
    data = []
    for item in classes:
        row = item.model_dump()
        allocated_cohorts = allocated_cohorts_by_room_scope.get(
            (item.home_room_id, item.academic_year, item.term), set(),
        ) if item.home_room_id else set()
        row["resource_assigned"] = any(
            cohort_labels_match(item.cohort_label, allocation_cohort)
            for allocation_cohort in allocated_cohorts
        )
        row["student_count"] = counts.get(item.id, 0)
        primary_subjects = primary_subjects_by_class.get(item.id, set())
        row["subject_track"] = (
            "physics" if primary_subjects == {"物理"} else
            "history" if primary_subjects == {"历史"} else
            "mixed" if len(primary_subjects) > 1 else "pending"
        )
        row["head_teacher_name"] = teacher_names.get(item.head_teacher_id)
        row["head_teacher_teaches_own_class"] = False
        if item.head_teacher_id and assignment_rows:
            try:
                summary = summarize_head_teacher_assignment(
                    item.head_teacher_id, item.id, assignment_rows,
                )
                row["head_teacher_teaches_own_class"] = bool(summary["teaches_own_class"])
                row["head_teacher_subject_name"] = subject_names.get(summary["subject_id"])
                row["head_teacher_taught_class_count"] = summary["taught_class_count"]
            except ValueError:
                pass
        data.append(row)
    return {"code": 0, "message": "ok", "data": data}


@router.post("/classes", summary="新建班级", status_code=201)
async def create_class(body: ClassIn, session: AsyncSession = Depends(get_session),
                       user=Depends(get_current_user),
                       tenant_id: int = Depends(get_current_tenant)):
    name = normalize_entity_name(body.name) or ""
    grade = await session.get(Grade, body.grade_id)
    if grade is None or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="年级不存在")
    academic_year = body.academic_year or await current_academic_year(session, tenant_id)
    term = body.term or await current_term(session, tenant_id)
    cohort_label = normalize_cohort_label(body.cohort_label) or expected_cohort_label(academic_year, grade.level)
    duplicate = (await session.execute(select(Class.id).where(
        Class.tenant_id == tenant_id,
        Class.grade_id == body.grade_id,
        Class.cohort_label == cohort_label,
        Class.academic_year == academic_year,
        Class.term == term,
        Class.name == name,
    ))).scalar()
    if duplicate:
        raise HTTPException(status_code=422, detail=f"{cohort_label}届该年级下班级「{name}」已存在")
    class_data = body.model_dump(exclude={"academic_year", "term", "cohort_label"})
    cls = Class(**class_data, tenant_id=tenant_id, name=name, cohort_label=cohort_label,
                academic_year=academic_year, term=term)
    session.add(cls)
    await session.commit()
    await session.refresh(cls)
    return {"code": 0, "message": "ok", "data": cls.model_dump()}


@router.patch("/classes/{class_id}/resource-plan", summary="配置班级类型和教室")
async def update_class_resource_plan(
    class_id: int,
    body: ClassResourcePlanIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    cls = await session.get(Class, class_id)
    if cls is None or cls.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="行政班不存在")
    if body.home_room_id is not None:
        room = await session.get(Room, body.home_room_id)
        if room is None or room.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="指定教室不存在")
        conflict = (await session.execute(select(Class).where(
            Class.tenant_id == tenant_id,
            Class.home_room_id == body.home_room_id,
            Class.id != class_id,
            Class.academic_year == cls.academic_year,
            Class.term == cls.term,
        ))).scalars().first()
        if conflict is not None:
            raise HTTPException(status_code=409, detail=f"教室已绑定{conflict.name}")
    cls.home_room_id = body.home_room_id
    cls.class_type = body.class_type
    await session.commit()
    await session.refresh(cls)
    return {"code": 0, "message": "ok", "data": cls.model_dump()}


@router.patch("/classes/{class_id}/head-teacher", summary="配置行政班班主任")
async def assign_head_teacher(
    class_id: int,
    body: HeadTeacherAssignmentIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    cls = await session.get(Class, class_id)
    if cls is None or cls.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="行政班不存在")
    teacher = await session.get(User, body.teacher_id)
    if teacher is None or teacher.tenant_id != tenant_id or teacher.status != UserStatus.active:
        raise HTTPException(status_code=404, detail="任课老师不存在或已停用")
    role_rows = list((await session.execute(
        select(Role.id, Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == teacher.id)
    )).all())
    role_codes = {code for _, code in role_rows}
    if "subject_teacher" not in role_codes:
        raise HTTPException(status_code=422, detail="班主任必须先具有任课老师角色")
    assignments = list((await session.execute(
        select(TeachingAssignment).where(
            TeachingAssignment.tenant_id == tenant_id,
            TeachingAssignment.teacher_id == teacher.id,
            TeachingAssignment.academic_year == body.academic_year,
            TeachingAssignment.term == body.term,
        )
    )).scalars().all())
    summary = summarize_head_teacher_assignment(
        teacher.id, cls.id, [item.model_dump() for item in assignments],
    )
    subject = await session.get(Subject, summary["subject_id"]) if summary["subject_id"] else None
    if subject and subject.name == "体育":
        raise HTTPException(status_code=422, detail="体育教师不能担任班主任")
    # 班主任可以先安排到行政班，再生成任教关系；确认任教关系时再回填任教信息。
    if "head_teacher" not in role_codes:
        head_teacher_role_id = next((role_id for role_id, code in role_rows if code == "head_teacher"), None)
        if head_teacher_role_id is None:
            head_teacher_role_id = (await session.execute(
                select(Role.id).where(Role.code == "head_teacher")
            )).scalar_one_or_none()
        if head_teacher_role_id is None:
            raise HTTPException(status_code=500, detail="班主任角色未配置")
        session.add(UserRole(user_id=teacher.id, role_id=head_teacher_role_id))
    cls.head_teacher_id = teacher.id
    await session.commit()
    await session.refresh(cls)
    return {"code": 0, "message": "ok", "data": {
        **cls.model_dump(),
        "head_teacher_name": teacher.name,
        "head_teacher_subject_name": subject.name if subject else None,
        "head_teacher_taught_class_count": summary["taught_class_count"],
        "head_teacher_teaches_own_class": bool(summary["teaches_own_class"]),
    }}


def add_existing_class_counts(class_rows: dict[int, dict], students: list[Student]) -> None:
    """Merge students already assigned to the preview classes into their summaries."""
    for student in students:
        row = class_rows.get(student.class_id)
        if row is None:
            continue
        row["student_count"] += 1
        gender = getattr(student.gender, "value", student.gender)
        if gender == Gender.male.value:
            row["male_count"] += 1
        elif gender == Gender.female.value:
            row["female_count"] += 1


async def build_auto_class_assignment(
    body: AutoClassAssignmentIn,
    session: AsyncSession,
    tenant_id: int,
) -> dict:
    classes = list((await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.grade_id == body.grade_id,
        Class.id.in_(body.class_ids),
    ).order_by(Class.id))).scalars().all())
    if len(classes) != len(set(body.class_ids)):
        raise HTTPException(status_code=404, detail="部分行政班不存在或不属于当前年级")
    capacity_by_class = {item.id: item.planned_student_count or 45 for item in classes}
    # 学生年级以当前学年的“学生年级关联快照”为准；兼容尚未迁移快照、仍直接写入
    # Student.grade_id 的旧数据。否则学生档案能显示学生，自动分班却会统计为 0 人。
    current_year = await current_academic_year(session, tenant_id)
    membership_student_ids = list((await session.execute(
        select(StudentGradeMembership.student_id).where(
            StudentGradeMembership.tenant_id == tenant_id,
            StudentGradeMembership.grade_id == body.grade_id,
            StudentGradeMembership.academic_year == current_year,
            StudentGradeMembership.status == "active",
        )
    )).scalars().all())
    student_stmt = select(Student).where(
        Student.tenant_id == tenant_id,
        Student.status == StudentStatus.studying,
        or_(
            Student.grade_id == body.grade_id,
            Student.id.in_(membership_student_ids) if membership_student_ids else False,
        ),
    )
    if not body.overwrite_existing:
        # 旧班级被删除后，学生可能仍残留已失效的 class_id。只有当前这次
        # 选中的有效班级才算“已分班”，其余（含孤儿 class_id）都应重新进入待分班。
        valid_class_ids = set(body.class_ids)
        student_stmt = student_stmt.where(
            or_(
                Student.class_id.is_(None),
                ~Student.class_id.in_(valid_class_ids),
            )
        )
    students = list((await session.execute(student_stmt.order_by(Student.roster_order, Student.id))).scalars().all())
    subject_choice_key_by_student: dict[int, str] = {}
    subject_group_by_student: dict[int, str] = {}
    if body.strategy == "subject_choice" and students:
        academic_year = await current_academic_year(session, tenant_id)
        term = await current_term(session, tenant_id)
        choice_rows = (await session.execute(select(StudentSubjectChoice).where(
            StudentSubjectChoice.tenant_id == tenant_id,
            StudentSubjectChoice.student_id.in_([item.id for item in students]),
            StudentSubjectChoice.academic_year == academic_year,
            StudentSubjectChoice.effective_term == term,
            StudentSubjectChoice.status.in_(["confirmed", "locked"]),
        ))).scalars().all()
        for choice in choice_rows:
            selected = choice.selected_subject_ids or [
                item for item in [choice.primary_subject_id, *(choice.secondary_subject_ids or [])]
                if item is not None
            ]
            subject_choice_key_by_student[choice.student_id] = "+".join(str(item) for item in sorted(set(selected))) or "未完成选科"
            # 物理和历史是互斥的首选科目，必须先按首选科目隔离班级池；
            # 同一首选科目内部再按完整选课组合排序和均衡分配。
            subject_group_by_student[choice.student_id] = (
                f"primary:{choice.primary_subject_id}"
                if choice.primary_subject_id is not None else "未完成选科"
            )
        if len(subject_choice_key_by_student) < len(students):
            missing = len(students) - len(subject_choice_key_by_student)
            if missing:
                for student in students:
                    subject_choice_key_by_student.setdefault(student.id, "未完成选科")
                    subject_group_by_student.setdefault(student.id, "未完成选科")
    if body.strategy == "stable":
        students.sort(key=lambda item: (item.student_no or "", item.id))
    elif body.strategy == "subject_choice":
        students.sort(key=lambda item: (subject_choice_key_by_student.get(item.id, "未完成选科"), item.roster_order, item.id))
    else:
        students.sort(key=lambda item: (item.roster_order, item.id))

    # 只启用能容纳本次学生总数的最少行政班，避免把学生平均摊到所有备用教室。
    required_class_count = 0
    selected_capacity = 0
    subject_group_class_ids: dict[str, list[int]] = {}
    if students:
        if body.strategy == "subject_choice":
            # 按首选科目分别计算所需容量，并优先使用大容量教室，避免某个
            # 首选科目被挤到最后只剩一个极小班，同时保证物理/历史绝不混班。
            group_counts: dict[str, int] = {}
            for student in students:
                group = subject_group_by_student.get(student.id, "未完成选科")
                group_counts[group] = group_counts.get(group, 0) + 1
            remaining = dict(group_counts)
            available_rooms = sorted(classes, key=lambda item: (-capacity_by_class[item.id], item.id))
            while remaining and available_rooms:
                group = max(remaining, key=lambda key: remaining[key])
                room = available_rooms.pop(0)
                subject_group_class_ids.setdefault(group, []).append(room.id)
                remaining[group] -= capacity_by_class[room.id]
                if remaining[group] <= 0:
                    remaining.pop(group)
            active_ids = {room_id for room_ids in subject_group_class_ids.values() for room_id in room_ids}
            active_classes = [item for item in classes if item.id in active_ids]
            required_class_count = len(active_classes)
            selected_capacity = sum(capacity_by_class[item.id] for item in active_classes)
        else:
            for item in classes:
                required_class_count += 1
                selected_capacity += capacity_by_class[item.id]
                if selected_capacity >= len(students):
                    break
            active_classes = classes[:required_class_count] if selected_capacity >= len(students) else classes
    else:
        active_classes = classes

    assignments: list[dict] = []
    class_rows = {item.id: {"id": item.id, "name": item.name, "capacity": capacity_by_class[item.id], "student_count": 0, "male_count": 0, "female_count": 0, "students": []} for item in active_classes}
    class_order = [item.id for item in active_classes]
    existing_student_count = 0
    if not body.overwrite_existing and class_order:
        existing_students = list((await session.execute(select(Student).where(
            Student.tenant_id == tenant_id,
            Student.grade_id == body.grade_id,
            Student.class_id.in_(class_order),
            Student.status == StudentStatus.studying,
        ))).scalars().all())
        add_existing_class_counts(class_rows, existing_students)
        existing_student_count = len(existing_students)
    pointer = 0
    for student in students:
        selected_id = None
        available = [
            class_rows[class_id]
            for class_id in class_order
            if class_rows[class_id]["student_count"] < capacity_by_class[class_id]
        ]
        if body.strategy == "subject_choice" and available:
            group = subject_group_by_student.get(student.id, "未完成选科")
            group_class_ids = subject_group_class_ids.get(group, class_order)
            group_available = [row for row in available if row["id"] in group_class_ids]
            if group_available:
                selected_id = min(
                    group_available,
                    key=lambda row: (row["student_count"], class_order.index(row["id"])),
                )["id"]
        elif available and body.balance_gender:
            gender_key = "male_count" if student.gender == Gender.male else "female_count"
            selected_id = min(
                available,
                key=lambda row: (row[gender_key], row["student_count"], class_order.index(row["id"])),
            )["id"]
            pointer = (class_order.index(selected_id) + 1) % len(class_order)
        else:
            for offset in range(len(class_order)):
                candidate_id = class_order[(pointer + offset) % len(class_order)]
                if class_rows[candidate_id]["student_count"] < capacity_by_class[candidate_id]:
                    selected_id = candidate_id
                    pointer = (class_order.index(candidate_id) + 1) % len(class_order)
                    break
        if selected_id is None:
            continue
        row = class_rows[selected_id]
        row["student_count"] += 1
        row["male_count"] += int(student.gender == Gender.male)
        row["female_count"] += int(student.gender == Gender.female)
        row["students"].append({"id": student.id, "name": student.name, "student_no": student.student_no, "gender": student.gender.value})
        assignments.append({"student_id": student.id, "class_id": selected_id})
    summaries = []
    for row in class_rows.values():
        summaries.append({**{key: value for key, value in row.items() if key != "students"}, "students": row["students"]})
    return {"grade_id": body.grade_id, "strategy": body.strategy,
            "classes": summaries, "assignments": assignments,
            "available_class_count": len(classes), "required_class_count": len(active_classes),
            "unused_class_count": max(0, len(classes) - len(active_classes)),
            "unassigned_count": len(students) - len(assignments), "total_students": len(students),
            "assigned_student_count": existing_student_count + len(assignments)}


@router.post("/classes/auto-assign/preview", summary="预览自动行政分班")
async def preview_auto_class_assignment(
    body: AutoClassAssignmentIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    return {"code": 0, "message": "ok", "data": await build_auto_class_assignment(body, session, tenant_id)}


@router.post("/classes/auto-assign", summary="执行自动行政分班")
async def execute_auto_class_assignment(
    body: AutoClassAssignmentIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    result = await build_auto_class_assignment(body, session, tenant_id)
    assignment_by_student = {item["student_id"]: item["class_id"] for item in result["assignments"]}
    if assignment_by_student:
        students = list((await session.execute(select(Student).where(Student.id.in_(assignment_by_student)))).scalars().all())
        target_classes = list((await session.execute(select(Class).where(
            Class.tenant_id == tenant_id, Class.id.in_(set(assignment_by_student.values())),
        ))).scalars().all())
        class_by_id = {item.id: item for item in target_classes}
        for student in students:
            target = class_by_id[assignment_by_student[student.id]]
            grade = await session.get(Grade, target.grade_id)
            cohort_label = normalize_cohort_label(target.cohort_label) or (expected_cohort_label(target.academic_year, grade.level) if grade else "")
            membership = (await session.execute(select(StudentClassMembership).where(
                StudentClassMembership.tenant_id == tenant_id,
                StudentClassMembership.student_id == student.id,
                StudentClassMembership.academic_year == target.academic_year,
                StudentClassMembership.term == target.term,
                StudentClassMembership.grade_id == target.grade_id,
                StudentClassMembership.cohort_label == cohort_label,
            ))).scalar_one_or_none()
            if membership is None:
                membership = StudentClassMembership(
                    tenant_id=tenant_id, student_id=student.id, class_id=target.id,
                    grade_id=target.grade_id, cohort_label=cohort_label,
                    academic_year=target.academic_year, term=target.term, status="active",
                )
            else:
                membership.class_id = target.id
                membership.status = "active"
            session.add(membership)
            student.class_id = target.id
            session.add(student)
            try:
                await sync_student_grade_membership(
                    session, tenant_id=tenant_id, student=student,
                    grade_id=body.grade_id, academic_year=target.academic_year,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"code": 0, "message": "ok", "data": result}


# ---------- 学生 ----------
@router.get("/students", summary="学生列表（按班级）")
async def list_students(class_id: int | None = None,
                        campus_id: int | None = None,
                        grade_id: int | None = None,
                        academic_year: str | None = None,
                        term: str | None = None,
                        cohort_label: str | None = None,
                        session: AsyncSession = Depends(get_session),
                        user=Depends(get_current_user)):
    scoped = bool(academic_year and term)
    if scoped:
        join_scope = (StudentClassMembership.student_id == Student.id) & (StudentClassMembership.tenant_id == user.tenant_id) & (StudentClassMembership.academic_year == academic_year) & (StudentClassMembership.term == term) & (StudentClassMembership.status == "active")
        if grade_id is not None:
            join_scope = join_scope & (StudentClassMembership.grade_id == grade_id)
        if cohort_label:
            join_scope = join_scope & (StudentClassMembership.cohort_label == normalize_cohort_label(cohort_label))
        stmt = select(Student, StudentClassMembership).outerjoin(StudentClassMembership, join_scope).where(Student.tenant_id == user.tenant_id).order_by(StudentClassMembership.class_id, Student.roster_order, Student.id)
    else:
        stmt = select(Student, None).where(Student.tenant_id == user.tenant_id).order_by(Student.class_id, Student.roster_order, Student.id)
    user_roles = set(getattr(user, "roles", []) or [])
    is_teacher = getattr(user, "role", None) in {"teacher", "head_teacher", "subject_teacher"} or "teacher" in user_roles
    if is_teacher:
        managed_class_ids = list((await session.execute(select(TeachingAssignment.class_id).where(
            TeachingAssignment.tenant_id == user.tenant_id,
            TeachingAssignment.teacher_id == user.id,
            TeachingAssignment.academic_year == academic_year if scoped else True,
            TeachingAssignment.term == term if scoped else True,
        ).distinct())).scalars().all())
        head_class_ids = list((await session.execute(select(Class.id).where(
            Class.tenant_id == user.tenant_id,
            or_(Class.head_teacher_id == user.id, Class.deputy_head_teacher_id == user.id),
            Class.academic_year == academic_year if scoped else True,
            Class.term == term if scoped else True,
            Class.grade_id == grade_id if grade_id is not None else True,
        ))).scalars().all())
        managed_class_ids = list(set(managed_class_ids) | set(head_class_ids))
        if scoped:
            stmt = stmt.where(StudentClassMembership.class_id.in_(managed_class_ids)) if managed_class_ids else stmt.where(Student.id == -1)
        else:
            stmt = stmt.where(Student.class_id.in_(managed_class_ids)) if managed_class_ids else stmt.where(Student.id == -1)
    if class_id is not None:
        stmt = stmt.where(StudentClassMembership.class_id == class_id) if scoped else stmt.where(Student.class_id == class_id)
    if campus_id is not None:
        stmt = stmt.where(Student.campus_id == campus_id)
    if grade_id is not None and not scoped:
        stmt = stmt.where(Student.grade_id == grade_id)
    rows = list((await session.execute(stmt)).all())
    classes = list((await session.execute(select(Class))).scalars().all())
    class_names = {item.id: item.name for item in classes}
    grades = list((await session.execute(select(Grade))).scalars().all())
    grade_names = {item.id: item.name for item in grades}
    data = []
    for item, membership in rows:
        row = item.model_dump()
        effective_class_id = membership.class_id if membership else (None if scoped else item.class_id)
        effective_grade_id = membership.grade_id if membership else (None if scoped else item.grade_id)
        row["class_id"] = effective_class_id
        row["class_name"] = class_names.get(effective_class_id)
        row["grade_id"] = effective_grade_id
        row["grade_name"] = grade_names.get(effective_grade_id)
        data.append(row)
    return {"code": 0, "message": "ok", "data": data}


@router.post("/students", summary="新增学生", status_code=201)
async def create_student(body: StudentIn, session: AsyncSession = Depends(get_session),
                         user=Depends(get_current_user),
                         tenant_id: int = Depends(get_current_tenant)):
    student_no = normalize_entity_name(body.student_no)
    if student_no:
        duplicate = (await session.execute(select(Student.id).where(
            Student.tenant_id == tenant_id, Student.student_no == student_no,
        ))).scalar()
        if duplicate:
            raise HTTPException(status_code=422, detail=f"学号「{student_no}」已存在")
    student = Student(**body.model_dump(), tenant_id=tenant_id, student_no=student_no)
    session.add(student)
    await session.flush()
    if student.class_id is not None:
        target = await session.get(Class, student.class_id)
        grade = await session.get(Grade, target.grade_id) if target else None
        if target is None or target.tenant_id != tenant_id:
            raise HTTPException(status_code=422, detail="行政班不存在")
        cohort_label = normalize_cohort_label(target.cohort_label) or (expected_cohort_label(target.academic_year, grade.level) if grade else "")
        session.add(StudentClassMembership(
            tenant_id=tenant_id, student_id=student.id, class_id=target.id,
            grade_id=target.grade_id, cohort_label=cohort_label,
            academic_year=target.academic_year, term=target.term, status="active",
        ))
    if student.grade_id is not None:
        try:
            await sync_student_grade_membership(
                session, tenant_id=tenant_id, student=student,
                grade_id=student.grade_id, academic_year=await current_academic_year(session, tenant_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(student)
    return {"code": 0, "message": "ok", "data": student.model_dump()}


@router.post("/students/simulate", summary="批量生成模拟学生", status_code=201)
async def simulate_students(
    body: StudentSimulationIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    """按届别和年级生成待分班学生，并同步学生年级关联。"""
    total = body.male_count + body.female_count
    if total <= 0:
        raise HTTPException(status_code=422, detail="男生和女生人数至少填写一项")

    cohort_label = normalize_cohort_label(body.cohort_label)
    if not cohort_label:
        raise HTTPException(status_code=422, detail="届别不能为空")
    grade = (await session.execute(select(Grade).where(
        Grade.id == body.grade_id,
        Grade.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if grade is None:
        raise HTTPException(status_code=404, detail="目标年级不存在或不属于当前学校")

    academic_year = await current_academic_year(session, tenant_id)
    grade_unit = (await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type == "grade_group",
        OrganizationUnit.grade_id == body.grade_id,
        OrganizationUnit.academic_year == academic_year,
        OrganizationUnit.cohort_label == cohort_label,
        OrganizationUnit.status == "active",
    ).order_by(OrganizationUnit.id))).scalars().first()
    if grade_unit is None:
        raise HTTPException(status_code=422, detail=f"当前学年尚未配置{cohort_label}届{grade.name}对应的年级部")

    prefix = f"SIM-{cohort_label}-G{body.grade_id}-"
    existing_numbers = set((await session.execute(select(Student.student_no).where(
        Student.tenant_id == tenant_id,
        Student.student_no.like(f"{prefix}%"),
    ))).scalars().all())
    sequence = 1
    generated: list[Student] = []
    for gender, count, gender_label in (
        (Gender.male, body.male_count, "男"),
        (Gender.female, body.female_count, "女"),
    ):
        for _ in range(count):
            while f"{prefix}{sequence:04d}" in existing_numbers:
                sequence += 1
            student_no = f"{prefix}{sequence:04d}"
            existing_numbers.add(student_no)
            generated.append(Student(
                tenant_id=tenant_id,
                campus_id=grade.campus_id,
                grade_id=grade.id,
                class_id=None,
                name=f"模拟{gender_label}生{cohort_label}-{sequence:04d}",
                gender=gender,
                student_no=student_no,
                roster_order=sequence,
            ))
            sequence += 1

    session.add_all(generated)
    await session.flush()
    for student in generated:
        await sync_student_grade_membership(
            session,
            tenant_id=tenant_id,
            student=student,
            grade_id=grade.id,
            academic_year=academic_year,
        )
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "created": len(generated),
        "male_count": body.male_count,
        "female_count": body.female_count,
        "cohort_label": cohort_label,
        "grade_id": grade.id,
        "grade_name": grade.name,
        "academic_year": academic_year,
        "status": "待分班",
    }}


@router.patch("/students/assign-class", summary="批量行政分班或移回待分班")
async def assign_students_to_class(
    body: ClassAssignmentIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    if body.class_id is None and not (body.academic_year or body.term or body.grade_id or body.cohort_label):
        # Compatibility for legacy callers that still manage one global class pointer.
        await session.execute(update(Student).where(
            Student.tenant_id == tenant_id, Student.id.in_(body.student_ids),
        ).values(class_id=None))
        await session.commit()
        return {"code": 0, "message": "ok", "data": {"updated": len(body.student_ids), "class_id": None}}
    target = None
    if body.class_id is not None:
        target = await session.get(Class, body.class_id)
        if target is None or target.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="目标班级不存在")
        if (body.academic_year and body.academic_year != target.academic_year) or (body.term and body.term != target.term) or (body.grade_id and body.grade_id != target.grade_id):
            raise HTTPException(status_code=422, detail="目标班级与提交的届别、学年学期或年级范围不匹配")
        academic_year, term, grade_id = target.academic_year, target.term, target.grade_id
        grade = await session.get(Grade, target.grade_id)
        cohort_label = normalize_cohort_label(target.cohort_label) or (expected_cohort_label(target.academic_year, grade.level) if grade else "")
    else:
        academic_year = body.academic_year or await current_academic_year(session, tenant_id)
        term = body.term or await current_term(session, tenant_id)
        grade_id = body.grade_id
        cohort_label = normalize_cohort_label(body.cohort_label)
        if grade_id is None:
            raise HTTPException(status_code=422, detail="移回待分班时必须指定届别、学年学期和年级")
    students = list((await session.execute(
        select(Student).where(Student.id.in_(body.student_ids), Student.tenant_id == tenant_id)
    )).scalars().all())
    if len(students) != len(set(body.student_ids)):
        raise HTTPException(status_code=404, detail="部分学生不存在或不属于当前学校")
    for student in students:
        membership = (await session.execute(select(StudentClassMembership).where(
            StudentClassMembership.tenant_id == tenant_id,
            StudentClassMembership.student_id == student.id,
            StudentClassMembership.academic_year == academic_year,
            StudentClassMembership.term == term,
            StudentClassMembership.grade_id == grade_id,
            StudentClassMembership.cohort_label == (cohort_label or ""),
        ))).scalar_one_or_none()
        if body.class_id is None:
            if membership is not None:
                membership.status = "removed"
                session.add(membership)
            if membership is not None and student.class_id == membership.class_id:
                student.class_id = None
                session.add(student)
            continue
        if membership is None:
            membership = StudentClassMembership(
                tenant_id=tenant_id, student_id=student.id, class_id=target.id,
                grade_id=target.grade_id, cohort_label=cohort_label or "",
                academic_year=academic_year, term=term, status="active",
            )
        else:
            membership.class_id = target.id
            membership.status = "active"
        session.add(membership)
        student.class_id, student.grade_id, student.campus_id = target.id, target.grade_id, target.campus_id
        session.add(student)
        try:
            await sync_student_grade_membership(session, tenant_id=tenant_id, student=student, grade_id=target.grade_id, academic_year=academic_year)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "updated": len(students),
        "class_id": body.class_id,
        "academic_year": academic_year,
        "term": term,
        "grade_id": grade_id,
        "cohort_label": cohort_label,
    }}


class StudentGradeMembershipIn(BaseModel):
    student_id: int
    grade_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    status: Literal["active", "archived"] = "active"


@router.get("/student-grade-memberships", summary="学生年级部关联表")
async def list_student_grade_memberships(
    academic_year: str | None = None,
    grade_unit_id: int | None = None,
    grade_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    stmt = select(StudentGradeMembership).where(StudentGradeMembership.tenant_id == tenant_id)
    if academic_year:
        stmt = stmt.where(StudentGradeMembership.academic_year == academic_year)
    if grade_unit_id:
        stmt = stmt.where(StudentGradeMembership.grade_unit_id == grade_unit_id)
    if grade_id:
        stmt = stmt.where(StudentGradeMembership.grade_id == grade_id)
    rows = list((await session.execute(stmt.order_by(StudentGradeMembership.id))).scalars().all())
    student_ids = [row.student_id for row in rows]
    grade_ids = [row.grade_id for row in rows]
    unit_ids = [row.grade_unit_id for row in rows]
    students = {item.id: item for item in (await session.execute(select(Student).where(Student.id.in_(student_ids)))).scalars().all()} if student_ids else {}
    grades = {item.id: item for item in (await session.execute(select(Grade).where(Grade.id.in_(grade_ids)))).scalars().all()} if grade_ids else {}
    units = {item.id: item for item in (await session.execute(select(OrganizationUnit).where(OrganizationUnit.id.in_(unit_ids)))).scalars().all()} if unit_ids else {}
    return {"code": 0, "message": "ok", "data": [{
        **row.model_dump(),
        "student_name": students.get(row.student_id).name if students.get(row.student_id) else None,
        "student_no": students.get(row.student_id).student_no if students.get(row.student_id) else None,
        "grade_name": grades.get(row.grade_id).name if grades.get(row.grade_id) else None,
        "grade_unit_name": units.get(row.grade_unit_id).name if units.get(row.grade_unit_id) else None,
    } for row in rows]}


@router.post("/student-grade-memberships/sync", summary="按学生当前年级回填关联表")
async def sync_student_grade_memberships(
    academic_year: str,
    student_ids: list[int] | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    stmt = select(Student).where(Student.tenant_id == tenant_id, Student.grade_id.is_not(None))
    if student_ids:
        stmt = stmt.where(Student.id.in_(student_ids))
    students = list((await session.execute(stmt)).scalars().all())
    for student in students:
        try:
            await sync_student_grade_membership(
                session, tenant_id=tenant_id, student=student,
                grade_id=student.grade_id, academic_year=academic_year,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"synced": len(students)}}


@router.patch("/students/{student_id}", summary="更新学生状态")
async def update_student_status(
    student_id: int,
    body: StudentStatusUpdateIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    student = await session.get(Student, student_id)
    if student is None or student.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="学生不存在")
    student.status = body.status
    session.add(student)
    await session.commit()
    await session.refresh(student)
    return {"code": 0, "message": "ok", "data": student.model_dump()}


@router.get("/students/count", summary="学生总数")
async def count_students(session: AsyncSession = Depends(get_session),
                         user=Depends(get_current_user),
                         tenant_id: int = Depends(get_current_tenant)):
    result = await session.execute(
        select(func.count()).select_from(Student).where(Student.tenant_id == tenant_id)
    )
    return {"code": 0, "message": "ok", "data": {"total": result.scalar_one()}}
