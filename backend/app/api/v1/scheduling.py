"""排课系统 API：基础资源、任教关系、周课表和日期课表。"""
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.core.security import get_password_hash
from app.db.session import get_session
from app.models.enums import BaseUserRole, StudentStatus, UserStatus, WeekParity
from app.models.facility import Room
from app.models.gaokao import GaokaoScheme
from app.models.org import (
    Class, CourseHourPlan, Grade, OrganizationUnit, Schedule, StaffAppointment, Student, Subject,
    TeachingAssignment, Tenant, TenantConfig, User,
)
from app.services.gaokao import SubjectChoicePolicy, get_subject_choice_strategy
from app.services.scheduling import (
    ScheduleItem,
    ScheduleValidationIssue,
    build_evening_study_items,
    expand_schedule,
    generate_schedule,
    parity_conflicts,
    validate_schedule_requirements,
)
from app.services.scheduling_strategies import build_schedule_strategy, list_schedule_strategies
from app.services.staff_roles import replace_staff_roles
from app.services.auto_teaching import (
    TeacherScopeRule,
    apply_subject_periods,
    assignments_outside_rebuild_scope,
    build_auto_assignments,
    target_class_ids,
)
from app.services.cohort import expected_cohort_label, normalize_cohort_label

router = APIRouter(prefix="/scheduling", tags=["排课管理"])
SCHEDULING_GRID_CONFIG_KEY = "scheduling_grid_config"
SUBJECT_DISPLAY_ORDER = (
    "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理", "体育",
    "音乐", "美术", "心理", "校本", "班会", "生涯",
)


def _sort_subjects(subjects: list[Subject]) -> list[Subject]:
    order = {name: index for index, name in enumerate(SUBJECT_DISPLAY_ORDER)}
    return sorted(subjects, key=lambda item: (order.get(item.name, len(order)), item.name, item.id or 0))


def _sort_course_hour_plans(plans: list[CourseHourPlan], subjects: list[Subject]) -> list[CourseHourPlan]:
    subject_order = {item.id: index for index, item in enumerate(_sort_subjects(subjects))}
    parity_order = {WeekParity.all.value: 0, WeekParity.odd.value: 1, WeekParity.even.value: 2}
    return sorted(
        plans,
        key=lambda item: (
            item.class_id,
            subject_order.get(item.subject_id, len(subject_order)),
            item.subject_id,
            parity_order.get(str(item.week_parity), 3),
            item.id or 0,
        ),
    )


def _default_grid_config() -> dict:
    """Keep the historic Mon–Fri, seven-period grid when a school has no config."""
    return {
        "days": 5,
        "periods_per_day": 7,
        "daily_periods": [7, 7, 7, 7, 7, 0, 0],
        "enable_saturday": False,
        "enable_evening": False,
        "evening_start_period": None,
        "evening_daily_periods_odd": [0, 0, 0, 0, 0, 0, 0],
        "evening_daily_periods_even": [0, 0, 0, 0, 0, 0, 0],
        "evening_subject_ids": [],
        "evening_subject_ids_odd": [],
        "evening_subject_ids_even": [],
        "evening_subject_ids_odd_by_day": [None] * 7,
        "evening_subject_ids_even_by_day": [None] * 7,
        "term_start_monday": None,
        "first_week_parity": WeekParity.odd.value,
    }


def _assignment_room_name(
    explicit_room: str | None,
    class_id: int,
    class_room_names: dict[int, str],
) -> str | None:
    """任教关系未指定专用教室时，使用行政班绑定的固定教室。"""
    return explicit_room or class_room_names.get(class_id)


async def _class_room_names(
    session: AsyncSession,
    tenant_id: int,
    classes: list[Class],
) -> dict[int, str]:
    room_ids = {item.home_room_id for item in classes if item.home_room_id is not None}
    if not room_ids:
        return {}
    rooms = list((await session.execute(select(Room).where(
        Room.tenant_id == tenant_id,
        Room.id.in_(room_ids),
    ))).scalars().all())
    names_by_id = {item.id: item.name for item in rooms}
    return {
        item.id: names_by_id[item.home_room_id]
        for item in classes
        if item.home_room_id in names_by_id
    }


class TeacherIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=6, max_length=20)
    password: str = Field(min_length=6, max_length=64)


class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    course_type: Literal["subject", "activity"] = Field(default="subject", description="学科课或活动课")
    evening_study_allowed: bool = Field(default=False, description="是否允许安排为主课晚自习")


class CourseHourIn(BaseModel):
    id: int | None = Field(default=None, description="编辑已有课时方案时传入")
    class_id: int
    subject_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    weekly_periods: float = Field(default=4, ge=0.5, le=20, multiple_of=0.5)
    weekday_periods: float | None = Field(default=None, ge=0, le=20, multiple_of=0.5)
    saturday_periods: float = Field(default=0, ge=0, le=10, multiple_of=0.5)
    week_parity: WeekParity = WeekParity.all
    evening_periods_odd: int = Field(default=0, ge=0, le=1)
    evening_periods_even: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_week_parity(self):
        if self.weekday_periods is None:
            self.weekday_periods = self.weekly_periods
        self.weekly_periods = round(self.weekday_periods + self.saturday_periods, 2)
        has_half_period = any(
            value % 1 != 0 for value in (self.weekday_periods, self.saturday_periods)
        )
        if has_half_period and self.week_parity == WeekParity.all:
            raise ValueError("包含 0.5 节隔周课时，必须选择单周或双周")
        if not has_half_period and self.week_parity != WeekParity.all:
            raise ValueError("只有包含 0.5 节隔周课时的方案才能选择单周或双周")
        return self


class AssignmentIn(BaseModel):
    teacher_id: int | None = None
    subject_id: int | None = None
    class_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    weekly_periods: float = Field(default=4, ge=0.5, le=20, multiple_of=0.5)
    room: str | None = Field(default=None, max_length=50)


class TeacherScopeRuleIn(BaseModel):
    teacher_id: int
    class_id: int
    subject_id: int | None = Field(default=None, ge=1)
    mode: str = Field(pattern="^(allow|deny)$")
    weekly_periods: int | None = Field(default=None, ge=1, le=20)
    fixed_weekday: int | None = Field(default=None, ge=1, le=7)
    fixed_period: int | None = Field(default=None, ge=1, le=12)


class TeacherScopeRulesIn(BaseModel):
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    rules: list[TeacherScopeRuleIn] = Field(default_factory=list, max_length=500)


class AutoTeachingIn(BaseModel):
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    class_ids: list[int] | None = Field(default=None, description="生成范围：不传=全部班级，传=仅这些班级")
    subject_id: int | None = Field(default=None, ge=1)
    weekly_periods: int = Field(default=4, ge=1, le=20)
    max_weekly_periods: int = Field(default=30, ge=1, le=60)
    execute: bool = False
    subject_period_rules: list[dict[str, int]] = Field(default_factory=list, max_length=50)
    subject_teacher_limits: list[dict[str, int]] = Field(default_factory=list, max_length=50)
    # 时间结构（与排课规则一致，可选；不传则仅按每周课时/教师上限编排）
    days: int = Field(default=5, ge=1, le=7, description="每周教学日")
    periods_per_day: int = Field(default=7, ge=1, le=12, description="每个教学日节数")
    forbidden_slots: list[tuple[int, int]] = Field(default_factory=list, max_length=84, description="禁止排课时间段")
    max_class_lessons_per_day: int | None = Field(default=None, ge=1, le=12, description="班级每日最多课时")
    max_teacher_lessons_per_day: int | None = Field(default=None, ge=1, le=12, description="教师每日最多课时")
    max_same_subject_per_day: int | None = Field(default=None, ge=1, le=6, description="班级同科每日最多课时")


class GenerateIn(BaseModel):
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    class_ids: list[int] | None = None
    days: int | None = Field(default=None, ge=1, le=7)
    periods_per_day: int | None = Field(default=None, ge=1, le=12)
    forbidden_slots: list[tuple[int, int]] = Field(default_factory=list, max_length=84)
    max_class_lessons_per_day: int | None = Field(default=None, ge=1, le=12)
    max_teacher_lessons_per_day: int | None = Field(default=None, ge=1, le=12)
    max_class_lessons_on_saturday: int | None = Field(default=None, ge=1, le=12)
    max_teacher_lessons_on_saturday: int | None = Field(default=None, ge=1, le=12)
    max_pe_teacher_lessons_per_day: int | None = Field(default=None, ge=1, le=12)
    enable_evening: bool = False
    evening_start_period: int | None = Field(default=None, ge=1, le=12)
    evening_daily_periods_odd: list[int] = Field(default_factory=lambda: [0] * 7, min_length=7, max_length=7)
    evening_daily_periods_even: list[int] = Field(default_factory=lambda: [0] * 7, min_length=7, max_length=7)
    evening_subject_ids: list[int] = Field(default_factory=list, max_length=30)
    evening_subject_ids_odd: list[int] | None = Field(default=None, max_length=30)
    evening_subject_ids_even: list[int] | None = Field(default=None, max_length=30)
    evening_subject_ids_odd_by_day: list[int | None] = Field(default_factory=lambda: [None] * 7, min_length=7, max_length=7)
    evening_subject_ids_even_by_day: list[int | None] = Field(default_factory=lambda: [None] * 7, min_length=7, max_length=7)
    max_teacher_weekly_periods: int | None = Field(default=None, ge=1, le=60, description="教师每周最多课时")
    max_same_subject_per_day: int | None = Field(default=None, ge=1, le=6)
    require_full_week: bool = False
    avoid_consecutive_teacher_lessons: bool = True
    random_seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    strategy_codes: list[str] = Field(
        default_factory=lambda: [
            "cross_day_variety", "class_compact", "daily_balance",
            "cross_class_gap_repair", "random_tiebreak",
        ],
        min_length=1,
        max_length=6,
    )

    @field_validator("strategy_codes")
    @classmethod
    def validate_strategy_codes(cls, value: list[str]) -> list[str]:
        strategy = build_schedule_strategy(value)
        return strategy.codes

    @model_validator(mode="after")
    def validate_evening_periods(self):
        legacy_subject_ids = set(self.evening_subject_ids)
        self.evening_subject_ids_odd = sorted(set(
            self.evening_subject_ids_odd if self.evening_subject_ids_odd is not None else legacy_subject_ids
        ))
        self.evening_subject_ids_even = sorted(set(
            self.evening_subject_ids_even if self.evening_subject_ids_even is not None else legacy_subject_ids
        ))
        self.evening_subject_ids = sorted(set(self.evening_subject_ids_odd) | set(self.evening_subject_ids_even))
        profiles = (*self.evening_daily_periods_odd, *self.evening_daily_periods_even)
        if any(not 0 <= count <= 3 for count in profiles):
            raise ValueError("每天晚自习只能配置 0 或 1 节")
        if self.enable_evening and not any(profiles):
            raise ValueError("开启晚自习后必须配置单周或双周的晚自习节数")
        if any(profiles):
            self.enable_evening = True
        if self.evening_start_period is not None and self.periods_per_day is not None:
            if self.evening_start_period <= self.periods_per_day:
                raise ValueError("晚自习起始节次必须在正式课结束后")
            if self.evening_start_period + max(profiles, default=0) - 1 > 12:
                raise ValueError("晚自习结束节次不能超过第 12 节")
        return self


class SchedulingGridConfigIn(BaseModel):
    """School term scheduling grid; values are stored per academic-year/term."""
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    days: int = Field(default=5, ge=5, le=7)
    periods_per_day: int = Field(default=7, ge=1, le=12)
    daily_periods: list[int] = Field(default_factory=lambda: [7, 7, 7, 7, 7, 0, 0], min_length=7, max_length=7)
    enable_saturday: bool = False
    enable_evening: bool = False
    evening_start_period: int | None = Field(default=None, ge=1, le=12)
    evening_daily_periods_odd: list[int] = Field(default_factory=lambda: [0] * 7, min_length=7, max_length=7)
    evening_daily_periods_even: list[int] = Field(default_factory=lambda: [0] * 7, min_length=7, max_length=7)
    evening_subject_ids: list[int] = Field(default_factory=list, max_length=30)
    evening_subject_ids_odd: list[int] | None = Field(default=None, max_length=30)
    evening_subject_ids_even: list[int] | None = Field(default=None, max_length=30)
    evening_subject_ids_odd_by_day: list[int | None] = Field(default_factory=lambda: [None] * 7, min_length=7, max_length=7)
    evening_subject_ids_even_by_day: list[int | None] = Field(default_factory=lambda: [None] * 7, min_length=7, max_length=7)
    term_start_monday: date | None = None
    first_week_parity: WeekParity = WeekParity.odd

    @field_validator("daily_periods")
    @classmethod
    def validate_daily_periods(cls, value: list[int]) -> list[int]:
        if any(not 0 <= item <= 12 for item in value):
            raise ValueError("每天正式课节数必须在 0 到 12 节之间")
        if not any(value):
            raise ValueError("至少需要一个正式教学时段")
        return value

    @model_validator(mode="after")
    def validate_grid(self):
        legacy_subject_ids = set(self.evening_subject_ids)
        self.evening_subject_ids_odd = sorted(set(
            self.evening_subject_ids_odd if self.evening_subject_ids_odd is not None else legacy_subject_ids
        ))
        self.evening_subject_ids_even = sorted(set(
            self.evening_subject_ids_even if self.evening_subject_ids_even is not None else legacy_subject_ids
        ))
        self.evening_subject_ids = sorted(set(self.evening_subject_ids_odd) | set(self.evening_subject_ids_even))
        active_days = max(index + 1 for index, count in enumerate(self.daily_periods) if count)
        self.days = active_days
        self.periods_per_day = max(self.daily_periods)
        self.enable_saturday = self.daily_periods[5] > 0
        evening_profiles = (*self.evening_daily_periods_odd, *self.evening_daily_periods_even)
        if any(not 0 <= count <= 3 for count in evening_profiles):
            raise ValueError("每天晚自习只能配置 0 或 1 节")
        self.enable_evening = any(evening_profiles)
        if self.enable_evening and self.evening_start_period is None:
            self.evening_start_period = self.periods_per_day + 1
        if self.evening_start_period and self.evening_start_period <= self.periods_per_day:
            raise ValueError("晚自习起始节次必须在正式课结束后")
        if self.term_start_monday and self.term_start_monday.weekday() != 0:
            raise ValueError("学期开始日期必须为周一")
        if self.first_week_parity is WeekParity.all:
            raise ValueError("首周类型只能是单周或双周")
        return self


class ScheduleMoveIn(BaseModel):
    schedule_id: int
    target_weekday: int = Field(ge=1, le=7)
    target_period: int = Field(ge=1, le=12)
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    days: int | None = Field(default=None, ge=1, le=7)
    periods_per_day: int | None = Field(default=None, ge=1, le=12)


def _resource_maps(teachers: list[User], subjects: list[Subject], classes: list[Class]):
    return (
        {item.id: item.name for item in teachers},
        {item.id: item.name for item in subjects},
        {item.id: item.name for item in classes},
    )


def _schedule_out(item: Schedule, teacher_names: dict, subject_names: dict, class_names: dict):
    data = item.model_dump()
    data.update(
        teacher_name=teacher_names.get(item.teacher_id, "未指定"),
        subject_name=subject_names.get(item.subject_id, "未知学科"),
        class_name=class_names.get(item.class_id, "未知班级"),
    )
    return data


def schedule_item_dict(item: Schedule) -> dict:
    """Serialize a persisted schedule row for a parity-safe snapshot."""
    return {
        "class_id": item.class_id,
        "weekday": item.weekday,
        "period": item.period,
        "subject_id": item.subject_id,
        "teacher_id": item.teacher_id,
        "room": item.room,
        "week_parity": item.week_parity.value if isinstance(item.week_parity, WeekParity) else item.week_parity,
    }


def schedule_row_from_snapshot(item: dict, academic_year: str, term: str, tenant_id: int) -> Schedule:
    """Rebuild a row while accepting snapshots created before week parity existed."""
    return Schedule(
        class_id=int(item["class_id"]),
        weekday=int(item["weekday"]),
        period=int(item["period"]),
        subject_id=int(item["subject_id"]),
        teacher_id=item.get("teacher_id"),
        room=item.get("room"),
        week_parity=WeekParity(item.get("week_parity", WeekParity.all)),
        academic_year=academic_year,
        term=term,
        tenant_id=tenant_id,
    )


def schedule_item_from_row(item: Schedule) -> ScheduleItem:
    """Convert a persisted row to the shared scheduling service representation."""
    return ScheduleItem(
        assignment_id=item.id or 0,
        class_id=item.class_id,
        subject_id=item.subject_id,
        teacher_id=item.teacher_id,
        weekday=item.weekday,
        period=item.period,
        room=item.room,
        week_parity=WeekParity(item.week_parity),
    )


def _slot_has_conflict(
    rows: list[Schedule],
    *,
    weekday: int,
    period: int,
    parity: WeekParity | str,
    match,
    exclude_id: int | None = None,
) -> bool:
    return any(
        row.weekday == weekday
        and row.period == period
        and (exclude_id is None or row.id != exclude_id)
        and match(row)
        and parity_conflicts(row.week_parity, parity)
        for row in rows
    )


async def _generation_assignments(
    session: AsyncSession,
    body: GenerateIn,
    tenant_id: int,
) -> list[TeachingAssignment]:
    stmt = select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.academic_year == body.academic_year,
        TeachingAssignment.term == body.term,
    )
    if body.class_ids:
        stmt = stmt.where(TeachingAssignment.class_id.in_(body.class_ids))
    assignments = list((await session.execute(stmt)).scalars().all())
    # 排课生成使用课时管理中已经建立的完整关系；校本、生涯和班会等活动
    # 也必须进入课表，只是它们在校验时不会计入教师的学科负荷。
    return assignments


def _apply_course_hour_plans(
    assignments: list[TeachingAssignment],
    plans: list[CourseHourPlan],
) -> list[dict]:
    """Build generator inputs from course hours while retaining teacher relations.

    CourseHourPlan is the source of truth for lesson volume and parity. A teaching
    assignment still supplies the teacher and room. Legacy assignments without a
    matching plan remain usable during migration.
    """
    plans_by_scope: dict[tuple[int, int], list[CourseHourPlan]] = defaultdict(list)
    for plan in plans:
        plans_by_scope[(plan.class_id, plan.subject_id)].append(plan)

    payloads: list[dict] = []
    for assignment in assignments:
        base = assignment.model_dump()
        scoped_plans = sorted(
            plans_by_scope.get((assignment.class_id, assignment.subject_id), []),
            key=lambda item: item.week_parity.value if isinstance(item.week_parity, WeekParity) else str(item.week_parity),
        )
        if not scoped_plans:
            payloads.append(base)
            continue
        for plan in scoped_plans:
            payload = dict(base)
            payload["weekly_periods"] = plan.weekly_periods
            payload["weekday_periods"] = plan.weekday_periods
            payload["saturday_periods"] = plan.saturday_periods
            payload["evening_periods_odd"] = plan.evening_periods_odd
            payload["evening_periods_even"] = plan.evening_periods_even
            payload["week_parity"] = plan.week_parity.value if isinstance(plan.week_parity, WeekParity) else plan.week_parity
            payloads.append(payload)
    return payloads


async def _generation_assignment_payloads(
    session: AsyncSession,
    body: GenerateIn,
    tenant_id: int,
) -> list[dict]:
    assignments = await _generation_assignments(session, body, tenant_id)
    class_ids = body.class_ids or [item.class_id for item in assignments]
    plan_stmt = select(CourseHourPlan).where(
        CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.academic_year == body.academic_year,
        CourseHourPlan.term == body.term,
    )
    if class_ids:
        plan_stmt = plan_stmt.where(CourseHourPlan.class_id.in_(class_ids))
    plans = list((await session.execute(plan_stmt)).scalars().all())
    payloads = _apply_course_hour_plans(assignments, plans)
    subject_ids = {int(item["subject_id"]) for item in payloads}
    subject_types = dict((await session.execute(select(Subject.id, Subject.course_type).where(
        Subject.tenant_id == tenant_id,
        Subject.id.in_(subject_ids) if subject_ids else False,
    ))).all())
    for payload in payloads:
        payload["counts_toward_teacher_load"] = subject_types.get(int(payload["subject_id"]), "subject") == "subject"
    return payloads


async def _evening_subject_plan_maps(
    session: AsyncSession,
    tenant_id: int,
    body: GenerateIn,
    class_ids: list[int],
) -> tuple[dict[int, set[int]], dict[int, set[int]]]:
    """Read per-class evening subject pools from course-hour plans."""
    stmt = select(CourseHourPlan).where(
        CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.academic_year == body.academic_year,
        CourseHourPlan.term == body.term,
        CourseHourPlan.class_id.in_(class_ids) if class_ids else False,
    )
    plans = list((await session.execute(stmt)).scalars().all())
    odd: dict[int, set[int]] = defaultdict(set)
    even: dict[int, set[int]] = defaultdict(set)
    for plan in plans:
        if plan.evening_periods_odd > 0:
            odd[plan.class_id].add(plan.subject_id)
        if plan.evening_periods_even > 0:
            even[plan.class_id].add(plan.subject_id)
    return dict(odd), dict(even)


async def _ensure_evening_activity_subject(
    session: AsyncSession,
    tenant_id: int,
) -> int:
    """Return the tenant-owned activity used for standalone self-study slots."""
    subject = (await session.execute(select(Subject).where(
        Subject.tenant_id == tenant_id,
        Subject.name == "自主学习",
    ))).scalars().first()
    if subject is None:
        subject = Subject(
            tenant_id=tenant_id,
            name="自主学习",
            course_type="activity",
            evening_study_allowed=False,
        )
        session.add(subject)
        await session.flush()
    return int(subject.id)


async def _teaching_track_subject_ids(
    session: AsyncSession,
    tenant_id: int,
) -> frozenset[int]:
    """Resolve course ownership through the registered gaokao strategy."""
    school = await session.get(Tenant, tenant_id)
    if school is None:
        return frozenset()
    scheme = (await session.execute(select(GaokaoScheme).where(
        GaokaoScheme.tenant_id == tenant_id,
        GaokaoScheme.is_active == True,  # noqa: E712
    ).order_by(GaokaoScheme.entry_year.desc()))).scalars().first()
    if scheme is None:
        return frozenset()
    config = scheme.strategy_config or {}
    policy = SubjectChoicePolicy(
        primary_subject_ids=set(scheme.primary_subject_ids),
        secondary_subject_ids=set(scheme.secondary_subject_ids),
        elective_subject_ids=set(config.get("elective_subject_ids", scheme.secondary_subject_ids)),
        elective_count=int(config.get("elective_count", 3)),
        primary_delivery_mode=str(config.get("primary_delivery_mode", "administrative")),
    )
    return get_subject_choice_strategy(
        scheme.mode or school.gaokao_mode,
    ).teaching_class_subject_pool(policy)


async def _administrative_primary_subject_ids(
    session: AsyncSession,
    tenant_id: int,
) -> frozenset[int]:
    scheme = (await session.execute(select(GaokaoScheme).where(
        GaokaoScheme.tenant_id == tenant_id,
        GaokaoScheme.is_active == True,  # noqa: E712
    ).order_by(GaokaoScheme.entry_year.desc()))).scalars().first()
    if scheme is None:
        return frozenset()
    config = scheme.strategy_config or {}
    if str(config.get("primary_delivery_mode", "administrative")) != "administrative":
        return frozenset()
    return frozenset(int(item) for item in scheme.primary_subject_ids)


def _validate_generation(
    assignments: list[dict],
    body: GenerateIn,
    administrative_primary_subject_ids: frozenset[int] = frozenset(),
):
    result = validate_schedule_requirements(
        assignments,
        days=body.days,
        periods_per_day=body.periods_per_day,
        forbidden_slots={tuple(slot) for slot in body.forbidden_slots},
        max_class_lessons_per_day=body.max_class_lessons_per_day,
        max_teacher_lessons_per_day=body.max_teacher_lessons_per_day,
        max_class_lessons_on_saturday=body.max_class_lessons_on_saturday,
        max_teacher_lessons_on_saturday=body.max_teacher_lessons_on_saturday,
        max_same_subject_per_day=body.max_same_subject_per_day,
        require_full_week=body.require_full_week,
        max_teacher_weekly_periods=body.max_teacher_weekly_periods,
    )
    primary_by_class: dict[int, set[int]] = {}
    for item in assignments:
        if item["subject_id"] in administrative_primary_subject_ids:
            primary_by_class.setdefault(item["class_id"], set()).add(item["subject_id"])
    primary_issues = tuple(
        ScheduleValidationIssue(
            code="primary_admin_track_conflict",
            message="同一行政班配置了多个互斥首选科目",
            entity_type="class",
            entity_id=class_id,
            related_id=None,
            requested=len(subject_ids),
            capacity=1,
            rule_code="primary_admin_single_track",
            formula=f"行政班首选科目数 {len(subject_ids)} > 1",
        )
        for class_id, subject_ids in primary_by_class.items()
        if len(subject_ids) > 1
    )
    if not primary_issues:
        return result
    return replace(result, valid=False, issues=[*result.issues, *primary_issues])


@router.get("/resources", summary="排课基础资源")
async def resources(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    teachers = list((await session.execute(select(User).where(
        User.tenant_id == tenant_id,
        User.status == UserStatus.active,
        User.role == BaseUserRole.teacher,
    ).order_by(User.name))).scalars().all())
    subjects = list((await session.execute(select(Subject).where(
        Subject.tenant_id == tenant_id,
    ).order_by(Subject.id))).scalars().all())
    subjects = _sort_subjects(subjects)
    classes = list((await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
    ).order_by(Class.grade_id, Class.id))).scalars().all())
    assignments = list((await session.execute(select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id,
    ).order_by(TeachingAssignment.class_id, TeachingAssignment.id))).scalars().all())
    teaching_subject_ids = await _teaching_track_subject_ids(session, tenant_id)
    # 资源页展示完整的关系，包括校本/生涯/班会等活动安排；教学轨道只影响自动生成入口。
    teacher_names, subject_names, class_names = _resource_maps(teachers, subjects, classes)
    subject_group_units = list((await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type == "subject_group",
        OrganizationUnit.status == "active",
        OrganizationUnit.subject_id.is_not(None),
    ))).scalars().all())
    subject_group_subjects = {
        unit.id: unit.subject_id
        for unit in subject_group_units
        if unit.subject_id is not None
    }
    teacher_subject_ids: dict[str, list[int]] = defaultdict(list)
    if subject_group_subjects:
        appointments = list((await session.execute(select(StaffAppointment).where(
            StaffAppointment.tenant_id == tenant_id,
            StaffAppointment.organization_unit_id.in_(subject_group_subjects),
            StaffAppointment.status == "active",
            StaffAppointment.position_code == "member",
        ))).scalars().all())
        for appointment in appointments:
            subject_id = subject_group_subjects.get(appointment.organization_unit_id)
            if subject_id is not None and subject_id not in teacher_subject_ids.setdefault(str(appointment.staff_id), []):
                teacher_subject_ids[str(appointment.staff_id)].append(subject_id)
        for subject_ids in teacher_subject_ids.values():
            subject_ids.sort()
    class_room_names = await _class_room_names(session, tenant_id, classes)
    assignment_data = []
    for item in assignments:
        data = item.model_dump()
        data.update(
            teacher_name=teacher_names.get(item.teacher_id) if item.teacher_id is not None else "活动安排",
            subject_name=subject_names.get(item.subject_id, "未知学科"),
            class_name=class_names.get(item.class_id, "未知班级"),
            room=_assignment_room_name(item.room, item.class_id, class_room_names),
        )
        assignment_data.append(data)
    return {"code": 0, "message": "ok", "data": {
        "teachers": [item.model_dump(exclude={"password_hash"}) for item in teachers],
        "subjects": [item.model_dump() for item in subjects],
        "classes": [item.model_dump() for item in classes],
        "assignments": assignment_data,
        "teaching_track_subject_ids": sorted(teaching_subject_ids),
        "teacher_subject_ids": teacher_subject_ids,
    }}


@router.post("/teachers", status_code=status.HTTP_201_CREATED, summary="新增教师")
async def create_teacher(
    body: TeacherIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    exists = (await session.execute(select(User).where(
        User.tenant_id == tenant_id, User.phone == body.phone,
    ))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="该手机号已存在")
    teacher = User(
        name=body.name,
        phone=body.phone,
        password_hash=get_password_hash(body.password),
        role=BaseUserRole.teacher,
        tenant_id=tenant_id,
    )
    session.add(teacher)
    await session.flush()
    await replace_staff_roles(session, teacher.id, ["subject_teacher"], tenant_id)
    await session.commit()
    await session.refresh(teacher)
    return {"code": 0, "message": "ok", "data": teacher.model_dump(exclude={"password_hash"})}


@router.get("/subjects", summary="学科列表")
async def list_subjects(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    subjects = list((await session.execute(select(Subject).where(
        Subject.tenant_id == tenant_id,
    ).order_by(Subject.id))).scalars().all())
    subjects = _sort_subjects(subjects)
    return {"code": 0, "message": "ok", "data": [item.model_dump() for item in subjects]}


@router.post("/subjects", status_code=status.HTTP_201_CREATED, summary="新增学科")
async def create_subject(
    body: SubjectIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    exists = (await session.execute(select(Subject).where(
        Subject.name == body.name,
        Subject.tenant_id == tenant_id,
    ))).scalars().first()
    if exists:
        return {"code": 0, "message": "ok", "data": exists.model_dump()}
    subject = Subject(
        tenant_id=tenant_id,
        name=body.name,
        course_type=body.course_type,
        evening_study_allowed=body.evening_study_allowed,
    )
    session.add(subject)
    await session.commit()
    await session.refresh(subject)
    return {"code": 0, "message": "ok", "data": subject.model_dump()}


@router.put("/subjects/{subject_id}", summary="更新学科晚自习资格")
async def update_subject(
    subject_id: int,
    body: SubjectIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    subject = await session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="学科不存在")
    if subject.tenant_id is None:
        raise HTTPException(status_code=403, detail="系统公共科目不可直接修改")
    if subject.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="学科不存在")
    duplicate = (await session.execute(select(Subject).where(
        Subject.tenant_id == tenant_id, Subject.name == body.name, Subject.id != subject_id,
    ))).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="学科名称已存在")
    subject.name = body.name
    subject.course_type = body.course_type
    subject.evening_study_allowed = body.evening_study_allowed
    await session.commit()
    await session.refresh(subject)
    return {"code": 0, "message": "ok", "data": subject.model_dump()}


def _course_hour_output(
    item: CourseHourPlan,
    class_names: dict[int, str],
    subject_names: dict[int, str],
) -> dict:
    data = item.model_dump()
    data.update(
        class_name=class_names.get(item.class_id, "未知班级"),
        subject_name=subject_names.get(item.subject_id, "未知学科"),
    )
    return data


@router.get("/course-hours", summary="查询班级课时方案")
async def list_course_hours(
    academic_year: str,
    term: str = "1",
    class_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    stmt = select(CourseHourPlan).where(
        CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.academic_year == academic_year,
        CourseHourPlan.term == term,
    ).order_by(CourseHourPlan.class_id, CourseHourPlan.subject_id, CourseHourPlan.week_parity)
    if class_id is not None:
        stmt = stmt.where(CourseHourPlan.class_id == class_id)
    items = list((await session.execute(stmt)).scalars().all())
    class_ids = {item.class_id for item in items}
    subject_ids = {item.subject_id for item in items}
    classes = list((await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.id.in_(class_ids) if class_ids else False,
    ))).scalars().all())
    subjects = list((await session.execute(select(Subject).where(
        Subject.tenant_id == tenant_id,
        Subject.id.in_(subject_ids) if subject_ids else False,
    ))).scalars().all())
    items = _sort_course_hour_plans(items, subjects)
    return {"code": 0, "message": "ok", "data": [
        _course_hour_output(item, {row.id: row.name for row in classes}, {row.id: row.name for row in subjects})
        for item in items
    ]}


@router.post("/course-hours", summary="保存班级课时方案")
async def upsert_course_hour(
    body: CourseHourIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    class_item = await session.get(Class, body.class_id)
    subject = await session.get(Subject, body.subject_id)
    if (
        class_item is None
        or class_item.tenant_id != tenant_id
        or subject is None
        or subject.tenant_id != tenant_id
    ):
        raise HTTPException(status_code=422, detail="班级或学科不存在")

    same_scope = select(CourseHourPlan).where(
        CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.class_id == body.class_id,
        CourseHourPlan.subject_id == body.subject_id,
        CourseHourPlan.academic_year == body.academic_year,
        CourseHourPlan.term == body.term,
    )
    siblings = list((await session.execute(same_scope)).scalars().all())
    editing_item = None
    if body.id is not None:
        editing_item = await session.get(CourseHourPlan, body.id)
        if editing_item is None or editing_item.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="课时方案不存在")
        siblings = [row for row in siblings if row.id != body.id]
    has_all = any(item.week_parity == WeekParity.all for item in siblings)
    has_alternate = any(item.week_parity != WeekParity.all for item in siblings)
    if (body.week_parity == WeekParity.all and has_alternate) or (body.week_parity != WeekParity.all and has_all):
        raise HTTPException(status_code=409, detail="同一班级同一科目不能同时配置每周和单双周课时")

    item = editing_item or next((row for row in siblings if row.week_parity == body.week_parity), None)
    if item is None:
        item = CourseHourPlan(tenant_id=tenant_id, **body.model_dump(exclude={"id"}))
        session.add(item)
    else:
        for field in (
            "weekday_periods", "saturday_periods", "weekly_periods",
            "evening_periods_odd", "evening_periods_even",
        ):
            setattr(item, field, getattr(body, field))
    await session.commit()
    await session.refresh(item)
    return {"code": 0, "message": "ok", "data": _course_hour_output(item, {class_item.id: class_item.name}, {subject.id: subject.name})}


@router.delete("/course-hours/{course_hour_id}", summary="删除班级课时方案")
async def delete_course_hour(
    course_hour_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    item = (await session.execute(select(CourseHourPlan).where(
        CourseHourPlan.id == course_hour_id,
        CourseHourPlan.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="课时方案不存在")
    await session.delete(item)
    await session.commit()
    return {"code": 0, "message": "ok", "data": None}


@router.post("/assignments", summary="新增或更新任教关系")
async def upsert_assignment(
    body: AssignmentIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    teacher = await session.get(User, body.teacher_id)
    subject = await session.get(Subject, body.subject_id) if body.subject_id is not None else None
    class_item = await session.get(Class, body.class_id)
    if not class_item or class_item.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="教师、学科或班级不存在")
    if teacher is not None and teacher.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="教师、学科或班级不存在")
    if subject is not None and subject.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="教师、学科或班级不存在")
    if subject is None and teacher is not None:
        subject_group_units = list((await session.execute(select(OrganizationUnit).where(
            OrganizationUnit.tenant_id == tenant_id,
            OrganizationUnit.unit_type == "subject_group",
            OrganizationUnit.status == "active",
            OrganizationUnit.subject_id.is_not(None),
        ))).scalars().all())
        unit_ids = [unit.id for unit in subject_group_units if unit.id is not None]
        subject_by_unit = {unit.id: unit.subject_id for unit in subject_group_units}
        appointments = list((await session.execute(select(StaffAppointment).where(
            StaffAppointment.tenant_id == tenant_id,
            StaffAppointment.staff_id == body.teacher_id,
            StaffAppointment.organization_unit_id.in_(unit_ids),
            StaffAppointment.status == "active",
            StaffAppointment.position_code == "member",
        ))).scalars().all()) if unit_ids else []
        subject_ids = sorted({subject_by_unit[item.organization_unit_id] for item in appointments if subject_by_unit.get(item.organization_unit_id) is not None})
        if len(subject_ids) != 1:
            detail = "该教师尚未关联学科组，无法自动确定学科" if not subject_ids else "该教师关联了多个学科组，请先明确组织关系"
            raise HTTPException(status_code=422, detail=detail)
        subject = await session.get(Subject, subject_ids[0])
    if subject is None:
        raise HTTPException(status_code=422, detail="普通学科课需要先选择教师；活动课需要选择活动类型")
    if subject.course_type == "subject" and teacher is None:
        raise HTTPException(status_code=422, detail="普通学科课必须选择教师")
    if subject.course_type == "activity" and subject.name == "班会":
        if class_item.head_teacher_id is None:
            raise HTTPException(status_code=422, detail="该班尚未设置班主任，无法生成班会安排")
        if body.teacher_id is not None and body.teacher_id != class_item.head_teacher_id:
            raise HTTPException(status_code=422, detail="班会必须由本班班主任负责")
        teacher = await session.get(User, class_item.head_teacher_id)
    if subject.course_type == "activity" and teacher is not None and teacher.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="活动负责人不存在")
    class_room_names = await _class_room_names(session, tenant_id, [class_item])
    values = body.model_dump()
    values["teacher_id"] = teacher.id if teacher is not None else None
    values["subject_id"] = subject.id
    values["room"] = _assignment_room_name(body.room, body.class_id, class_room_names)
    stmt = select(TeachingAssignment).where(
        TeachingAssignment.class_id == body.class_id,
        TeachingAssignment.subject_id == subject.id,
        TeachingAssignment.academic_year == body.academic_year,
        TeachingAssignment.term == body.term,
    )
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item:
        for key, value in values.items():
            setattr(item, key, value)
    else:
        item = TeachingAssignment(**values, tenant_id=tenant_id)
        session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"code": 0, "message": "ok", "data": item.model_dump()}


@router.delete("/assignments/{assignment_id}", summary="删除任教关系")
async def delete_assignment(
    assignment_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    stmt = select(TeachingAssignment).where(
        TeachingAssignment.id == assignment_id,
        TeachingAssignment.tenant_id == tenant_id,
    )
    item = (await session.execute(stmt)).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="任教关系不存在")
    await session.delete(item)
    await session.commit()
    return {"code": 0, "message": "ok", "data": None}


async def _load_scope_rules(session: AsyncSession, tenant_id: int, academic_year: str, term: str) -> list[dict]:
    item = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "scheduling_teacher_scope_rules",
    ))).scalars().first()
    if not item or not isinstance(item.config_value, dict):
        return []
    return [rule for rule in item.config_value.get(f"{academic_year}:{term}", []) if isinstance(rule, dict)]


@router.get("/teacher-scope-rules", summary="查询教师搭班规则")
async def teacher_scope_rules(
    academic_year: str,
    term: str = "1",
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    rules = await _load_scope_rules(session, tenant_id, academic_year, term)
    teacher_ids = {int(item["teacher_id"]) for item in rules if item.get("teacher_id") is not None}
    class_ids = {int(item["class_id"]) for item in rules if item.get("class_id") is not None}
    teachers = dict((await session.execute(select(User.id, User.name).where(User.id.in_(teacher_ids)))).all()) if teacher_ids else {}
    classes = dict((await session.execute(select(Class.id, Class.name).where(Class.id.in_(class_ids)))).all()) if class_ids else {}
    return {"code": 0, "message": "ok", "data": [
        {**item, "teacher_name": teachers.get(int(item["teacher_id"])), "class_name": classes.get(int(item["class_id"]))}
        for item in rules
    ]}


@router.put("/teacher-scope-rules", summary="保存教师搭班规则")
async def save_teacher_scope_rules(
    body: TeacherScopeRulesIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    teacher_ids = {item.teacher_id for item in body.rules}
    class_ids = {item.class_id for item in body.rules}
    valid_teachers = set((await session.execute(select(User.id).where(User.id.in_(teacher_ids), User.tenant_id == tenant_id))).scalars()) if teacher_ids else set()
    valid_classes = set((await session.execute(select(Class.id).where(Class.id.in_(class_ids), Class.tenant_id == tenant_id))).scalars()) if class_ids else set()
    if teacher_ids - valid_teachers or class_ids - valid_classes:
        raise HTTPException(status_code=422, detail="教师搭班规则中存在无效教师或班级")
    item = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "scheduling_teacher_scope_rules",
    ))).scalars().first()
    config = dict(item.config_value) if item and isinstance(item.config_value, dict) else {}
    config[f"{body.academic_year}:{body.term}"] = [rule.model_dump() for rule in body.rules]
    if item is None:
        item = TenantConfig(tenant_id=tenant_id, config_key="scheduling_teacher_scope_rules", config_value=config, updated_by=user.id)
        session.add(item)
    else:
        item.config_value = config
        item.updated_by = user.id
    await session.commit()
    return {"code": 0, "message": "ok", "data": config[f"{body.academic_year}:{body.term}"]}


@router.post("/auto-teaching", summary="预览或执行自动任教关系")
async def auto_teaching(
    body: AutoTeachingIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    assignments = list((await session.execute(select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.academic_year == body.academic_year,
        TeachingAssignment.term == body.term,
    ))).scalars().all())
    teaching_track_subject_ids = await _teaching_track_subject_ids(session, tenant_id)
    assignments = [item for item in assignments if item.subject_id not in teaching_track_subject_ids]
    grades_by_id = {item.id: item for item in (await session.execute(
        select(Grade).where(Grade.tenant_id == tenant_id),
    )).scalars().all()}

    def _expected_cohort(grade_id: int) -> str | None:
        grade = grades_by_id.get(grade_id)
        if grade is None:
            return None
        return expected_cohort_label(body.academic_year, grade.level)

    all_classes = list((await session.execute(select(Class).where(Class.tenant_id == tenant_id).order_by(Class.grade_id, Class.id))).scalars().all())
    # 届过滤：只排「本学年该年级应属届」的班级。
    # 模板生成是按届快照执行的，不能用“同学年”替代届别，否则会把
    # 同一学年下的高二/高三组织或历史班级混入当前高一范围。
    all_classes = [
        item for item in all_classes
        if item.cohort_label is not None and item.cohort_label == _expected_cohort(item.grade_id)
    ]
    class_room_names = await _class_room_names(session, tenant_id, all_classes)
    head_teacher_ids = {int(item.head_teacher_id) for item in all_classes if item.head_teacher_id is not None}
    if body.class_ids:
        scoped_class_ids = [class_id for class_id in body.class_ids if class_id in {item.id for item in all_classes}]
    else:
        # 未指定范围时覆盖全部班级：自动生成任教关系面向整个年级/全校，而不是只补已有数据班级的缺
        scoped_class_ids = [item.id for item in all_classes]
    # 学生情况：按班级统计实际在册学生数，无实际数据时回退班级计划人数
    student_rows = (await session.execute(
        select(Student.class_id, func.count(Student.id)).where(
            Student.tenant_id == tenant_id,
            Student.class_id.in_(scoped_class_ids),
            Student.status == StudentStatus.studying,
        ).group_by(Student.class_id)
    )).all()
    class_student_counts = {int(row[0]): int(row[1]) for row in student_rows}
    for item in all_classes:
        if item.id not in class_student_counts and item.planned_student_count is not None:
            class_student_counts[item.id] = int(item.planned_student_count)
    raw_rules = await _load_scope_rules(session, tenant_id, body.academic_year, body.term)
    rules = [TeacherScopeRule(
        teacher_id=int(item["teacher_id"]), class_id=int(item["class_id"]),
        subject_id=int(item["subject_id"]) if item.get("subject_id") else None,
        mode=str(item["mode"]),
        weekly_periods=int(item["weekly_periods"]) if item.get("weekly_periods") else None,
        fixed_weekday=int(item["fixed_weekday"]) if item.get("fixed_weekday") else None,
        fixed_period=int(item["fixed_period"]) if item.get("fixed_period") else None,
    ) for item in raw_rules]
    # 内建业务规则（不作为配置暴露）：班主任默认任教自己班、教本学科。
    # 为每个设了班主任的班级自动生成一条固定任教规则；用户显式配置的同(教师,班级)规则优先。
    explicit_rule_pairs = {(rule.teacher_id, rule.class_id) for rule in rules}
    rules.extend(
        TeacherScopeRule(teacher_id=item.head_teacher_id, class_id=item.id, subject_id=None, mode="allow")
        for item in all_classes
        if item.head_teacher_id is not None and (item.head_teacher_id, item.id) not in explicit_rule_pairs
    )
    subject_periods = {
        int(item["subject_id"]): int(item["weekly_periods"])
        for item in body.subject_period_rules
        if item.get("subject_id") is not None and item.get("weekly_periods") is not None
    }
    subject_teacher_limits = {
        int(item["subject_id"]): int(item["max_weekly_periods"])
        for item in body.subject_teacher_limits
        if item.get("subject_id") is not None and item.get("max_weekly_periods") is not None
    }
    selected_subject_ids = list(subject_periods) or ([body.subject_id] if body.subject_id is not None else None)
    # 教研组成员资格 → 教师学科资质：只使用同租户的显式 subject_id 关联，绝不按名称猜测。
    tenant_subject_ids = set((await session.execute(select(Subject.id).where(
        Subject.tenant_id == tenant_id,
    ))).scalars().all())
    group_units = list((await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type == "subject_group",
        OrganizationUnit.status == "active",
    ))).scalars().all())
    unit_to_subject = {
        unit.id: unit.subject_id
        for unit in group_units
        if unit.subject_id in tenant_subject_ids
    }
    teacher_subject_fallback: dict[int, set[int]] = defaultdict(set)
    if unit_to_subject:
        appts = list((await session.execute(select(StaffAppointment).where(
            StaffAppointment.tenant_id == tenant_id,
            StaffAppointment.organization_unit_id.in_(unit_to_subject),
            StaffAppointment.status == "active",
        ))).scalars().all())
        for appt in appts:
            subject_id = unit_to_subject[appt.organization_unit_id]
            if subject_id not in teaching_track_subject_ids:
                teacher_subject_fallback[appt.staff_id].add(subject_id)
    # 只有已任命到当前班级所属年级部的教师，才允许生成该年级的任教关系。
    # 学科教研组只代表“具备学科资质”，不代表本学年已被调入年级部。
    grade_units = list((await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type == "grade_group",
        OrganizationUnit.status == "active",
    ))).scalars().all())
    grade_unit_levels = {
        unit.id: next((level for level, label in ((1, "高一"), (2, "高二"), (3, "高三")) if label in unit.name), None)
        for unit in grade_units
    }
    scoped_levels = {
        grades_by_id[item.grade_id].level
        for item in all_classes
        if item.id in scoped_class_ids and item.grade_id in grades_by_id
    }
    expected_cohorts = {
        _expected_cohort(item.grade_id)
        for item in all_classes
        if item.id in scoped_class_ids and _expected_cohort(item.grade_id) is not None
    }
    scoped_grade_ids = {
        item.grade_id for item in all_classes
        if item.id in scoped_class_ids
    }
    target_grade_unit_ids = {
        unit.id for unit in grade_units
        if unit.grade_id in scoped_grade_ids
        and normalize_cohort_label(unit.cohort_label) in expected_cohorts
        and unit.academic_year == body.academic_year
    }
    active_grade_teacher_ids = set((await session.execute(select(StaffAppointment.staff_id).where(
        StaffAppointment.tenant_id == tenant_id,
        StaffAppointment.organization_unit_id.in_(target_grade_unit_ids) if target_grade_unit_ids else False,
        StaffAppointment.academic_year == body.academic_year,
        StaffAppointment.status == "active",
    ))).scalars().all())
    assignment_rows = [item.model_dump() for item in assignments]
    # 模板/多学科重新编排必须重算当前范围，不能把旧任教关系当成“已完成”直接跳过。
    # 范围之外的关系仍保留，用于计算教师在其他范围已经承担的负荷。
    planning_source = assignments_outside_rebuild_scope(
        assignment_rows,
        scoped_class_ids,
        selected_subject_ids or [],
    ) if selected_subject_ids else assignment_rows
    # 班主任任教本班是硬约束，不是排序偏好：在重算范围内，先移除
    # 其任教科目上由其他教师占用的本班关系，交给固定规则重新落位。
    # 否则 build_auto_assignments 会把已有关系视为“已满足”，导致班主任
    # 明明已经指定本班，却仍保留其他教师。
    head_teacher_pairs = {
        (int(item.id), int(item.head_teacher_id))
        for item in all_classes
        if item.id in scoped_class_ids and item.head_teacher_id is not None
    }
    if head_teacher_pairs and selected_subject_ids:
        head_ids = {teacher_id for _, teacher_id in head_teacher_pairs}
        head_subjects = {
            (teacher_id, subject_id)
            for teacher_id, subject_ids in (teacher_subject_fallback or {}).items()
            for subject_id in subject_ids
            if subject_id in selected_subject_ids and teacher_id in head_ids
        }
        planning_source = [
            item for item in planning_source
            if not (
                (int(item["class_id"]), int(item["teacher_id"])) not in head_teacher_pairs
                and (next(
                    (teacher_id for class_id, teacher_id in head_teacher_pairs if class_id == int(item["class_id"])),
                    None,
                ), int(item["subject_id"])) in head_subjects
            )
        ]
    planning_assignments = apply_subject_periods(planning_source, subject_periods)
    created, skipped = build_auto_assignments(
        planning_assignments, scoped_class_ids, rules,
        weekly_periods=body.weekly_periods, max_weekly_periods=body.max_weekly_periods,
        subject_ids=selected_subject_ids,
        subject_weekly_periods=subject_periods,
        subject_max_weekly_periods=subject_teacher_limits,
        student_counts=class_student_counts,
        days=body.days,
        periods_per_day=body.periods_per_day,
        max_same_subject_per_day=body.max_same_subject_per_day,
        max_teacher_lessons_per_day=body.max_teacher_lessons_per_day,
        max_class_lessons_per_day=body.max_class_lessons_per_day,
        forbidden_slots=body.forbidden_slots,
        teacher_subject_fallback=teacher_subject_fallback or None,
        eligible_teacher_ids=active_grade_teacher_ids,
    )
    for data in created:
        data["room"] = _assignment_room_name(data.get("room"), int(data["class_id"]), class_room_names)
    updated_count = 0
    if body.execute and skipped:
        raise HTTPException(status_code=422, detail="任教关系校验未通过，请先处理未匹配关系")
    if body.execute:
        # 幂等覆盖：同一 (班级, 学科, 学年, 学期) 已存在 → 更新教师/课时；不存在 → 新增。
        # 重复执行多次结果收敛为同一份数据，不会产生重复关系。
        for data in created:
            existing = (await session.execute(select(TeachingAssignment).where(
                TeachingAssignment.tenant_id == tenant_id,
                TeachingAssignment.class_id == data["class_id"],
                TeachingAssignment.subject_id == data["subject_id"],
                TeachingAssignment.academic_year == body.academic_year,
                TeachingAssignment.term == body.term,
            ))).scalars().first()
            if existing:
                if (
                    existing.teacher_id != data["teacher_id"]
                    or existing.weekly_periods != data["weekly_periods"]
                    or existing.room != data.get("room")
                ):
                    existing.teacher_id = data["teacher_id"]
                    existing.weekly_periods = data["weekly_periods"]
                    existing.room = data.get("room")
                    updated_count += 1
                continue
            session.add(TeachingAssignment(**data, academic_year=body.academic_year, term=body.term, tenant_id=tenant_id))
        # 已有任教关系的课时按学科规则同步（未在编排范围内但配置了学科课时的）
        for item in assignments:
            configured_periods = subject_periods.get(int(item.subject_id))
            if configured_periods is not None and item.weekly_periods != configured_periods:
                item.weekly_periods = configured_periods
                updated_count += 1
        await session.commit()
    workload = {}
    for item in planning_assignments:
        workload[int(item["teacher_id"])] = workload.get(int(item["teacher_id"]), 0) + int(item.get("weekly_periods") or body.weekly_periods)
    for item in created:
        workload[int(item["teacher_id"])] = workload.get(int(item["teacher_id"]), 0) + int(item["weekly_periods"])
    teacher_ids = list(workload)
    teacher_names = dict((await session.execute(select(User.id, User.name).where(
        User.tenant_id == tenant_id, User.id.in_(teacher_ids),
    ))).all()) if teacher_ids else {}
    workload_summary = [{
        "teacher_id": teacher_id,
        "teacher_name": teacher_names.get(teacher_id),
        "weekly_periods": periods,
        "max_weekly_periods": subject_teacher_limits.get(next(iter({int(item.subject_id) for item in assignments if int(item.teacher_id) == teacher_id}), 0), body.max_weekly_periods),
        "sufficient": periods <= body.max_weekly_periods,
    } for teacher_id, periods in sorted(workload.items(), key=lambda item: (-item[1], item[0]))]
    # 名称映射：让前端直接渲染「一排排列表」而不必再查资源
    teacher_names = dict((await session.execute(
        select(User.id, User.name).where(User.id.in_({int(item["teacher_id"]) for item in created} | {int(item["teacher_id"]) for item in workload_summary}))
    )).all()) if (created or workload_summary) else {}
    subject_names = dict((await session.execute(
        select(Subject.id, Subject.name).where(Subject.id.in_({int(item["subject_id"]) for item in created} | {int(item["subject_id"]) for item in skipped}))
    )).all()) if (created or skipped) else {}
    class_names = dict((await session.execute(
        select(Class.id, Class.name).where(Class.id.in_({int(item["class_id"]) for item in created} | {int(item["class_id"]) for item in skipped}))
    )).all()) if (created or skipped) else {}
    plan = [
        {
            **item,
            "teacher_name": teacher_names.get(int(item["teacher_id"]), "未知教师"),
            "subject_name": subject_names.get(int(item["subject_id"]), "未知学科"),
            "class_name": class_names.get(int(item["class_id"]), "未知班级"),
            "status": "success",
        }
        for item in created
    ] + [
        {
            **item,
            "subject_name": subject_names.get(int(item["subject_id"]), "未知学科"),
            "class_name": class_names.get(int(item["class_id"]), "未知班级"),
            "teacher_name": "",
            "student_count": class_student_counts.get(int(item["class_id"])),
            "status": "skipped",
        }
        for item in skipped
    ]
    time_structure = {
        "days": body.days,
        "periods_per_day": body.periods_per_day,
        "forbidden_slots": [list(slot) for slot in body.forbidden_slots],
        "max_class_lessons_per_day": body.max_class_lessons_per_day,
        "max_teacher_lessons_per_day": body.max_teacher_lessons_per_day,
        "max_same_subject_per_day": body.max_same_subject_per_day,
        "weekly_lesson_cap": body.days * body.periods_per_day,
        "same_subject_weekly_cap": body.max_same_subject_per_day * body.days if body.max_same_subject_per_day else None,
        "teacher_weekly_cap": body.max_teacher_lessons_per_day * body.days if body.max_teacher_lessons_per_day else None,
    }
    return {"code": 0, "message": "ok", "data": {
        "created": created, "skipped": skipped, "executed": body.execute,
        "created_count": len(created), "skipped_count": len(skipped), "updated_count": updated_count,
        "workload_summary": workload_summary,
        "plan": plan,
        "time_structure": time_structure,
    }}


@router.post("/generate", summary="生成周课表")
async def create_schedule(
    body: GenerateIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    grid = await _load_grid_config(session, tenant_id, body.academic_year, body.term)
    body = body.model_copy(update={
        "days": body.days if body.days is not None else grid["days"],
        "periods_per_day": body.periods_per_day if body.periods_per_day is not None else grid["periods_per_day"],
        "evening_start_period": body.evening_start_period or (
            body.periods_per_day if body.periods_per_day is not None else grid["periods_per_day"]
        ) + 1,
        "forbidden_slots": sorted({*body.forbidden_slots, *_grid_forbidden_slots(grid)}),
    })
    assignments = await _generation_assignment_payloads(session, body, tenant_id)
    if not assignments:
        raise HTTPException(status_code=422, detail="请先配置当前学年学期的任教关系")
    validation = _validate_generation(
        assignments,
        body,
        await _administrative_primary_subject_ids(session, tenant_id),
    )
    if not validation.valid:
        raise HTTPException(status_code=422, detail="排课条件无解，请先根据校验结果调整条件")
    pe_subject = (await session.execute(select(Subject).where(Subject.name == "体育"))).scalars().first()
    teacher_daily_limits = (
        {
            int(item["teacher_id"]): body.max_pe_teacher_lessons_per_day
            for item in assignments
            if pe_subject is not None
            and item["subject_id"] == pe_subject.id
            and item.get("teacher_id") is not None
        }
        if body.max_pe_teacher_lessons_per_day is not None
        else None
    )
    result = generate_schedule(
        assignments,
        days=body.days,
        periods_per_day=body.periods_per_day,
        forbidden_slots={tuple(slot) for slot in body.forbidden_slots},
        max_class_lessons_per_day=body.max_class_lessons_per_day,
        max_teacher_lessons_per_day=body.max_teacher_lessons_per_day,
        max_class_lessons_on_saturday=body.max_class_lessons_on_saturday,
        max_teacher_lessons_on_saturday=body.max_teacher_lessons_on_saturday,
        max_same_subject_per_day=body.max_same_subject_per_day,
        avoid_consecutive_teacher_lessons=body.avoid_consecutive_teacher_lessons,
        teacher_daily_limits=teacher_daily_limits,
        strategy_codes=body.strategy_codes,
        random_seed=body.random_seed,
        max_teacher_weekly_periods=body.max_teacher_weekly_periods,
    )
    class_ids = sorted({item["class_id"] for item in assignments})
    if any(body.evening_daily_periods_odd) or any(body.evening_daily_periods_even):
        evening_subject_id = await _ensure_evening_activity_subject(session, tenant_id)
        evening_items = build_evening_study_items(
            assignments,
            class_ids=class_ids,
            first_evening_period=body.evening_start_period or body.periods_per_day + 1,
            evening_daily_periods_odd=body.evening_daily_periods_odd,
            evening_daily_periods_even=body.evening_daily_periods_even,
            activity_subject_id=evening_subject_id,
        )
        result = replace(result, items=[*result.items, *evening_items])
    previous_rows = (await session.execute(select(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year,
        Schedule.term == body.term,
        Schedule.class_id.in_(class_ids),
    ))).scalars().all()
    snapshot = {
        "version_id": int(datetime.utcnow().timestamp() * 1000),
        "saved_at": datetime.utcnow().isoformat(),
        "academic_year": body.academic_year,
        "term": body.term,
        "class_ids": class_ids,
        "class_count": len(class_ids),
        "lesson_count": len(previous_rows),
        "items": [schedule_item_dict(row) for row in previous_rows],
    }
    # 1) 兼容旧接口：保存最近一次快照用于 rollback
    snapshot_config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "scheduling_last_snapshot",
    ))).scalars().first()
    if snapshot_config is None:
        snapshot_config = TenantConfig(tenant_id=tenant_id, config_key="scheduling_last_snapshot", config_value=snapshot)
        session.add(snapshot_config)
    else:
        snapshot_config.config_value = snapshot
        snapshot_config.updated_at = datetime.utcnow()
    # 2) 版本历史：最多保留 20 版，按时间倒序排列（最新在最前）
    MAX_VERSIONS = 20
    history_config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "scheduling_version_history",
    ))).scalars().first()
    history_list = []
    if history_config and isinstance(history_config.config_value, list):
        history_list = [v for v in history_config.config_value if isinstance(v, dict)]
    # 仅当有可恢复内容时才入历史
    if previous_rows:
        history_item = {k: v for k, v in snapshot.items() if k != "items"}
        history_item["items"] = snapshot["items"]
        existing_numbers = [
            int(item["version_number"])
            for item in history_list
            if isinstance(item.get("version_number"), int)
        ]
        history_item["version_number"] = max(existing_numbers, default=0) + 1
        history_list.insert(0, history_item)
        if len(history_list) > MAX_VERSIONS:
            history_list = history_list[:MAX_VERSIONS]
    if history_config is None:
        history_config = TenantConfig(tenant_id=tenant_id, config_key="scheduling_version_history", config_value=history_list)
        session.add(history_config)
    else:
        history_config.config_value = history_list
        history_config.updated_at = datetime.utcnow()
    await session.execute(delete(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year,
        Schedule.term == body.term,
        Schedule.class_id.in_(class_ids),
    ))
    records = [Schedule(
        class_id=item.class_id,
        weekday=item.weekday,
        period=item.period,
        subject_id=item.subject_id,
        teacher_id=item.teacher_id,
        room=item.room,
        week_parity=item.week_parity,
        academic_year=body.academic_year,
        term=body.term,
        tenant_id=tenant_id,
    ) for item in result.items]
    session.add_all(records)
    await session.commit()
    staffing_issues = result.staffing_issues
    if staffing_issues:
        issue_class_ids = {
            issue[key]
            for issue in staffing_issues
            for key in ("class_id", "blocking_class_id")
        }
        issue_subject_ids = {issue["subject_id"] for issue in staffing_issues}
        issue_teacher_ids = {issue["teacher_id"] for issue in staffing_issues}
        class_names = dict((await session.execute(
            select(Class.id, Class.name).where(Class.id.in_(issue_class_ids))
        )).all())
        subject_names = dict((await session.execute(
            select(Subject.id, Subject.name).where(Subject.id.in_(issue_subject_ids))
        )).all())
        teacher_names = dict((await session.execute(
            select(User.id, User.name).where(User.id.in_(issue_teacher_ids))
        )).all())
        staffing_issues = [{
            **issue,
            "class_name": class_names.get(issue["class_id"]),
            "blocking_class_name": class_names.get(issue["blocking_class_id"]),
            "subject_name": subject_names.get(issue["subject_id"]),
            "teacher_name": teacher_names.get(issue["teacher_id"]),
        } for issue in staffing_issues]
    return {"code": 0, "message": "ok", "data": {
        "created": len(records),
        "unplaced": result.unplaced,
        "class_count": len(class_ids),
        "strategy_codes": body.strategy_codes,
        "staffing_issues": staffing_issues,
        "validation": {
            "assignment_count": validation.assignment_count,
            "requested_lessons": validation.requested_lessons,
            "available_slots": validation.available_slots,
        },
        "can_rollback": bool(previous_rows),
    }}


@router.post("/rollback", summary="恢复上一次课表")
async def rollback_schedule(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "scheduling_last_snapshot",
    ))).scalars().first()
    snapshot = config.config_value if config and isinstance(config.config_value, dict) else None
    if not snapshot or not snapshot.get("items"):
        raise HTTPException(status_code=404, detail="没有可恢复的上一版课表")
    academic_year = str(snapshot.get("academic_year", ""))
    term = str(snapshot.get("term", "1"))
    class_ids = [int(value) for value in snapshot.get("class_ids", [])]
    if not academic_year or not class_ids:
        raise HTTPException(status_code=422, detail="上一版课表快照不完整")
    await session.execute(delete(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == academic_year,
        Schedule.term == term,
        Schedule.class_id.in_(class_ids),
    ))
    session.add_all([
        schedule_row_from_snapshot(item, academic_year, term, tenant_id)
        for item in snapshot["items"]
    ])
    config.config_value = None
    config.updated_at = datetime.utcnow()
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"restored": len(snapshot["items"]), "academic_year": academic_year, "term": term}}


@router.get("/versions", summary="查询课表历史版本列表")
async def list_schedule_versions(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    history_config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "scheduling_version_history",
    ))).scalars().first()
    history_list = []
    if history_config and isinstance(history_config.config_value, list):
        history_list = [v for v in history_config.config_value if isinstance(v, dict)]
    # 返回摘要（不含 items），节省带宽
    summary = []
    for idx, item in enumerate(history_list):
        summary.append({
            "version_id": item.get("version_id"),
            "saved_at": item.get("saved_at"),
            "academic_year": item.get("academic_year"),
            "term": item.get("term"),
            "class_count": item.get("class_count", len(item.get("class_ids", []))),
            "lesson_count": item.get("lesson_count", len(item.get("items", []))),
            "label": f"版本 {item.get('version_number', idx + 1)} · {item.get('saved_at', '')[:19].replace('T', ' ')}",
        })
    return {"code": 0, "message": "ok", "data": summary}


@router.post("/versions/{version_id}/restore", summary="恢复指定历史版本")
async def restore_schedule_version(
    version_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    history_config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "scheduling_version_history",
    ))).scalars().first()
    history_list = []
    if history_config and isinstance(history_config.config_value, list):
        history_list = [v for v in history_config.config_value if isinstance(v, dict)]
    target = next((v for v in history_list if v.get("version_id") == version_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="指定版本不存在或已过期")
    academic_year = str(target.get("academic_year", ""))
    term = str(target.get("term", "1"))
    class_ids = [int(value) for value in target.get("class_ids", [])]
    items = target.get("items", [])
    if not academic_year or not class_ids:
        raise HTTPException(status_code=422, detail="版本快照不完整")
    # 先保存当前状态为 last_snapshot，便于再次回滚
    current_rows = (await session.execute(select(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == academic_year,
        Schedule.term == term,
        Schedule.class_id.in_(class_ids),
    ))).scalars().all()
    current_snapshot = {
        "version_id": int(datetime.utcnow().timestamp() * 1000),
        "saved_at": datetime.utcnow().isoformat(),
        "academic_year": academic_year,
        "term": term,
        "class_ids": class_ids,
        "items": [schedule_item_dict(row) for row in current_rows],
    }
    snapshot_config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "scheduling_last_snapshot",
    ))).scalars().first()
    if snapshot_config is None:
        snapshot_config = TenantConfig(tenant_id=tenant_id, config_key="scheduling_last_snapshot", config_value=current_snapshot)
        session.add(snapshot_config)
    else:
        snapshot_config.config_value = current_snapshot
        snapshot_config.updated_at = datetime.utcnow()
    # 执行恢复
    await session.execute(delete(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == academic_year,
        Schedule.term == term,
        Schedule.class_id.in_(class_ids),
    ))
    session.add_all([
        schedule_row_from_snapshot(item, academic_year, term, tenant_id)
        for item in items
    ])
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "restored": len(items),
        "academic_year": academic_year,
        "term": term,
        "version_id": version_id,
    }}


@router.get("/strategies", summary="查询可用排课策略")
async def scheduling_strategies(user=Depends(get_current_user)):
    return {
        "code": 0,
        "message": "ok",
        "data": [asdict(option) for option in list_schedule_strategies()],
    }


@router.post("/validate", summary="排课前资源校验")
async def validate_schedule(
    body: GenerateIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    assignments = await _generation_assignment_payloads(session, body, tenant_id)
    if not assignments:
        raise HTTPException(status_code=422, detail="请先配置当前学年学期的任教关系")
    result = _validate_generation(
        assignments,
        body,
        await _administrative_primary_subject_ids(session, tenant_id),
    )
    suggestions = []
    seen_suggestions: set[tuple[str, int]] = set()
    for issue in result.issues:
        for suggestion in issue.suggestions:
            key = (suggestion.field, suggestion.recommended_value)
            if key not in seen_suggestions:
                seen_suggestions.add(key)
                suggestions.append(asdict(suggestion))
    return {"code": 0, "message": "ok", "data": {
        "valid": result.valid,
        "issues": [asdict(issue) for issue in result.issues],
        "rules": [asdict(rule) for rule in result.rules],
        "suggestions": suggestions,
        "assignment_count": result.assignment_count,
        "requested_lessons": result.requested_lessons,
        "available_slots": result.available_slots,
    }}


async def _load_weekly(session: AsyncSession, class_id: int, academic_year: str, term: str):
    items = list((await session.execute(select(Schedule).where(
        Schedule.class_id == class_id,
        Schedule.academic_year == academic_year,
        Schedule.term == term,
    ).order_by(Schedule.weekday, Schedule.period))).scalars().all())
    teachers = list((await session.execute(select(User))).scalars().all())
    subjects = list((await session.execute(select(Subject))).scalars().all())
    classes = list((await session.execute(select(Class).where(Class.id == class_id))).scalars().all())
    maps = _resource_maps(teachers, subjects, classes)
    return items, maps


async def _load_grid_config(
    session: AsyncSession,
    tenant_id: int,
    academic_year: str,
    term: str,
) -> dict:
    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == SCHEDULING_GRID_CONFIG_KEY,
    ))).scalars().first()
    saved = row.config_value if row and isinstance(row.config_value, dict) else {}
    stored_scope = saved.get(f"{academic_year}:{term}", {})
    stored_scope = stored_scope if isinstance(stored_scope, dict) else {}
    value = {**_default_grid_config(), **stored_scope}
    if not isinstance(value.get("daily_periods"), list) or len(value["daily_periods"]) != 7:
        value["daily_periods"] = [value["periods_per_day"]] * value["days"] + [0] * (7 - value["days"])
    for field in ("evening_daily_periods_odd", "evening_daily_periods_even"):
        if not isinstance(value.get(field), list) or len(value[field]) != 7:
            value[field] = [0] * 7
    for field in ("evening_subject_ids_odd_by_day", "evening_subject_ids_even_by_day"):
        if not isinstance(value.get(field), list) or len(value[field]) != 7:
            value[field] = [None] * 7
    legacy_evening_subject_ids = stored_scope.get("evening_subject_ids", [])
    if not isinstance(legacy_evening_subject_ids, list):
        legacy_evening_subject_ids = []
    for field in ("evening_subject_ids_odd", "evening_subject_ids_even"):
        if field not in stored_scope or not isinstance(value.get(field), list):
            value[field] = list(legacy_evening_subject_ids)
    value["evening_subject_ids"] = sorted(set(value["evening_subject_ids_odd"]) | set(value["evening_subject_ids_even"]))
    value["days"] = max(index + 1 for index, count in enumerate(value["daily_periods"]) if count)
    value["periods_per_day"] = max(value["daily_periods"])
    value["enable_saturday"] = value["daily_periods"][5] > 0
    value["enable_evening"] = any(value["evening_daily_periods_odd"]) or any(value["evening_daily_periods_even"])
    if value["enable_evening"] and not value.get("evening_start_period"):
        value["evening_start_period"] = value["periods_per_day"] + 1
    if not value["enable_evening"]:
        value["evening_start_period"] = None
    if isinstance(value.get("term_start_monday"), str):
        value["term_start_monday"] = date.fromisoformat(value["term_start_monday"])
    return value


def _grid_forbidden_slots(config: dict) -> set[tuple[int, int]]:
    """Turn per-day configured capacities into ordinary scheduling forbidden slots."""
    return {
        (weekday, period)
        for weekday, available_periods in enumerate(config["daily_periods"], start=1)
        for period in range(available_periods + 1, config["periods_per_day"] + 1)
    }


def _evening_subject_ids_for_parity(config: dict, parity: WeekParity | str) -> set[int]:
    """Return the evening-study subjects allowed for the item's week leg."""
    parity_value = parity.value if isinstance(parity, WeekParity) else parity
    field = "evening_subject_ids_odd" if parity_value == WeekParity.odd.value else "evening_subject_ids_even"
    selected = config.get(field)
    if isinstance(selected, list):
        return set(selected)
    legacy = config.get("evening_subject_ids", [])
    return set(legacy) if isinstance(legacy, list) else set()


@router.get("/grid-config", summary="查询排课周格配置")
async def grid_config(
    academic_year: str,
    term: str = "1",
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    return {"code": 0, "message": "ok", "data": await _load_grid_config(session, tenant_id, academic_year, term)}


@router.put("/grid-config", summary="保存排课周格配置")
async def save_grid_config(
    body: SchedulingGridConfigIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == SCHEDULING_GRID_CONFIG_KEY,
    ))).scalars().first()
    config = dict(row.config_value) if row and isinstance(row.config_value, dict) else {}
    value = body.model_dump(mode="json")
    value.pop("academic_year", None)
    value.pop("term", None)
    config[f"{body.academic_year}:{body.term}"] = value
    if row is None:
        session.add(TenantConfig(
            tenant_id=tenant_id,
            config_key=SCHEDULING_GRID_CONFIG_KEY,
            config_value=config,
            updated_by=user.id,
        ))
    else:
        row.config_value = config
        row.updated_by = user.id
        row.updated_at = datetime.utcnow()
    await session.commit()
    return {"code": 0, "message": "ok", "data": value}


@router.get("/weekly", summary="查询班级周课表")
async def weekly_schedule(
    class_id: int,
    academic_year: str,
    term: str = "1",
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    items, maps = await _load_weekly(session, class_id, academic_year, term)
    return {"code": 0, "message": "ok", "data": [_schedule_out(item, *maps) for item in items]}


@router.get("/calendar", summary="生成具体日期课表")
async def calendar_schedule(
    class_id: int,
    academic_year: str,
    week_start: date,
    term: str = "1",
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    items, maps = await _load_weekly(session, class_id, academic_year, term)
    grid = await _load_grid_config(session, tenant_id, academic_year, term)
    try:
        dated = expand_schedule(
            [schedule_item_from_row(item) for item in items],
            week_start,
            term_start_monday=grid["term_start_monday"],
            first_week_parity=grid["first_week_parity"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    output = []
    rows_by_id = {item.id: item for item in items}
    for dated_item in dated:
        source = rows_by_id[dated_item.assignment_id]
        data = _schedule_out(source, *maps)
        data["lesson_date"] = dated_item.lesson_date.isoformat()
        output.append(data)
    return {"code": 0, "message": "ok", "data": output}


@router.get("/adjustments/options", summary="查询课表可调时段")
async def schedule_adjustment_options(
    schedule_id: int,
    academic_year: str,
    term: str = "1",
    days: int | None = None,
    periods_per_day: int | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    grid = await _load_grid_config(session, tenant_id, academic_year, term)
    days = days if days is not None else grid["days"]
    periods_per_day = periods_per_day if periods_per_day is not None else grid["periods_per_day"]
    source = (await session.execute(select(Schedule).where(
        Schedule.id == schedule_id,
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == academic_year,
        Schedule.term == term,
    ))).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="课表记录不存在")
    subject = await session.get(Subject, source.subject_id)
    teaching_relation = (await session.execute(select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.teacher_id == source.teacher_id,
        TeachingAssignment.subject_id == source.subject_id,
        TeachingAssignment.class_id == source.class_id,
        TeachingAssignment.academic_year == academic_year,
        TeachingAssignment.term == term,
    ))).scalar_one_or_none()
    rows = list((await session.execute(select(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == academic_year,
        Schedule.term == term,
    ))).scalars().all())
    source_index = (source.weekday - 1) * periods_per_day + source.period
    options = []
    for weekday in range(1, days + 1):
        for period in range(1, periods_per_day + 1):
            if (weekday - 1) * periods_per_day + period <= source_index:
                continue
            reasons = []
            if grid.get("enable_evening") and grid.get("evening_start_period") and period >= grid["evening_start_period"] and source.subject_id not in _evening_subject_ids_for_parity(grid, source.week_parity):
                reasons.append("该学科未获准安排主课晚自习")
            if teaching_relation is None:
                reasons.append("教师未配置该班该学科的任教关系")
            if _slot_has_conflict(rows, weekday=weekday, period=period, parity=source.week_parity,
                                  match=lambda row: row.class_id == source.class_id, exclude_id=source.id):
                reasons.append("该班已有课程")
            if source.teacher_id is not None and _slot_has_conflict(
                rows, weekday=weekday, period=period, parity=source.week_parity,
                match=lambda row: row.teacher_id == source.teacher_id, exclude_id=source.id,
            ):
                reasons.append("任课教师已有课程")
            options.append({
                "weekday": weekday,
                "period": period,
                "available": not reasons,
                "reason": "；".join(reasons) if reasons else "可调课",
            })
    return {"code": 0, "message": "ok", "data": options}


async def _substitute_candidates(session: AsyncSession, tenant_id: int, subject_id: int, academic_year: str, term: str) -> dict[int, str]:
    """可代课候选:本学期任教该学科的教师(任意班级),无任教关系时回退学科教研组成员。"""
    rows = list((await session.execute(
        select(TeachingAssignment.teacher_id, User.name)
        .join(User, User.id == TeachingAssignment.teacher_id)
        .where(
            TeachingAssignment.tenant_id == tenant_id,
            TeachingAssignment.subject_id == subject_id,
            TeachingAssignment.academic_year == academic_year,
            TeachingAssignment.term == term,
            User.status == UserStatus.active,
        )
    )).all())
    if rows:
        return {int(tid): name for tid, name in rows}
    subject = (await session.execute(select(Subject).where(
        Subject.id == subject_id,
        Subject.tenant_id == tenant_id,
    ))).scalars().first()
    if subject is None:
        return {}
    group_units = list((await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type == "subject_group",
        OrganizationUnit.status == "active",
    ))).scalars().all())
    unit_ids = [unit.id for unit in group_units if unit.subject_id == subject.id]
    if not unit_ids:
        return {}
    appts = list((await session.execute(select(StaffAppointment.staff_id, User.name)
        .join(User, User.id == StaffAppointment.staff_id)
        .where(
            StaffAppointment.tenant_id == tenant_id,
            StaffAppointment.organization_unit_id.in_(unit_ids),
            StaffAppointment.status == "active",
            User.status == UserStatus.active,
        ))).all())
    return {int(tid): name for tid, name in appts}


@router.get("/substitutes", summary="查询某节课的可代课教师")
async def schedule_substitutes(
    schedule_id: int,
    academic_year: str,
    term: str = "1",
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    source = (await session.execute(select(Schedule).where(
        Schedule.id == schedule_id,
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == academic_year,
        Schedule.term == term,
    ))).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="课表记录不存在")
    candidates = await _substitute_candidates(session, tenant_id, source.subject_id, academic_year, term)
    rows = list((await session.execute(select(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == academic_year,
        Schedule.term == term,
    ))).scalars().all())
    load_by_teacher: dict[int, int] = {}
    for row in rows:
        if row.teacher_id is not None:
            load_by_teacher[row.teacher_id] = load_by_teacher.get(row.teacher_id, 0) + 1
    data = []
    for teacher_id, name in candidates.items():
        if teacher_id == source.teacher_id:
            continue
        reason = "该时段有课" if _slot_has_conflict(
            rows, weekday=source.weekday, period=source.period, parity=source.week_parity,
            match=lambda row: row.teacher_id == teacher_id, exclude_id=source.id,
        ) else ""
        data.append({
            "teacher_id": teacher_id,
            "teacher_name": name,
            "weekly_lessons": load_by_teacher.get(teacher_id, 0),
            "available": not reason,
            "reason": reason or "可代课",
        })
    data.sort(key=lambda item: (not item["available"], item["weekly_lessons"]))
    return {"code": 0, "message": "ok", "data": data}


class ScheduleSubstituteIn(BaseModel):
    schedule_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    teacher_id: int


@router.post("/substitutes", summary="执行代课(更换该节课教师)")
async def substitute_schedule(
    body: ScheduleSubstituteIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    source = (await session.execute(select(Schedule).where(
        Schedule.id == body.schedule_id,
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year,
        Schedule.term == body.term,
    ))).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="课表记录不存在")
    candidates = await _substitute_candidates(session, tenant_id, source.subject_id, body.academic_year, body.term)
    if body.teacher_id not in candidates:
        raise HTTPException(status_code=422, detail="该教师不具备本学期此学科的任教资格")
    if body.teacher_id == source.teacher_id:
        raise HTTPException(status_code=422, detail="代课教师与当前任课教师相同")
    conflict_rows = list((await session.execute(select(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year,
        Schedule.term == body.term,
    ))).scalars().all())
    if _slot_has_conflict(
        conflict_rows, weekday=source.weekday, period=source.period, parity=source.week_parity,
        match=lambda row: row.teacher_id == body.teacher_id, exclude_id=source.id,
    ):
        raise HTTPException(status_code=409, detail="该教师在此时段已有课程")
    source.teacher_id = body.teacher_id
    await session.commit()
    subject = await session.get(Subject, source.subject_id)
    klass = await session.get(Class, source.class_id)
    await session.refresh(source)
    return {"code": 0, "message": "ok", "data": _schedule_out(
        source,
        {body.teacher_id: candidates[body.teacher_id]},
        {subject.id: subject.name} if subject else {},
        {klass.id: klass.name} if klass else {},
    )}


@router.post("/adjustments", summary="执行课表调课")
async def move_schedule(
    body: ScheduleMoveIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    grid = await _load_grid_config(session, tenant_id, body.academic_year, body.term)
    days = body.days if body.days is not None else grid["days"]
    periods_per_day = body.periods_per_day if body.periods_per_day is not None else grid["periods_per_day"]
    source = (await session.execute(select(Schedule).where(
        Schedule.id == body.schedule_id,
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year,
        Schedule.term == body.term,
    ))).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="课表记录不存在")
    subject = await session.get(Subject, source.subject_id)
    if (
        grid.get("enable_evening")
        and grid.get("evening_start_period")
        and body.target_period >= grid["evening_start_period"]
        and source.subject_id not in _evening_subject_ids_for_parity(grid, source.week_parity)
    ):
        raise HTTPException(status_code=422, detail="该学科未获准安排主课晚自习")
    teaching_relation = (await session.execute(select(TeachingAssignment).where(
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.teacher_id == source.teacher_id,
        TeachingAssignment.subject_id == source.subject_id,
        TeachingAssignment.class_id == source.class_id,
        TeachingAssignment.academic_year == body.academic_year,
        TeachingAssignment.term == body.term,
    ))).scalar_one_or_none()
    if teaching_relation is None:
        raise HTTPException(status_code=409, detail="教师未配置该班该学科的任教关系")
    if body.target_weekday > days or body.target_period > periods_per_day:
        raise HTTPException(status_code=422, detail="目标时段不在当前排课规则范围内")
    rows = list((await session.execute(select(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year,
        Schedule.term == body.term,
    ))).scalars().all())
    if _slot_has_conflict(
        rows, weekday=body.target_weekday, period=body.target_period, parity=source.week_parity,
        match=lambda row: row.class_id == source.class_id, exclude_id=source.id,
    ):
        raise HTTPException(status_code=409, detail="目标时段已有该班课程")
    if source.teacher_id is not None:
        if _slot_has_conflict(
            rows, weekday=body.target_weekday, period=body.target_period, parity=source.week_parity,
            match=lambda row: row.teacher_id == source.teacher_id, exclude_id=source.id,
        ):
            raise HTTPException(status_code=409, detail="任课教师在目标时段已有课程")
    source.weekday = body.target_weekday
    source.period = body.target_period
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"id": source.id, "weekday": source.weekday, "period": source.period}}
