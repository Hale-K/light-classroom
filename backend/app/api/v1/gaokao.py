"""New-gaokao subject choice, teaching-class formation, and walk scheduling API."""
from __future__ import annotations

from collections import Counter, defaultdict
import asyncio
import hashlib
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict, model_validator
from sqlalchemy import and_, delete, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user, require_choice_viewer, require_head_teacher, require_management_user, resolve_choice_view_access
from app.db.session import get_session
from app.models.gaokao import (
    GaokaoScheme,
    StudentSubjectChoice,
    TeachingClass,
    TeachingClassSchedule,
    TeachingClassStudent,
    TeachingSubjectHourPlan,
    WalkSchedulingPlan, WalkSchedulingSlot, WalkSchedulingRoom,
)
from app.models.facility import Building, ResourceAllocationRule, Room, RoomCohortAllocation
from app.services.org.cohort import expected_cohort_label, normalize_cohort_label
from app.models.org import (
    Class, Grade, Student, StudentGradeMembership, StudentClassMembership, Subject, TeachingAssignment,
    Tenant, TenantConfig, User, OrganizationUnit, StaffAppointment, Schedule, CourseHourPlan,
)
from app.models.enums import BaseUserRole, UserStatus
from app.services.academic.gaokao import (
    SubjectChoice,
    SubjectChoicePolicy,
    form_teaching_classes,
    get_subject_choice_strategy,
    resolve_selection_phase,
    validate_scheme_configuration,
)

router = APIRouter(prefix="/gaokao", tags=["新高考走班"])


class WalkRegroupAutoIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    grade_id: int = Field(ge=1)
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(pattern=r'^[12]$')
    capacity: int = Field(default=45, ge=1, le=100)
    capacity_overflow: int = Field(default=5, ge=0, le=10)
    weekdays: list[int] = Field(default_factory=lambda: list(range(1, 7)))
    periods: list[int] = Field(default_factory=lambda: list(range(1, 8)))

    @model_validator(mode='after')
    def validate_slots(self):
        WalkRegroupPreviewIn(**self.model_dump(), a_groups={1: 0}, b_groups={1: 0},
                             b_excluded_subject={0: 1})
        return self


class WalkRegroupSaveIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    grade_id: int = Field(ge=1)
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(pattern=r'^[12]$')
    preview_token: str = Field(min_length=1, max_length=50)
    confirm_replace: Literal[True]


@router.post('/teaching-classes/regroup-plan', dependencies=[Depends(require_management_user)],
             summary='联合预览重新分组和课表')
async def preview_regroup_plan(body: WalkRegroupAutoIn, session: AsyncSession = Depends(get_session),
                              tenant_id: int = Depends(get_current_tenant)):
    from app.services.scheduling.walk_regroup_save import preview_plan
    return {'code': 0, 'message': 'ok', 'data': await preview_plan(body, session, tenant_id)}


@router.post('/teaching-classes/regroup-save', dependencies=[Depends(require_management_user)],
             summary='保存联合分组和课表（不备份旧数据）')
async def save_regroup_plan(body: WalkRegroupSaveIn, session: AsyncSession = Depends(get_session),
                           tenant_id: int = Depends(get_current_tenant),
                           user: User = Depends(get_current_user)):
    from app.services.scheduling.walk_regroup_save import save_plan
    return {'code': 0, 'message': 'ok', 'data': await save_plan(body, session, tenant_id, user.id)}


class WalkRegroupPreviewIn(BaseModel):
    """Explicit, opt-in walk partitions; no persistence or implicit rule replacement."""
    model_config = ConfigDict(extra='forbid')
    grade_id: int = Field(ge=1)
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(pattern=r'^[12]$')
    capacity: int = Field(default=45, ge=1, le=100)
    capacity_overflow: int = Field(default=5, ge=0, le=10)
    a_groups: dict[int, int] = Field(min_length=1, max_length=100)
    b_groups: dict[int, int] = Field(min_length=1, max_length=100)
    b_excluded_subject: dict[int, int] = Field(min_length=1, max_length=100)
    weekdays: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6], min_length=1, max_length=6)
    periods: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7], min_length=1, max_length=12)

    @model_validator(mode='after')
    def validate_partitions(self):
        if len(set(self.weekdays)) != len(self.weekdays) or any(d < 1 or d > 6 for d in self.weekdays):
            raise ValueError('星期必须为周一至周六，且不能重复')
        if sorted(self.periods) != list(range(1, max(self.periods) + 1)):
            raise ValueError('不空节范围必须从第1节连续选择，不能重复')
        if set(self.a_groups) != set(self.b_groups):
            raise ValueError('两组必须覆盖相同的行政班')
        if any(cid <= 0 or group < 0 for groups in (self.a_groups, self.b_groups)
               for cid, group in groups.items()):
            raise ValueError('行政班 ID 必须为正数，分组编号不能为负数')
        if set(self.b_excluded_subject) != set(self.b_groups.values()):
            raise ValueError('每个 B 组必须配置一个排除学科')
        if any(sid <= 0 for sid in self.b_excluded_subject.values()):
            raise ValueError('学科 ID 必须为正数')
        return self


@router.post('/teaching-classes/regroup-preview', dependencies=[Depends(require_management_user)],
             summary='预览走班重新分组（不保存）')
async def preview_walk_regroup(body: WalkRegroupPreviewIn,
                              session: AsyncSession = Depends(get_session),
                              tenant_id: int = Depends(get_current_tenant)):
    from app.services.scheduling.walk_regroup import regroup_walk_students
    grade, selected, admin_by_student = await _regroup_roster(body, session, tenant_id)
    if not set(body.b_excluded_subject.values()).issubset(set().union(*selected.values())):
        raise HTTPException(status_code=422, detail='排除学科不在当前学生选科中')
    if set(body.a_groups) != set(admin_by_student.values()):
        raise HTTPException(status_code=422, detail='分组必须覆盖本学期所有在读行政班，不能包含其他班级')
    result = await asyncio.to_thread(regroup_walk_students, selected, admin_by_student,
        body.a_groups, body.b_groups, body.b_excluded_subject,
        capacity=body.capacity + body.capacity_overflow)
    if result['status'] == 'feasible':
        result.update(await _preview_regroup_calendar(body, session, tenant_id, grade,
            selected, admin_by_student, result))
    return {'code': 0, 'message': 'ok', 'data': {**result, 'saved': False,
        'student_count': len(selected),
        'warnings': ['分组及课表仅预览，未修改原数据；联合排课不创建或修改用户规则']}}


async def _regroup_roster(body, session, tenant_id):
    grade = await session.get(Grade, body.grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail='年级不存在')
    student_ids = await _grade_student_ids(session, tenant_id, body.grade_id, body.academic_year)
    choices = list((await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == tenant_id,
        StudentSubjectChoice.student_id.in_(student_ids),
        StudentSubjectChoice.academic_year == body.academic_year,
        StudentSubjectChoice.effective_term == body.term,
        StudentSubjectChoice.status.in_(['confirmed', 'locked'])))).scalars())
    if not student_ids or len(choices) != len(student_ids):
        raise HTTPException(status_code=422, detail='请先完成本年级所有学生的选科确认')
    selected = {c.student_id: set(c.secondary_subject_ids) for c in choices}
    if any(len(subjects) != 2 for subjects in selected.values()):
        raise HTTPException(status_code=422, detail='当前预览仅支持每名学生两个再选走班学科')
    classes = await _student_term_classes(session, tenant_id, student_ids,
        body.academic_year, body.term, body.grade_id)
    admin_by_student = {sid: cls.id for sid, cls in classes.items()}
    return grade, selected, admin_by_student


async def _student_term_classes(session, tenant_id, student_ids, academic_year, term, grade_id=None):
    """Use actual semester memberships, never infer current classes from legacy names."""
    query = select(StudentClassMembership.student_id, Class).join(
        Class, Class.id == StudentClassMembership.class_id).where(
        StudentClassMembership.tenant_id == tenant_id,
        StudentClassMembership.student_id.in_(student_ids),
        StudentClassMembership.academic_year == academic_year,
        StudentClassMembership.term == term,
        StudentClassMembership.status == 'active',
        Class.tenant_id == tenant_id, Class.academic_year == academic_year, Class.term == term,
        Class.grade_id == StudentClassMembership.grade_id)
    if grade_id is not None:
        query = query.where(StudentClassMembership.grade_id == grade_id)
    rows = (await session.execute(query)).all()
    result = {}
    for sid, cls in rows:
        if sid in result:
            raise HTTPException(status_code=422, detail='本学期行政班归属重复，请先修正分班记录')
        result[sid] = cls
    if set(result) != set(student_ids):
        raise HTTPException(status_code=422, detail=f'还有 {len(set(student_ids) - set(result))} 名学生未分入本学期行政班')
    return result


async def _preview_regroup_calendar(body, session, tenant_id, grade, selected, admins, draft):
    from app.api.v1.scheduling import GenerateIn, _generation_assignment_payloads, _load_rule_group, _load_grid_config
    from app.services.scheduling.grid_slots import allowed_slots as configured_slots
    from app.services.scheduling.walk_regroup_calendar import trial_calendar, audit_draft, check_hour_bounds
    from app.services.scheduling.walk_regroup_save import fixed_walk_class_mapping
    from app.services.scheduling.rules import generation_subject_allowed_slots, rules_for_schedule
    assignments = await _generation_assignment_payloads(session, GenerateIn(
        academic_year=body.academic_year, term=body.term,
        class_ids=sorted(set(admins.values()))), tenant_id)
    if any(a['week_parity'] != 'all' or a['evening_periods_odd'] or a['evening_periods_even']
           or any(float(a[key]) != int(a[key]) for key in ('weekly_periods', 'weekday_periods', 'saturday_periods'))
           for a in assignments):
        raise HTTPException(status_code=422, detail='当前联合预览只支持每周相同的整数白天课时')
    subjects = set().union(*selected.values())
    plans = list((await session.execute(select(TeachingSubjectHourPlan).where(
        TeachingSubjectHourPlan.tenant_id == tenant_id, TeachingSubjectHourPlan.grade_id == body.grade_id,
        TeachingSubjectHourPlan.academic_year == body.academic_year, TeachingSubjectHourPlan.term == body.term,
        TeachingSubjectHourPlan.subject_id.in_(subjects)))).scalars())
    if {p.subject_id for p in plans} != subjects or len({p.weekly_periods for p in plans}) != 1:
        raise HTTPException(status_code=422, detail='请配置两个走班学科等课时；当前分组预览不支持不等课时')
    hours = plans[0].weekly_periods
    plans_by_subject = {p.subject_id: p for p in plans}
    for c in draft['classes']:
        plan = plans_by_subject[c['subject_id']]
        c['weekday_periods'] = plan.weekday_periods
        c['weekend_periods'] = plan.weekend_periods
    required_slots = {(d, p) for d in body.weekdays for p in body.periods}
    grid = await _load_grid_config(session, tenant_id, body.academic_year, body.term, body.grade_id)
    daytime = configured_slots(grid, 'daytime')
    slots = sorted(s for s in daytime['odd'] & daytime['even'] if s[0] in body.weekdays)
    if not grid['configured'] or not required_slots.issubset(slots):
        raise HTTPException(status_code=422, detail='最低排满范围包含未开放的白天课位，请先检查课位配置')
    totals = defaultdict(lambda: [0, 0])
    for a in assignments:
        totals[a['class_id']][0] += a['weekday_periods']
        totals[a['class_id']][1] += a['saturday_periods']
    if set(totals) != set(admins.values()):
        raise HTTPException(status_code=422, detail='存在行政班未配置公共课课时，请先检查课时和任教关系')
    profiles = {(admins[sid], tuple(sorted(choices))) for sid, choices in selected.items()}
    for admin_id, choices in sorted(profiles):
        work = totals[admin_id][0]
        weekend = totals[admin_id][1]
        selected_plans = [plans_by_subject[sid] for sid in choices]
        split = all(p.weekday_periods is not None and p.weekend_periods is not None for p in selected_plans)
        error = check_hour_bounds(sum(totals[admin_id]) + sum(p.weekly_periods for p in selected_plans),
            work + sum(p.weekday_periods for p in selected_plans) if split else None,
            weekend + sum(p.weekend_periods for p in selected_plans) if split else None,
            slots, required_slots)
        if error:
            raise HTTPException(status_code=422, detail=f'行政班ID {admin_id}的学生：{error}（公共课{int(sum(totals[admin_id]))}节＋走班{sum(p.weekly_periods for p in selected_plans)}节）')
    saturday_totals = {int(h[1]) for h in totals.values()}
    if len(saturday_totals) != 1:
        raise HTTPException(status_code=422, detail='当前联合预览要求各行政班周六公共课课时相同')
    saturday_walk = max(0, sum(d == 6 for d, _ in required_slots) - saturday_totals.pop())
    saturday_hours = {'A': saturday_walk // 2, 'B': saturday_walk - saturday_walk // 2}
    if any(h < 0 or h > hours for h in saturday_hours.values()):
        raise HTTPException(status_code=422, detail='周六课时不满足走班分组要求')
    old_classes = list((await session.execute(select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id, TeachingClass.grade_id == body.grade_id,
        TeachingClass.academic_year == body.academic_year, TeachingClass.term == body.term)
        .order_by(TeachingClass.subject_id, TeachingClass.sequence))).scalars())
    try:
        fixed_teachers, fixed_class_ids = fixed_walk_class_mapping(
            [c for c in old_classes if c.subject_id in subjects], draft['classes'])
    except ValueError as error:
        subject_names = dict((await session.execute(select(Subject.id, Subject.name).where(
            Subject.id.in_(subjects)))).all())
        detail = str(error)
        for subject_id, subject_name in subject_names.items():
            detail = detail.replace(f'学科 {subject_id}', f'{subject_name}')
        raise HTTPException(status_code=422, detail=detail) from error
    teachers = defaultdict(set)
    for c in draft['classes']:
        teachers[c['subject_id']].add(fixed_teachers[c['id']])
    required_room_capacity = max((c['size'] for c in draft['classes']), default=0)
    rooms = [r for r in await _shared_teaching_rooms(session, tenant_id, grade, body.academic_year, body.term)
             if r.capacity >= required_room_capacity]
    if not rooms:
        raise HTTPException(status_code=422, detail='没有满足班额的共享教室')
    external, blocked_rooms = set(), defaultdict(set)
    for model in (Schedule, TeachingClassSchedule):
        query = select(model).where(model.tenant_id == tenant_id, model.academic_year == body.academic_year,
                                    model.term == body.term)
        query = query.where(model.class_id.not_in(set(admins.values()))) if model == Schedule else query.where(
            model.teaching_class_id.not_in([c.id for c in old_classes]))
        for row in (await session.execute(query)).scalars():
            slot = row.weekday, row.period
            external.add((row.teacher_id, slot))
            for room in rooms:
                if row.room in {room.name, f'楼栋{room.building_id} · {room.name}'}:
                    blocked_rooms[slot].add(room.id)
    group = await _load_rule_group(session, tenant_id, body.academic_year, body.term, grade_id=body.grade_id)
    allowed = generation_subject_allowed_slots(rules_for_schedule(group, 'admin'))
    calendar = await asyncio.to_thread(trial_calendar, draft, assignments, set(admins.values()),
        body.a_groups, body.b_groups, teachers, len(rooms), external, slots=slots,
        phase_hours=hours, saturday_hours=saturday_hours, subject_allowed=allowed, blocked_rooms=blocked_rooms,
        required_slots=required_slots, fixed_teachers=fixed_teachers)
    if calendar['status'] not in ('OPTIMAL', 'FEASIBLE'):
        return {'status': calendar['status'].lower(), 'schedule_validated': False}
    report, placements = audit_draft(draft, calendar, selected, admins, assignments,
        [{'id': r.id, 'capacity': r.capacity} for r in rooms], external, slots=slots,
        phase_hours=hours, blocked_rooms=blocked_rooms, required_slots=required_slots)
    # The legacy blanket reservation/prefix rules are deliberately NOT treated as satisfied.
    # No rule is silently changed: the preview describes the required coordinated replacement.
    return {'schedule_validated': True, 'calendar': calendar, 'placements': placements,
        'audit': report, 'class_id_map': fixed_class_ids, 'current_rules_validated': False,
        'rules_requiring_review': [r.id for r in group.rules if r.enabled and r.code != 'subject_allowed_slots']}


def _map_student_admin_classes_to_term(
    student_class_ids: set[int],
    referenced_classes: list[Class],
    term_classes: list[Class],
) -> dict[int, int]:
    """Resolve roster class IDs to this term's class IDs without changing student records."""
    term_by_id = {int(item.id): int(item.id) for item in term_classes if item.id is not None}
    term_by_cohort_and_name: dict[tuple[int, str, str], list[int]] = defaultdict(list)
    term_by_grade_and_name: dict[tuple[int, str], list[int]] = defaultdict(list)
    for item in term_classes:
        if item.id is None:
            continue
        term_by_grade_and_name[(item.grade_id, item.name)].append(int(item.id))
        if item.cohort_label:
            term_by_cohort_and_name[(item.grade_id, item.cohort_label, item.name)].append(int(item.id))

    source_by_id = {int(item.id): item for item in referenced_classes if item.id is not None}
    mapping: dict[int, int] = {}
    for source_id in student_class_ids:
        if source_id in term_by_id:
            mapping[source_id] = source_id
            continue
        source = source_by_id.get(source_id)
        if source is None:
            raise ValueError("学生关联的行政班不存在，无法对应到当前学期")
        candidates = (
            term_by_cohort_and_name.get((source.grade_id, source.cohort_label, source.name), [])
            if source.cohort_label
            else term_by_grade_and_name.get((source.grade_id, source.name), [])
        )
        if len(candidates) != 1:
            raise ValueError("部分学生原行政班无法唯一对应到当前学期班级，请先核对班级名称和届别")
        mapping[source_id] = candidates[0]
    return mapping


async def _walk_teacher_subjects(session: AsyncSession, tenant_id: int, academic_year: str) -> dict[int, set[int]]:
    rows = (await session.execute(select(StaffAppointment.staff_id, OrganizationUnit.subject_id)
        .join(OrganizationUnit, OrganizationUnit.id == StaffAppointment.organization_unit_id)
        .where(StaffAppointment.tenant_id == tenant_id, OrganizationUnit.tenant_id == tenant_id,
               StaffAppointment.status == "active", StaffAppointment.position_code == "member",
               or_(StaffAppointment.academic_year.is_(None), StaffAppointment.academic_year == academic_year),
               OrganizationUnit.status == "active", OrganizationUnit.unit_type == "subject_group",
               OrganizationUnit.subject_id.is_not(None)))).all()
    result: dict[int, set[int]] = defaultdict(set)
    for teacher_id, subject_id in rows:
        result[teacher_id].add(subject_id)
    return result


@router.get("/teaching-classes/teachers", dependencies=[Depends(require_management_user)])
async def walk_teacher_options(academic_year: str, term: str = Query(pattern=r"^[12]$"),
                               session: AsyncSession = Depends(get_session), tenant_id: int = Depends(get_current_tenant)):
    teachers = (await session.execute(select(User).where(User.tenant_id == tenant_id,
        User.status == UserStatus.active, User.role == BaseUserRole.teacher).order_by(User.name))).scalars().all()
    subjects = await _walk_teacher_subjects(session, tenant_id, academic_year)
    admin_load: dict[int, float] = defaultdict(float)
    walk_load: dict[int, int] = defaultdict(int)
    for assignment in (await session.execute(select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id, TeachingAssignment.academic_year == academic_year,
        TeachingAssignment.term == term))).scalars().all():
        if assignment.teacher_id is not None:
            admin_load[assignment.teacher_id] += assignment.weekly_periods
    for item in (await session.execute(select(TeachingClass).where(TeachingClass.tenant_id == tenant_id,
        TeachingClass.academic_year == academic_year, TeachingClass.term == term))).scalars().all():
        if item.teacher_id is not None:
            walk_load[item.teacher_id] += item.weekly_periods
    return {"code": 0, "message": "ok", "data": [{"id": teacher.id, "name": teacher.name,
        "subject_ids": sorted(subjects.get(teacher.id, set())), "administrative_periods": admin_load[teacher.id],
        "walk_periods": walk_load[teacher.id], "total_periods": admin_load[teacher.id] + walk_load[teacher.id]} for teacher in teachers]}


class WalkTeacherChange(BaseModel):
    teaching_class_id: int
    teacher_id: int | None
    expected_teacher_id: int | None


class WalkConfigurationIn(BaseModel):
    grade_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(pattern=r"^[12]$")
    expected_revision: int = Field(ge=0)
    slots: list[tuple[int, int]] = Field(default_factory=list, max_length=84)
    room_ids: list[int] = Field(default_factory=list, max_length=500)


class WalkRecommendationIn(BaseModel):
    grade_id: int = Field(ge=1)
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(pattern=r"^[12]$")
    room_ids: list[int] | None = Field(default=None, max_length=500)
    forbidden_slots: list[tuple[int, int]] = Field(default_factory=list, max_length=84)


@router.post("/walk-configuration/recommend", dependencies=[Depends(require_management_user)])
async def recommend_walk_configuration(body: WalkRecommendationIn, session: AsyncSession = Depends(get_session),
                                       tenant_id: int = Depends(get_current_tenant)):
    from app.api.v1.scheduling import _load_grid_config
    from app.services.scheduling.grid_slots import allowed_slots
    from app.services.scheduling.walk_recommendation import recommend_walk_slots
    grade = await session.get(Grade, body.grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="年级不存在")
    grid = await _load_grid_config(session, tenant_id, body.academic_year, body.term, body.grade_id)
    if not grid['configured']:
        raise HTTPException(status_code=422, detail="请先保存本年级本学期基础课位")
    rooms = await _shared_teaching_rooms(session, tenant_id, grade, body.academic_year, body.term)
    if body.room_ids:
        if not set(body.room_ids).issubset({r.id for r in rooms}):
            raise HTTPException(status_code=422, detail="所选教室不属于当前年级学期共享池")
        rooms = [r for r in rooms if r.id in body.room_ids]
    classes = list((await session.execute(select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id, TeachingClass.grade_id == body.grade_id,
        TeachingClass.academic_year == body.academic_year, TeachingClass.term == body.term))).scalars().all())
    class_ids = {c.id for c in classes}
    members = list((await session.execute(select(TeachingClassStudent.teaching_class_id, TeachingClassStudent.student_id)
        .where(TeachingClassStudent.tenant_id == tenant_id, TeachingClassStudent.teaching_class_id.in_(class_ids)))).all()) if class_ids else []
    students = set(await _grade_student_ids(session, tenant_id, body.grade_id, body.academic_year))
    choices = list((await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == tenant_id, StudentSubjectChoice.student_id.in_(students),
        StudentSubjectChoice.academic_year == body.academic_year, StudentSubjectChoice.effective_term == body.term,
        StudentSubjectChoice.status.in_(['confirmed', 'locked'])))).scalars().all()) if students else []
    if {c.student_id for c in choices} != students or not students:
        raise HTTPException(status_code=422, detail="请先完成当前年级全部学生的确认选科")
    schemes = {s.id: s for s in (await session.execute(select(GaokaoScheme).where(
        GaokaoScheme.tenant_id == tenant_id, GaokaoScheme.id.in_({c.scheme_id for c in choices})))).scalars().all()}
    by_id = {c.id: c for c in classes}
    teacher_ids = {c.teacher_id for c in classes if c.teacher_id is not None}
    teacher_names = dict((await session.execute(select(User.id, User.name).where(User.tenant_id == tenant_id,
        User.id.in_(teacher_ids), User.role == BaseUserRole.teacher, User.status == UserStatus.active))).all())
    active_teachers = set(teacher_names)
    if active_teachers != teacher_ids:
        raise HTTPException(status_code=422, detail="部分教学班教师已停用或不属于当前学校，请重新安排教师")
    student_subjects = defaultdict(Counter)
    for cid, sid in members:
        student_subjects[sid][by_id[cid].subject_id] += 1
    missing = 0
    for choice in choices:
        scheme = schemes.get(choice.scheme_id)
        if scheme is None:
            raise HTTPException(status_code=422, detail="学生选科方案不存在")
        required = set(get_subject_choice_strategy(scheme.mode).teaching_class_subject_ids(
            _subject_choice(choice), _choice_policy(scheme)))
        if set(student_subjects[choice.student_id]) != required or any(n != 1 for n in student_subjects[choice.student_id].values()):
            missing += 1
    if missing or any(sid not in students for _, sid in members):
        raise HTTPException(status_code=422, detail=f"有 {missing} 名学生的教学班名单与选科不一致，请先修正分班结果")
    blocked_students, blocked_teachers, blocked_rooms = defaultdict(set), defaultdict(set), defaultdict(set)
    admin = list((await session.execute(select(Schedule).where(Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year, Schedule.term == body.term))).scalars().all())
    current_classes = await _student_term_classes(session, tenant_id, students,
        body.academic_year, body.term, body.grade_id)
    admin_members = defaultdict(set)
    for sid, cls in current_classes.items():
        admin_members[cls.id].add(sid)
    admin_class_ids = set(admin_members)
    scheduled_class_ids = {row.class_id for row in admin if row.class_id in admin_class_ids}
    missing_admin_schedule = admin_class_ids - scheduled_class_ids
    if missing_admin_schedule:
        raise HTTPException(status_code=422, detail=(
            f"高一年级还有 {len(missing_admin_schedule)} 个行政班没有已生成的公共课课表。"
            "请先在「排课管理 → 课表」生成并保存行政班课表，再预览走班课表。"
        ))
    student_fixed_by_parity = {'odd': defaultdict(set), 'even': defaultdict(set)}
    for row in admin:
        slot = (row.weekday, row.period)
        if row.teacher_id: blocked_teachers[row.teacher_id].add(slot)
        for sid in admin_members[row.class_id]: blocked_students[sid].add(slot)
        if row.period < (grid.get('evening_start_period') or 13):
            for parity in student_fixed_by_parity:
                if row.week_parity in ('all', parity):
                    for sid in admin_members[row.class_id]:
                        student_fixed_by_parity[parity][sid].add(slot)
        for room in rooms:
            if row.room in {room.name, f"楼栋{room.building_id} · {room.name}"}:
                blocked_rooms[room.id].add(slot)
    # Other grades' saved walk timetables remain occupied; this grade is a fresh preview.
    others = list((await session.execute(select(TeachingClassSchedule).where(
        TeachingClassSchedule.tenant_id == tenant_id, TeachingClassSchedule.academic_year == body.academic_year,
        TeachingClassSchedule.term == body.term, TeachingClassSchedule.teaching_class_id.not_in(class_ids)))).scalars().all())
    for row in others:
        slot = (row.weekday, row.period)
        if row.teacher_id: blocked_teachers[row.teacher_id].add(slot)
        for room in rooms:
            if row.room in {room.name, f"楼栋{room.building_id} · {room.name}"}:
                blocked_rooms[room.id].add(slot)
    allowed = allowed_slots(grid, 'daytime')
    slots = allowed['odd'] & allowed['even']
    forbidden_slots = set(body.forbidden_slots)
    if any(not 1 <= day <= 7 or not 1 <= period <= 12 for day, period in forbidden_slots):
        raise HTTPException(status_code=422, detail="禁排时段必须在周一至周日、第1至12节之间")
    from app.api.v1.scheduling import _load_rule_group
    from app.services.scheduling.rules import (
        generation_global_forbidden_slots,
        generation_subject_allowed_slots,
        generation_subject_forbidden_slots,
        generation_teacher_forbidden_slots,
        rules_for_schedule,
    )
    rule_group = await _load_rule_group(session, tenant_id, body.academic_year, body.term, grade_id=body.grade_id)
    if rule_group is not None:
        rule_group = rules_for_schedule(rule_group, "walk")
    blocked_slots = set(forbidden_slots)
    blocked_subjects = defaultdict(set)
    if rule_group:
        blocked_slots.update(generation_global_forbidden_slots(rule_group))
        teacher_rules = generation_teacher_forbidden_slots(rule_group)
        for teacher_id, rule_slots in teacher_rules.items():
            blocked_teachers[teacher_id].update(rule_slots)
        for subject_id, rule_slots in generation_subject_forbidden_slots(rule_group).items():
            blocked_subjects[subject_id].update(rule_slots)
        subject_allow_lists = generation_subject_allowed_slots(rule_group)
        slot_universe = set(slots)
        for subject_id, allowed_slots in subject_allow_lists.items():
            blocked_subjects[subject_id].update(slot_universe - allowed_slots)
    gap_weekdays = None
    gap_periods = None
    contiguous_periods = None
    self_study_periods = None
    if rule_group:
        from app.services.scheduling.rules import compile_rule_group
        ready_ids = {r.rule_id for r in compile_rule_group(rule_group) if r.status == 'ready'}
        gap_rules = [r for r in rule_group.rules if r.enabled and r.id in ready_ids
                     and r.code == 'student_gap_minimize']
        if gap_rules:
            gap_weekdays = sorted({d for r in gap_rules for d in (r.weekdays or range(1, 8))})
            gap_periods = {day: sorted({p for r in gap_rules if day in (r.weekdays or range(1, 8))
                                       for p in (r.periods or range(1, 8))}) for day in gap_weekdays}
        contiguous_rules = [r for r in rule_group.rules if r.enabled and r.id in ready_ids
                            and r.code == 'student_contiguous' and not r.params.get('fill_self_study')]
        if contiguous_rules:
            contiguous_days = {d for r in contiguous_rules for d in (r.weekdays or range(1, 8))}
            contiguous_periods = {day: sorted({p for r in contiguous_rules
                if day in (r.weekdays or range(1, 8)) for p in r.periods}) for day in contiguous_days}
        study_rules = [r for r in rule_group.rules if r.enabled and r.id in ready_ids
                       and r.code == 'student_contiguous' and r.params.get('fill_self_study')]
        if study_rules:
            self_study_periods = {day: sorted({p for r in study_rules
                if day in (r.weekdays or range(1, 8)) for p in r.periods})
                for day in {d for r in study_rules for d in (r.weekdays or range(1, 8))}}
            if any((day, p) not in slots for day, periods in self_study_periods.items() for p in periods):
                raise HTTPException(status_code=422, detail='学生排满节次包含未开放课位，请先修改基础课位')
            # Keep home rooms available for the students not attending walk
            # lessons; do not let the walk solver borrow them in this window.
            study_slots = {(day, p) for day, periods in self_study_periods.items() for p in periods}
            for admin_class in term_classes:
                if admin_class.id in admin_members and admin_class.home_room_id:
                    blocked_rooms[admin_class.home_room_id].update(study_slots)
    result = await asyncio.to_thread(recommend_walk_slots,
        [dict(id=c.id, name=c.name, subject_id=c.subject_id, teacher_id=c.teacher_id,
              teacher_name=teacher_names.get(c.teacher_id),
              weekly_periods=c.weekly_periods, weekday_periods=c.weekday_periods,
              weekend_periods=c.weekend_periods) for c in classes],
        members, [dict(id=r.id, name=r.name, capacity=r.capacity) for r in rooms], sorted(slots - blocked_slots),
        blocked_students=blocked_students, blocked_teachers=blocked_teachers, blocked_rooms=blocked_rooms,
        blocked_subjects=blocked_subjects, blocked_slots=blocked_slots,
        student_gap_weekdays=gap_weekdays, student_fixed_by_parity=student_fixed_by_parity,
        student_gap_periods=gap_periods, student_contiguous_periods=contiguous_periods,
        student_self_study_periods=self_study_periods)
    rule_results = []
    rule_warnings = []
    if result.get('status') == 'feasible':
        from app.services.scheduling.core import ScheduleItem
        from app.services.scheduling.rules import blocking_rule_results, evaluate_rule_group
        if rule_group:
            subjects_by_class = {c.id: c.subject_id for c in classes}
            room_by_id = {r.id: r for r in rooms}
            admin_rule_items = [ScheduleItem(
                assignment_id=row.id, class_id=row.class_id, subject_id=row.subject_id,
                teacher_id=row.teacher_id, weekday=row.weekday, period=row.period,
                room=row.room, week_parity=row.week_parity,
            ) for row in admin]
            rule_items = [ScheduleItem(
                assignment_id=-int(item['teaching_class_id']),
                class_id=-int(item['teaching_class_id']),
                subject_id=subjects_by_class[int(item['teaching_class_id'])],
                teacher_id=int(item['teacher_id']), weekday=int(item['weekday']), period=int(item['period']),
                room=f"楼栋{room_by_id[int(item['room_id'])].building_id} · {room_by_id[int(item['room_id'])].name}",
            ) for item in result.get('placements', [])]
            student_occupied = {parity: {sid: set(fixed.get(sid, set())) for sid in students}
                                for parity, fixed in student_fixed_by_parity.items()}
            walk_members = defaultdict(set)
            for cid, sid in members:
                walk_members[cid].add(sid)
            for placement in result.get('placements', []):
                for occupied in student_occupied.values():
                    for sid in walk_members[placement['teaching_class_id']]:
                        occupied[sid].add((placement['weekday'], placement['period']))
            from app.services.scheduling.student_gaps import build_student_self_study
            summary = evaluate_rule_group(rule_group, rule_items,
                evening_start_period=grid.get('evening_start_period'), schedule_mode="walk",
                shared_items=admin_rule_items, student_occupied_by_parity=student_occupied,
                student_self_study_by_parity=(build_student_self_study(student_occupied, self_study_periods)
                                             if self_study_periods else None))
            rule_results = [item.model_dump(mode='json') for item in summary.results]
            failed = blocking_rule_results(summary)
            if failed:
                result['status'] = 'blocked_rules'
                result['message'] = '当前方案未通过已启用的硬性排课规则，未生成课表'
                result['rule_failures'] = [
                    {'rule_id': item.rule_id, 'title': item.title, 'message': item.message}
                    for item in failed
                ]
            if any(rule.enabled and rule.priority == 'hard' and rule.target.type == 'class'
                   and rule.code in {'class_gap_free', 'class_slot_pattern', 'class_allowed_subjects'}
                   for rule in rule_group.rules):
                rule_warnings.append('班级目标规则按行政班 ID 校验；走班教学班是独立班级实体，班级目标规则不会错误套用到教学班。')
    result['rule_results'] = rule_results
    result['scope'] = dict(grade_id=body.grade_id, academic_year=body.academic_year, term=body.term)
    result['roster_student_count'] = len(students)
    result['warnings'] = rule_warnings
    admin_hours = defaultdict(float)
    for plan in (await session.execute(select(CourseHourPlan).where(CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.academic_year == body.academic_year, CourseHourPlan.term == body.term,
        CourseHourPlan.class_id.in_(admin_members)))).scalars().all():
        admin_hours[plan.class_id] += plan.weekly_periods
    walk_hours = defaultdict(int)
    for cid, sid in members: walk_hours[sid] += by_id[cid].weekly_periods
    total_hours = [admin_hours[cid] + walk_hours[sid] for cid, sids in admin_members.items() for sid in sids]
    if total_hours:
        result['combined_hours_min'], result['combined_hours_max'] = min(total_hours), max(total_hours)
    if any(cid not in admin_hours for cid in admin_members):
        result['warnings'].append("部分行政班尚未设置行政课时，总周课时仍需补齐核对。")
    return {"code": 0, "message": "ok", "data": result}


@router.get("/walk-configuration", dependencies=[Depends(require_management_user)])
async def get_walk_configuration(grade_id: int, academic_year: str, term: str = Query(pattern=r"^[12]$"),
                                 session: AsyncSession = Depends(get_session), tenant_id: int = Depends(get_current_tenant)):
    from app.api.v1.scheduling import _load_grid_config
    grade = await session.get(Grade, grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="年级不存在")
    plan = (await session.execute(select(WalkSchedulingPlan).where(WalkSchedulingPlan.tenant_id == tenant_id,
        WalkSchedulingPlan.grade_id == grade_id, WalkSchedulingPlan.academic_year == academic_year,
        WalkSchedulingPlan.term == term))).scalar_one_or_none()
    slots = (await session.execute(select(WalkSchedulingSlot).where(WalkSchedulingSlot.plan_id == plan.id)
        .order_by(WalkSchedulingSlot.weekday, WalkSchedulingSlot.period))).scalars().all() if plan else []
    rooms = (await session.execute(select(WalkSchedulingRoom).where(WalkSchedulingRoom.plan_id == plan.id)
        .order_by(WalkSchedulingRoom.room_id))).scalars().all() if plan else []
    grid = await _load_grid_config(session, tenant_id, academic_year, term, grade_id)
    available = await _shared_teaching_rooms(session, tenant_id, grade, academic_year, term)
    return {"code": 0, "message": "ok", "data": {"revision": plan.revision if plan else 0,
        "slots": [[row.weekday, row.period] for row in slots], "room_ids": [row.room_id for row in rooms],
        "grid_configured": grid["configured"], "daily_periods": grid["daily_periods"],
        "available_slots": [[day, period] for day in range(1, 8) for period in range(1, grid['daily_periods'][day - 1] + 1)
            if not any(s['weekday'] == day and s['period'] == period and s['slot_type'] == 'disabled' for s in grid.get('slot_overrides', []))],
        "available_rooms": [{"id": room.id, "name": room.name, "capacity": room.capacity} for room in available]}}


@router.put("/walk-configuration", dependencies=[Depends(require_management_user)])
async def save_walk_configuration(body: WalkConfigurationIn, session: AsyncSession = Depends(get_session),
                                  tenant_id: int = Depends(get_current_tenant)):
    from app.api.v1.scheduling import _load_grid_config
    grade = (await session.execute(select(Grade).where(Grade.id == body.grade_id,
        Grade.tenant_id == tenant_id).with_for_update())).scalar_one_or_none()
    if not grade:
        raise HTTPException(status_code=404, detail="年级不存在")
    grid = await _load_grid_config(session, tenant_id, body.academic_year, body.term, body.grade_id)
    if not grid["configured"]:
        raise HTTPException(status_code=422, detail="请先保存本学期课位结构")
    slots = set(body.slots)
    if any(not 1 <= day <= 7 or not 1 <= period <= grid["daily_periods"][day - 1] for day, period in slots):
        raise HTTPException(status_code=422, detail="所选时段不在本学期已保存的白天课位中")
    if grid.get('slot_overrides'):
        from app.services.scheduling.grid_slots import allowed_slots
        allowed = allowed_slots(grid, 'daytime')
        if not slots.issubset(allowed['odd'] & allowed['even']):
            raise HTTPException(status_code=422, detail="每周走班时段必须在单周和双周均启用")
    rooms = await _shared_teaching_rooms(session, tenant_id, grade, body.academic_year, body.term)
    if not set(body.room_ids).issubset({room.id for room in rooms}):
        raise HTTPException(status_code=422, detail="所选教室不属于本年级本学期可用共享池")
    plan = (await session.execute(select(WalkSchedulingPlan).where(WalkSchedulingPlan.tenant_id == tenant_id,
        WalkSchedulingPlan.grade_id == body.grade_id, WalkSchedulingPlan.academic_year == body.academic_year,
        WalkSchedulingPlan.term == body.term))).scalar_one_or_none()
    if (plan.revision if plan else 0) != body.expected_revision:
        raise HTTPException(status_code=409, detail="走班配置已被更新，请刷新后再保存")
    if plan:
        await session.execute(delete(WalkSchedulingSlot).where(WalkSchedulingSlot.plan_id == plan.id))
        await session.execute(delete(WalkSchedulingRoom).where(WalkSchedulingRoom.plan_id == plan.id))
        plan.revision += 1
    else:
        plan = WalkSchedulingPlan(tenant_id=tenant_id, grade_id=body.grade_id, academic_year=body.academic_year, term=body.term)
    session.add(plan)
    await session.flush()
    session.add_all([WalkSchedulingSlot(plan_id=plan.id, weekday=day, period=period) for day, period in sorted(slots)])
    session.add_all([WalkSchedulingRoom(plan_id=plan.id, room_id=room_id) for room_id in sorted(set(body.room_ids))])
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"revision": plan.revision}}


class WalkTeachersIn(BaseModel):
    grade_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(pattern=r"^[12]$")
    assignments: list[WalkTeacherChange] = Field(min_length=1, max_length=200)


@router.patch("/teaching-classes/teachers", dependencies=[Depends(require_management_user)])
async def assign_walk_teachers(body: WalkTeachersIn, session: AsyncSession = Depends(get_session),
                               tenant_id: int = Depends(get_current_tenant)):
    grade = (await session.execute(select(Grade).where(Grade.id == body.grade_id,
        Grade.tenant_id == tenant_id).with_for_update())).scalar_one_or_none()
    if grade is None:
        raise HTTPException(status_code=404, detail="年级不存在")
    ids = [change.teaching_class_id for change in body.assignments]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="同一个教学班不能重复提交")
    classes = {item.id: item for item in (await session.execute(select(TeachingClass).where(
        TeachingClass.id.in_(ids), TeachingClass.tenant_id == tenant_id, TeachingClass.grade_id == body.grade_id,
        TeachingClass.academic_year == body.academic_year, TeachingClass.term == body.term))).scalars().all()}
    if len(classes) != len(ids):
        raise HTTPException(status_code=404, detail="教学班不存在或不属于所选年级学期，请刷新")
    subjects = await _walk_teacher_subjects(session, tenant_id, body.academic_year)
    teacher_ids = {change.teacher_id for change in body.assignments if change.teacher_id is not None}
    teachers = {item.id for item in (await session.execute(select(User).where(User.id.in_(teacher_ids),
        User.tenant_id == tenant_id, User.status == UserStatus.active, User.role == BaseUserRole.teacher))).scalars().all()}
    changed = []
    for change in body.assignments:
        item = classes[change.teaching_class_id]
        if change.teacher_id is not None and (change.teacher_id not in teachers or item.subject_id not in subjects.get(change.teacher_id, set())):
            raise HTTPException(status_code=422, detail=f"「{item.name}」的教师不存在、已停用或未关联该学科组")
        if item.teacher_id == change.teacher_id:
            continue
        if item.teacher_id != change.expected_teacher_id:
            raise HTTPException(status_code=409, detail="任教关系已被调整，请刷新后再提交")
        changed.append((item, change.teacher_id))
    changed_ids = [item.id for item, _ in changed]
    if changed_ids and (await session.execute(select(TeachingClassSchedule.id).where(
        TeachingClassSchedule.teaching_class_id.in_(changed_ids)))).first():
        raise HTTPException(status_code=409, detail="所选教学班已有走班课表，不能直接更换或解除教师，请先处理课表调整")
    for item, teacher_id in changed:
        item.teacher_id = teacher_id
        session.add(item)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"updated": len(changed)}}


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
    term: str = Field(pattern=r"^[12]$")
    preview: bool = False
    replace_existing: bool = False
    preview_token: str | None = None
    capacity: int = Field(default=40, ge=20, le=60)
    weekly_periods: int = Field(default=3, ge=1, le=12)
    weekly_periods_by_subject: dict[int, int] = Field(default_factory=dict)
    primary_delivery_mode: str | None = Field(
        default=None,
        pattern=r"^(administrative|teaching_class)$",
        description="首选科目默认在行政班授课，也可按年级改为走班",
    )


class WalkHoursIn(BaseModel):
    weekly_periods: int | None = Field(default=None, ge=1, le=12)
    weekday_periods: int | None = Field(default=None, ge=0, le=12, strict=True)
    weekend_periods: int | None = Field(default=None, ge=0, le=12, strict=True)

    @model_validator(mode='after')
    def validate_hours(self):
        if self.weekday_periods is not None or self.weekend_periods is not None:
            if self.weekday_periods is None or self.weekend_periods is None:
                raise ValueError('请同时填写工作日和周末课时')
            total = self.weekday_periods + self.weekend_periods
            if not 1 <= total <= 12:
                raise ValueError('每周合计须为1到12节')
            if self.weekly_periods is not None and self.weekly_periods != total:
                raise ValueError('每周合计必须等于工作日加周末课时')
            self.weekly_periods = total
        elif self.weekly_periods is None:
            raise ValueError('请填写课时')
        return self


class UpdateTeachingSubjectHoursIn(WalkHoursIn):
    grade_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(pattern=r"^[12]$")
    subject_id: int


class UpdateTeachingClassHoursIn(WalkHoursIn):
    grade_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(pattern=r"^[12]$")


async def _walk_subject_hours(session: AsyncSession, tenant_id: int, grade_id: int,
                              academic_year: str, term: str, detailed: bool = False) -> dict:
    plans = (await session.execute(select(TeachingSubjectHourPlan).where(
        TeachingSubjectHourPlan.tenant_id == tenant_id,
        TeachingSubjectHourPlan.grade_id == grade_id,
        TeachingSubjectHourPlan.academic_year == academic_year,
        TeachingSubjectHourPlan.term == term,
    ))).scalars().all()
    return {str(item.subject_id): {
        'weekly_periods': item.weekly_periods, 'weekday_periods': item.weekday_periods,
        'weekend_periods': item.weekend_periods,
    } if detailed else item.weekly_periods for item in plans}


async def _shared_teaching_rooms(session: AsyncSession, tenant_id: int, grade: Grade,
                                 academic_year: str, term: str) -> list[Room]:
    """Current semester's allocation records are the only shared-room source."""
    cohort = expected_cohort_label(academic_year, grade.level)
    rows = (await session.execute(select(Room, RoomCohortAllocation.cohort_label).join(
        RoomCohortAllocation, RoomCohortAllocation.room_id == Room.id,
    ).join(ResourceAllocationRule, ResourceAllocationRule.id == RoomCohortAllocation.rule_id).join(
        Building, Building.id == Room.building_id,
    ).where(
        Room.tenant_id == tenant_id, Building.tenant_id == tenant_id,
        RoomCohortAllocation.tenant_id == tenant_id, ResourceAllocationRule.tenant_id == tenant_id,
        RoomCohortAllocation.academic_year == academic_year, RoomCohortAllocation.term == term,
        ResourceAllocationRule.academic_year == academic_year, ResourceAllocationRule.term == term,
        RoomCohortAllocation.allocation_mode == "shared", RoomCohortAllocation.status == "active",
        ResourceAllocationRule.allocation_mode == "shared", ResourceAllocationRule.status == "active",
        Room.is_schedulable.is_(True), Room.status == "available",
        Room.room_type.in_(["classroom", "laboratory", "computer"]),
        Building.campus_id == grade.campus_id if grade.campus_id else True,
    ).order_by(Room.id))).all()
    return list({room.id: room for room, label in rows if normalize_cohort_label(label) == cohort}.values())


class GenerateWalkScheduleIn(BaseModel):
    grade_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(pattern=r"^[12]$")
    room_ids: list[int] | None = Field(default=None, max_length=500)
    days: int = Field(default=5, ge=1, le=7)
    periods_per_day: int = Field(default=8, ge=1, le=12)
    forbidden_slots: list[tuple[int, int]] = Field(default_factory=list, max_length=84)


class ClearWalkScheduleIn(BaseModel):
    grade_id: int = Field(ge=1)
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(pattern=r"^[12]$")


class WalkClassSpacePoolIn(BaseModel):
    grade_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    # term is accepted for compatibility with existing clients but room rules are year-wide.
    term: str | None = Field(default=None, pattern=r"^(1|2)$")
    physics_room_ids: list[int] = Field(default_factory=list, max_length=500)
    history_room_ids: list[int] = Field(default_factory=list, max_length=500)
    shared_room_ids: list[int] = Field(default_factory=list, max_length=500)


def _walk_class_space_pool_key(grade_id: int, academic_year: str) -> str:
    return f"walkspace:{grade_id}:{academic_year}"


async def _walk_class_space_pool_value(
    session: AsyncSession,
    tenant_id: int,
    grade_id: int,
    academic_year: str,
    term: str | None = None,
) -> dict[str, Any]:
    grade = await session.get(Grade, grade_id)
    if not grade or grade.tenant_id != tenant_id or term not in {"1", "2"}:
        return {}
    rooms = await _shared_teaching_rooms(session, tenant_id, grade, academic_year, term)
    return {"shared_room_ids": [room.id for room in rooms]}


class ChoiceReviewIn(BaseModel):
    action: str = Field(pattern=r"^(approve|reject|reopen)$")


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


async def _grade_student_ids(
    session: AsyncSession,
    tenant_id: int,
    grade_id: int,
    academic_year: str,
) -> list[int]:
    # Student grade affiliation is independent from the administrative class.
    # Keep the class join as a legacy fallback, but don't make it a prerequisite:
    # class/room data may be cleared when setting up a new term.
    class_ids = list((await session.execute(select(Class.id).where(
        Class.tenant_id == tenant_id, Class.grade_id == grade_id,
    ))).scalars().all())
    membership_student_ids = select(StudentGradeMembership.student_id).where(
        StudentGradeMembership.tenant_id == tenant_id,
        StudentGradeMembership.grade_id == grade_id,
        StudentGradeMembership.academic_year == academic_year,
        StudentGradeMembership.status == "active",
    )
    student_query = select(Student.id).where(
        Student.tenant_id == tenant_id,
        or_(
            Student.grade_id == grade_id,
            Student.id.in_(membership_student_ids),
            Student.class_id.in_(class_ids) if class_ids else False,
        ),
    ).order_by(Student.id)
    return list((await session.execute(student_query)).scalars().all())


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
    student_ids = await _grade_student_ids(
        session, tenant_id, grade_id, academic_year,
    ) if grade_id else []
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
        "recommended_class_count": (count + 39) // 40,
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


@router.get("/my-students", summary="查询教师负责的学生")
async def my_students(
    include_teaching: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    """教师工作台专用学生列表，不开放组织学籍管理能力。"""
    class_ids = set((await session.execute(select(Class.id).where(
        Class.tenant_id == tenant_id,
        or_(Class.head_teacher_id == user.id, Class.deputy_head_teacher_id == user.id),
    ))).scalars().all())
    if include_teaching and user.role in {"teacher", "head_teacher", "subject_teacher"}:
        class_ids.update((await session.execute(select(TeachingAssignment.class_id).where(
            TeachingAssignment.tenant_id == tenant_id,
            TeachingAssignment.teacher_id == user.id,
            TeachingAssignment.class_id.is_not(None),
        ).distinct())).scalars().all())
    if not class_ids:
        return {"code": 0, "message": "ok", "data": []}
    students = list((await session.execute(select(Student).where(
        Student.tenant_id == tenant_id,
        Student.class_id.in_(class_ids),
    ).order_by(Student.class_id, Student.roster_order, Student.id))).scalars().all())
    classes = list((await session.execute(select(Class).where(Class.tenant_id == tenant_id, Class.id.in_(class_ids)))).scalars().all())
    class_names = {item.id: item.name for item in classes}
    return {"code": 0, "message": "ok", "data": [{
        **student.model_dump(),
        "class_name": class_names.get(student.class_id),
    } for student in students]}


@router.get("/choices", summary="查询学生选科审核列表")
async def choices_for_review(
    academic_year: str,
    term: str = "1",
    grade_id: int | None = None,
    status_filter: str | None = "confirmed",
    session: AsyncSession = Depends(get_session),
    user=Depends(require_choice_viewer),
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
    from app.services.org.staff_roles import get_staff_role_codes
    role_codes = set(await get_staff_role_codes(session, user.id))
    view_scope = resolve_choice_view_access(user.role, role_codes)
    if view_scope == "head_teacher":
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
    user=Depends(require_head_teacher),
    tenant_id: int = Depends(get_current_tenant),
):
    choice = await session.get(StudentSubjectChoice, choice_id)
    if choice is None or choice.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="选科记录不存在")
    if user.role in {"teacher", "head_teacher", "subject_teacher"}:
        student = await session.get(Student, choice.student_id)
        class_item = await session.get(Class, student.class_id) if student and student.class_id else None
        if class_item is None or user.id not in {class_item.head_teacher_id, class_item.deputy_head_teacher_id}:
            raise HTTPException(status_code=403, detail="只有该学生的班主任或副班主任可以审核")
    if choice.status == "locked" and body.action != "reopen":
        raise HTTPException(status_code=409, detail="选科已锁定，不能重复审核")
    if body.action == "reopen":
        choice.status = "confirmed"
        message = "已解除锁定，退回待审核"
    elif body.action == "approve":
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
    user=Depends(require_head_teacher),
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
    if user.role in {"teacher", "head_teacher", "subject_teacher"}:
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
    if any(periods < 1 or periods > 12 for periods in body.weekly_periods_by_subject.values()):
        raise HTTPException(status_code=422, detail="每个科目的每周课时须在 1 到 12 节之间")
    grade = await session.get(Grade, body.grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="年级不存在")
    phase = resolve_selection_phase(grade.level, body.term)
    if not phase.can_generate_teaching_classes:
        raise HTTPException(status_code=422, detail=f"当前处于{phase.label}阶段，尚不能生成教学班")
    student_ids = await _grade_student_ids(
        session, tenant_id, body.grade_id, body.academic_year,
    )
    if not student_ids:
        raise HTTPException(
            status_code=422,
            detail="该年级当前没有学生归属，无法生成教学班；请先确认学生档案中的年级信息",
        )
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

    # Serialize generation within a grade; previews perform no business writes.
    if not body.preview:
        await session.execute(select(Grade.id).where(
            Grade.id == grade.id, Grade.tenant_id == tenant_id,
        ).with_for_update())
    shared_rooms = await _shared_teaching_rooms(session, tenant_id, grade, body.academic_year, body.term)
    old_classes = list((await session.execute(select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id,
        TeachingClass.grade_id == body.grade_id,
        TeachingClass.academic_year == body.academic_year,
        TeachingClass.term == body.term,
    ))).scalars().all())
    old_ids = [item.id for item in old_classes]
    subject_names = {
        item.id: item.name for item in (await session.execute(select(Subject).where(
            Subject.tenant_id == tenant_id,
        ))).scalars().all()
    }
    saved_plans = list((await session.execute(select(TeachingSubjectHourPlan).where(
        TeachingSubjectHourPlan.tenant_id == tenant_id,
        TeachingSubjectHourPlan.grade_id == body.grade_id,
        TeachingSubjectHourPlan.academic_year == body.academic_year,
        TeachingSubjectHourPlan.term == body.term,
    ))).scalars().all())
    saved_hours = {str(item.subject_id): item.weekly_periods for item in saved_plans}
    plan_ids = {item.subject_id: item.id for item in saved_plans}
    plan_by_subject = {item.subject_id: item for item in saved_plans}
    effective_hours = {draft.subject_id: body.weekly_periods_by_subject.get(
        draft.subject_id, saved_hours.get(str(draft.subject_id), body.weekly_periods),
    ) for draft in drafts}
    token = hashlib.sha256(json.dumps({
        "scope": [tenant_id, grade.id, body.academic_year, body.term, body.capacity],
        "drafts": [[d.subject_id, d.sequence, d.student_ids] for d in drafts],
        "hours": effective_hours,
        "split_hours": [(p.subject_id, p.weekday_periods, p.weekend_periods) for p in saved_plans],
        "existing": sorted((c.id, c.weekly_periods, c.teacher_id, c.room, c.updated_at.isoformat()) for c in old_classes),
    }, sort_keys=True).encode()).hexdigest()
    warnings = []
    if not shared_rooms:
        warnings.append("本学期暂无可用共享教室；可以先组班，排课前再配置教室。")
    elif max((len(d.student_ids) for d in drafts), default=0) > max(r.capacity for r in shared_rooms):
        warnings.append("部分教学班人数超过共享教室容量，请调整班额或在排课前补充教室。")
    missing_hours = [subject_names.get(sid, str(sid)) for sid in effective_hours if str(sid) not in saved_hours and sid not in body.weekly_periods_by_subject]
    if missing_hours:
        warnings.append(f"{('、'.join(missing_hours))}未设置科目课时，本次使用每周 {body.weekly_periods} 节。")
    if body.preview:
        return {"code": 0, "message": "ok", "data": {
            "created": len(drafts), "memberships": 0,
            "existing_class_count": len(old_classes), "available_room_count": len(shared_rooms),
            "preview_token": token, "warnings": warnings,
            "classes": [{"subject_id": d.subject_id, "subject_name": subject_names.get(d.subject_id, str(d.subject_id)),
                         "sequence": d.sequence, "student_count": len(d.student_ids),
                         "weekly_periods": effective_hours[d.subject_id]} for d in drafts],
        }}
    if body.preview_token != token:
        raise HTTPException(status_code=409, detail="请先预览；若选科、课时或已有教学班已变化，请重新预览后确认。")
    if old_classes and not body.replace_existing:
        raise HTTPException(status_code=409, detail="已有教学班，请明确确认替换；替换将清除原班成员、教师教室安排和走班课表。")
    if old_ids:
        await session.execute(delete(TeachingClassSchedule).where(TeachingClassSchedule.tenant_id == tenant_id, TeachingClassSchedule.teaching_class_id.in_(old_ids)))
        await session.execute(delete(TeachingClassStudent).where(TeachingClassStudent.tenant_id == tenant_id, TeachingClassStudent.teaching_class_id.in_(old_ids)))
        await session.execute(delete(TeachingClass).where(TeachingClass.tenant_id == tenant_id, TeachingClass.id.in_(old_ids)))
    created_classes: list[TeachingClass] = []
    for draft in drafts:
        inherited = plan_by_subject.get(draft.subject_id)
        if inherited and effective_hours[draft.subject_id] != inherited.weekly_periods:
            inherited = None
        teaching_class = TeachingClass(
            tenant_id=tenant_id,
            grade_id=body.grade_id,
            subject_id=draft.subject_id,
            name=f"{grade.name}{subject_names.get(draft.subject_id, '选科')}走班{draft.sequence:02d}",
            academic_year=body.academic_year,
            term=body.term,
            sequence=draft.sequence,
            capacity=body.capacity,
            weekly_periods=body.weekly_periods_by_subject.get(
                draft.subject_id, saved_hours.get(str(draft.subject_id), body.weekly_periods),
            ),
            hour_plan_id=plan_ids.get(draft.subject_id),
            weekday_periods=inherited.weekday_periods if inherited else None,
            weekend_periods=inherited.weekend_periods if inherited else None,
            hours_overridden=(draft.subject_id in body.weekly_periods_by_subject
                              and body.weekly_periods_by_subject[draft.subject_id] != saved_hours.get(str(draft.subject_id))),
            teacher_id=None,
            room=None,
            status="generated",
        )
        session.add(teaching_class)
        created_classes.append(teaching_class)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "created": len(created_classes),
        "memberships": 0,
        "student_count": len(student_ids),
        "subject_count": len({item.subject_id for item in created_classes}),
    }}


@router.get("/teaching-classes/subject-hours", summary="读取走班科目课时方案")
async def get_teaching_subject_hours(
    grade_id: int, academic_year: str, term: str = Query(pattern=r"^[12]$"),
    detailed: bool = False,
    session: AsyncSession = Depends(get_session), user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    grade = await session.get(Grade, grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="年级不存在")
    return {"code": 0, "message": "ok", "data": await _walk_subject_hours(
        session, tenant_id, grade_id, academic_year, term, detailed,
    )}


@router.patch("/teaching-classes/subject-hours", summary="按科目调整走班课时")
async def update_teaching_subject_hours(
    body: UpdateTeachingSubjectHoursIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    grade = await session.get(Grade, body.grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="年级不存在")
    subject = await session.get(Subject, body.subject_id)
    if not subject or subject.tenant_id not in {None, tenant_id}:
        raise HTTPException(status_code=404, detail="科目不存在")
    classes = list((await session.execute(select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id,
        TeachingClass.grade_id == body.grade_id,
        TeachingClass.subject_id == body.subject_id,
        TeachingClass.academic_year == body.academic_year,
        TeachingClass.term == body.term,
    ))).scalars().all())
    plan = (await session.execute(select(TeachingSubjectHourPlan).where(
        TeachingSubjectHourPlan.tenant_id == tenant_id,
        TeachingSubjectHourPlan.grade_id == body.grade_id,
        TeachingSubjectHourPlan.academic_year == body.academic_year,
        TeachingSubjectHourPlan.term == body.term,
        TeachingSubjectHourPlan.subject_id == body.subject_id,
    ))).scalar_one_or_none()
    if plan:
        plan.weekly_periods = body.weekly_periods
    else:
        plan = TeachingSubjectHourPlan(tenant_id=tenant_id, grade_id=body.grade_id,
            academic_year=body.academic_year, term=body.term, subject_id=body.subject_id,
            weekly_periods=body.weekly_periods)
        session.add(plan)
    await session.flush()
    plan.weekday_periods = body.weekday_periods
    plan.weekend_periods = body.weekend_periods
    for item in classes:
        item.hour_plan_id = plan.id
        item.hours_overridden = False
    changed_classes = [item for item in classes if
        (item.weekly_periods, item.weekday_periods, item.weekend_periods) !=
        (body.weekly_periods, body.weekday_periods, body.weekend_periods)]
    cleared_schedule_count = 0
    if changed_classes:
        for item in changed_classes:
            item.weekly_periods = body.weekly_periods
            item.weekday_periods = body.weekday_periods
            item.weekend_periods = body.weekend_periods
        class_ids = [item.id for item in changed_classes]
        result = await session.execute(delete(TeachingClassSchedule).where(
            TeachingClassSchedule.tenant_id == tenant_id,
            TeachingClassSchedule.teaching_class_id.in_(class_ids),
        ))
        cleared_schedule_count = result.rowcount or 0
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "updated": len(changed_classes),
        "weekly_periods": body.weekly_periods,
        "cleared_schedule_count": cleared_schedule_count,
    }}


@router.patch("/teaching-classes/{class_id}/hours", summary="调整单个教学班课时")
async def update_teaching_class_hours(
    class_id: int, body: UpdateTeachingClassHoursIn,
    session: AsyncSession = Depends(get_session), user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    item = (await session.execute(select(TeachingClass).where(
        TeachingClass.id == class_id, TeachingClass.tenant_id == tenant_id,
        TeachingClass.grade_id == body.grade_id, TeachingClass.academic_year == body.academic_year,
        TeachingClass.term == body.term,
    ))).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="当前学期教学班不存在")
    cleared = 0
    if (item.weekly_periods, item.weekday_periods, item.weekend_periods) != (
        body.weekly_periods, body.weekday_periods, body.weekend_periods):
        item.weekly_periods = body.weekly_periods
        item.weekday_periods = body.weekday_periods
        item.weekend_periods = body.weekend_periods
        result = await session.execute(delete(TeachingClassSchedule).where(
            TeachingClassSchedule.tenant_id == tenant_id,
            TeachingClassSchedule.teaching_class_id == class_id,
        ))
        cleared = result.rowcount or 0
    item.hours_overridden = True
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"updated": 1, "cleared_schedule_count": cleared}}


@router.get("/space-pool", summary="读取选科走班共享教室池")
async def get_walk_class_space_pool(
    grade_id: int,
    academic_year: str,
    term: str = "1",
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    if term not in {"1", "2"}:
        raise HTTPException(status_code=422, detail="学期只能是 1 或 2")
    grade = await session.get(Grade, grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="年级不存在")
    value = await _walk_class_space_pool_value(session, tenant_id, grade_id, academic_year, term)
    rooms = await _shared_teaching_rooms(session, tenant_id, grade, academic_year, term)
    return {"code": 0, "message": "ok", "data": {
        "grade_id": grade_id,
        "academic_year": academic_year,
        "term": term,
        "physics_room_ids": value.get("physics_room_ids", []),
        "history_room_ids": value.get("history_room_ids", []),
        "shared_room_ids": value.get("shared_room_ids", []),
        "available_rooms": [{"id": room.id, "name": room.name, "capacity": room.capacity} for room in rooms],
    }}


@router.get("/teaching-classes", summary="查询选科走班已生成教学班")
async def list_walk_teaching_classes(
    grade_id: int,
    academic_year: str,
    term: str = "1",
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    grade = await session.get(Grade, grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="年级不存在")
    classes = list((await session.execute(select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id,
        TeachingClass.grade_id == grade_id,
        TeachingClass.academic_year == academic_year,
        TeachingClass.term == term,
    ).order_by(TeachingClass.subject_id, TeachingClass.sequence))).scalars().all())
    class_ids = [item.id for item in classes]
    teacher_names = {item.id: item.name for item in (await session.execute(
        select(User).where(User.tenant_id == tenant_id)
    )).scalars().all()}
    subjects = {item.id: item.name for item in (await session.execute(select(Subject))).scalars().all()}
    members_by_class: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if class_ids:
        member_rows = (await session.execute(
            select(TeachingClassStudent, Student, Class.name)
            .join(Student, Student.id == TeachingClassStudent.student_id)
            .outerjoin(Class, Class.id == Student.class_id)
            .where(
                TeachingClassStudent.teaching_class_id.in_(class_ids),
                Student.tenant_id == tenant_id,
            )
            .order_by(TeachingClassStudent.teaching_class_id, Student.student_no, Student.id)
        )).all()
        for membership, student, admin_class_name in member_rows:
            members_by_class[membership.teaching_class_id].append({
                "id": student.id,
                "student_no": student.student_no,
                "name": student.name,
                "administrative_class": admin_class_name,
            })
    return {"code": 0, "message": "ok", "data": [{
        "id": item.id,
        "name": item.name,
        "subject_id": item.subject_id,
        "subject_name": subjects.get(item.subject_id, "未知学科"),
        "sequence": item.sequence,
        "capacity": item.capacity,
        "weekly_periods": item.weekly_periods,
        "weekday_periods": item.weekday_periods,
        "weekend_periods": item.weekend_periods,
        "hours_overridden": item.hours_overridden,
        "teacher_id": item.teacher_id,
        "room": item.room,
        "student_count": len(members_by_class[item.id]),
        "teacher_name": teacher_names.get(item.teacher_id),
        "students": members_by_class[item.id],
    } for item in classes]}


@router.put("/space-pool", summary="保存选科走班共享教室池")
async def save_walk_class_space_pool(
    body: WalkClassSpacePoolIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    raise HTTPException(status_code=410, detail="旧教室池配置已停用，请在空间资源中维护本学期的同届复用分配规则。")


@router.post("/schedules/clear", dependencies=[Depends(require_management_user)], summary="清空指定年级学期走班课表")
async def clear_walk_schedule(
    body: ClearWalkScheduleIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: int = Depends(get_current_tenant),
):
    grade = (await session.execute(select(Grade).where(
        Grade.id == body.grade_id, Grade.tenant_id == tenant_id,
    ).with_for_update())).scalar_one_or_none()
    if grade is None:
        raise HTTPException(status_code=404, detail="年级不存在")
    teaching_class_ids = list((await session.execute(select(TeachingClass.id).where(
        TeachingClass.tenant_id == tenant_id,
        TeachingClass.grade_id == body.grade_id,
        TeachingClass.academic_year == body.academic_year,
        TeachingClass.term == body.term,
    ))).scalars().all())
    cleared = 0
    if teaching_class_ids:
        result = await session.execute(delete(TeachingClassSchedule).where(
            TeachingClassSchedule.tenant_id == tenant_id,
            TeachingClassSchedule.teaching_class_id.in_(teaching_class_ids),
        ))
        cleared = result.rowcount or 0
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "cleared": cleared, "teaching_class_count": len(teaching_class_ids),
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
        raise HTTPException(status_code=422, detail=f"当前处于{phase.label}阶段，暂不能生成走班课表")
    # One source of truth for preview and generation: grade-term base slots,
    # confirmed student rosters, assigned teachers, shared-room capacity and rules.
    preview = await recommend_walk_configuration(
        WalkRecommendationIn(
            grade_id=body.grade_id,
            academic_year=body.academic_year,
            term=body.term,
            room_ids=body.room_ids or None,
            forbidden_slots=body.forbidden_slots,
        ),
        session=session,
        tenant_id=tenant_id,
    )
    result = preview["data"]
    if result.get("status") != "feasible":
        detail = {
            "message": result.get("message", "没有找到满足当前条件的走班课表"),
            "status": result.get("status"),
            "diagnostics": result.get("diagnostics", []),
            "rule_failures": result.get("rule_failures", []),
            "warnings": result.get("warnings", []),
        }
        raise HTTPException(status_code=422, detail=detail)

    teaching_classes = list((await session.execute(select(TeachingClass).where(
        TeachingClass.tenant_id == tenant_id,
        TeachingClass.grade_id == body.grade_id,
        TeachingClass.academic_year == body.academic_year,
        TeachingClass.term == body.term,
    ).order_by(TeachingClass.subject_id, TeachingClass.sequence))).scalars().all())
    teaching_by_id = {int(item.id): item for item in teaching_classes}
    teaching_ids = list(teaching_by_id)
    rooms = await _shared_teaching_rooms(session, tenant_id, grade, body.academic_year, body.term)
    room_by_id = {int(room.id): room for room in rooms}
    roster_sizes = Counter((await session.execute(select(TeachingClassStudent.teaching_class_id).where(
        TeachingClassStudent.tenant_id == tenant_id,
        TeachingClassStudent.teaching_class_id.in_(teaching_ids),
    ))).scalars().all()) if teaching_ids else Counter()
    placements = result.get("placements", [])
    expected_periods = sum(int(item.weekly_periods) for item in teaching_classes)
    if len(placements) != expected_periods:
        raise HTTPException(status_code=422, detail="排课结果未覆盖全部教学班课时，原课表未修改")
    class_period_counts = Counter(int(item["teaching_class_id"]) for item in placements)
    for item_id, item in teaching_by_id.items():
        if item.weekday_periods is not None or item.weekend_periods is not None:
            work = sum(p['teaching_class_id'] == item_id and 1 <= int(p['weekday']) <= 5 for p in placements)
            weekend = sum(p['teaching_class_id'] == item_id and int(p['weekday']) in (6, 7) for p in placements)
            if (work, weekend) != (item.weekday_periods, item.weekend_periods):
                raise HTTPException(status_code=422, detail='工作日或周末课时不符，原课表未修改')
    if any(class_period_counts.get(item_id, 0) != int(item.weekly_periods)
           for item_id, item in teaching_by_id.items()):
        raise HTTPException(status_code=422, detail="部分教学班课时未排足，原课表未修改")
    records = []
    for placement in placements:
        class_id = int(placement["teaching_class_id"])
        room_id = int(placement["room_id"])
        teaching_class = teaching_by_id.get(class_id)
        room = room_by_id.get(room_id)
        if teaching_class is None or room is None or room.capacity < roster_sizes.get(class_id, 0):
            raise HTTPException(status_code=422, detail="排课结果中的教学班或教室已变化，原课表未修改")
        teaching_class.room = f"楼栋{room.building_id} · {room.name}"
        records.append(TeachingClassSchedule(
            tenant_id=tenant_id,
            teaching_class_id=class_id,
            teacher_id=teaching_class.teacher_id,
            subject_id=teaching_class.subject_id,
            academic_year=body.academic_year,
            term=body.term,
            weekday=int(placement["weekday"]),
            period=int(placement["period"]),
            room=teaching_class.room,
        ))
    await session.execute(delete(TeachingClassSchedule).where(
        TeachingClassSchedule.teaching_class_id.in_(teaching_ids),
    ))
    session.add_all(records)
    await session.commit()
    used_room_ids = sorted({int(item["room_id"]) for item in placements})
    return {"code": 0, "message": "ok", "data": {
        "created": len(records),
        "teaching_class_count": len(teaching_classes),
        "unplaced": [],
        "room_count": len(used_room_ids),
        "room_ids": used_room_ids,
        "slots": result.get("slots", []),
        "daily_slot_counts": result.get("daily_slot_counts", []),
        "placements": placements,
        "rule_results": result.get("rule_results", []),
        "warnings": result.get("warnings", []),
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


@router.get('/teaching-classes/{class_id}/roster', summary='教学班学生名单（按行政班分组）',
            dependencies=[Depends(require_management_user)])
async def teaching_class_roster(class_id: int, academic_year: str, term: str,
                                session: AsyncSession = Depends(get_session),
                                user=Depends(get_current_user),
                                tenant_id: int = Depends(get_current_tenant)):
    teaching_class = await session.get(TeachingClass, class_id)
    if not teaching_class or teaching_class.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail='教学班不存在')
    # 行政班归属按本学期分班关系（StudentClassMembership）取，未分班的学生 class_name 为 None
    member_rows = (await session.execute(
        select(Student, Class.name)
        .join(TeachingClassStudent, TeachingClassStudent.student_id == Student.id)
        .outerjoin(StudentClassMembership, and_(
            StudentClassMembership.student_id == Student.id,
            StudentClassMembership.tenant_id == tenant_id,
            StudentClassMembership.academic_year == academic_year,
            StudentClassMembership.term == term,
            StudentClassMembership.status == 'active',
        ))
        .outerjoin(Class, and_(
            Class.id == StudentClassMembership.class_id,
            Class.tenant_id == tenant_id,
            Class.academic_year == academic_year,
            Class.term == term,
        ))
        .where(
            TeachingClassStudent.teaching_class_id == class_id,
            TeachingClassStudent.tenant_id == tenant_id,
            Student.tenant_id == tenant_id,
        )
        .order_by(Class.name, Student.student_no, Student.id)
    )).all()
    items = [{
        "student_id": student.id,
        "student_no": student.student_no,
        "student_name": student.name,
        "class_name": admin_class_name,
    } for student, admin_class_name in member_rows]
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "teaching_class_id": class_id,
            "teaching_class_name": teaching_class.name,
            "subject_id": teaching_class.subject_id,
            "total": len(items),
            "items": items,
        },
    }


@router.get('/student-timetable/{student_id}', summary='查询学生完整课表',
            dependencies=[Depends(require_management_user)])
async def student_timetable(student_id: int, academic_year: str, term: str,
                            session: AsyncSession = Depends(get_session),
                            user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant)):
    from app.api.v1.scheduling import _load_rule_group, weekly_schedule
    from app.services.scheduling.rules import compile_rule_group, rules_for_schedule
    from app.services.scheduling.student_gaps import complete_student_timetable
    student = await session.get(Student, student_id)
    if not student or student.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail='学生不存在')
    current_class = (await _student_term_classes(session, tenant_id, [student_id], academic_year, term))[student_id]
    class_id = current_class.id
    admin = (await weekly_schedule(class_id, academic_year, term, session, user))['data']
    walk = (await list_schedules(academic_year, term, None, None, student_id, session, user, tenant_id))['data']
    entries = admin + [{**entry, 'id': -entry['id'], 'class_id': -entry['teaching_class_id'],
        'class_name': '走班 · ' + entry['teaching_class_name'], 'week_parity': 'all'} for entry in walk]
    group = await _load_rule_group(session, tenant_id, academic_year, term, grade_id=current_class.grade_id)
    study_periods = {}
    if group:
        group = rules_for_schedule(group, 'walk')
        ready_ids = {rule.rule_id for rule in compile_rule_group(group) if rule.status == 'ready'}
        for rule in group.rules:
            if rule.enabled and rule.id in ready_ids and rule.code == 'student_contiguous' and rule.params.get('fill_self_study'):
                for day in rule.weekdays or range(1, 8):
                    study_periods.setdefault(day, set()).update(rule.periods)
    if study_periods:
        teaching = list((await session.execute(select(TeachingClass).join(TeachingClassStudent,
            TeachingClassStudent.teaching_class_id == TeachingClass.id).where(
                TeachingClass.tenant_id == tenant_id, TeachingClassStudent.tenant_id == tenant_id,
                TeachingClassStudent.student_id == student_id,
                TeachingClass.academic_year == academic_year, TeachingClass.term == term))).scalars().all())
        counts = Counter(entry['teaching_class_id'] for entry in walk)
        if not admin or not teaching or any(counts[item.id] != item.weekly_periods for item in teaching):
            raise HTTPException(status_code=422, detail='公共课或走班课尚未排完整，暂不补自习')
    room = await session.get(Room, current_class.home_room_id) if current_class.home_room_id else None
    context = dict(class_id=class_id, class_name=current_class.name, academic_year=academic_year, term=term,
        room='自习地点待安排')
    try:
        entries = complete_student_timetable(entries, study_periods, context)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if study_periods and room and room.tenant_id == tenant_id:
        room_names = {room.name, f'楼栋{room.building_id} · {room.name}'}
        other_rows = list((await session.execute(select(Schedule).where(
            Schedule.tenant_id == tenant_id, Schedule.academic_year == academic_year,
            Schedule.term == term, Schedule.room.in_(room_names), Schedule.class_id != class_id))).scalars().all())
        other_rows += list((await session.execute(select(TeachingClassSchedule).where(
            TeachingClassSchedule.tenant_id == tenant_id, TeachingClassSchedule.academic_year == academic_year,
            TeachingClassSchedule.term == term, TeachingClassSchedule.room.in_(room_names)))).scalars().all())
        for entry in entries:
            if entry.get('is_self_study'):
                occupied = any(row.weekday == entry['weekday'] and row.period == entry['period']
                    and (row.week_parity == 'all' or entry['week_parity'] == 'all' or row.week_parity == entry['week_parity'])
                    for row in other_rows)
                if not occupied:
                    entry['room'] = f'楼栋{room.building_id} · {room.name}'
    return {'code': 0, 'message': 'ok', 'data': entries}
