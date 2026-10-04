"""排课系统 API：基础资源、任教关系、周课表和日期课表。"""
import asyncio
import logging
import os
import random
import secrets
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user, require_management_user
from app.core.security import get_password_hash
from app.db.session import get_session
from app.models.enums import BaseUserRole, EveningParity, StudentStatus, UserStatus, WeekParity
from app.models.facility import Room
from app.models.gaokao import GaokaoScheme
from app.models.org import (
    Class, CourseHourPlan, Grade, OrganizationUnit, Schedule, StaffAppointment, Student, Subject,
    TeachingAssignment, Tenant, TenantConfig, User,
)
from app.services.academic.gaokao import SubjectChoicePolicy, get_subject_choice_strategy
from app.services.scheduling import (
    ScheduleItem,
    ScheduleResult,
    ScheduleValidationIssue,
    ensure_teacher_evening_daytime_anchors,
    expand_schedule,
    find_schedule_conflicts,
    has_scheduled_hours,
    generate_schedule,
    parity_conflicts,
    validate_schedule_requirements,
)
from app.services.scheduling import diagnose_staffing_gaps
from app.services.scheduling.diagnosis import (
    apply_suggestion_to_group,
    diagnose_generation_failure,
)
from app.services.scheduling.evening_cpsat import generate_evening_schedule
from app.services.scheduling.soft_search import improve_soft_period_preferences
from app.services.scheduling.strategies import build_schedule_strategy, list_schedule_strategies
from app.services.scheduling.generate_jobs import GenerateBusy
from app.services.scheduling.rules import (
    RuleGroupDocument,
    blocking_rule_results,
    compile_rule_group,
    dump_stored_rule_groups,
    parse_stored_rule_groups,
    pick_rule_group,
    normalize_legacy_rule_group,
    evaluate_rule_group,
    generation_slot_patterns,
    merge_required_teachers_by_slot,
    generation_teacher_forbidden_slots,
    generation_teacher_class_forbidden_slots,
    generation_class_slot_allowed_subjects,
    generation_global_forbidden_slots,
    generation_class_required_subject_slots,
    generation_consecutive_requirements,
    generation_evening_free_days,
    generation_evening_self_study_candidates,
    generation_gap_free_groups,
    generation_class_gap_free_weekdays,
    generation_slot_teacher_balance_scope,
    generation_evening_parity_pairs,
    generation_daytime_parity_pairs,
    generation_teacher_evening_daytime_links,
    generation_teacher_preferred_evening_weekdays,
    generation_teacher_required_evening_weekdays,
    generation_r15_exempt_teacher_ids,
    generation_early_subject_ids,
    generation_early_subject_prefs,
    generation_gap_fill_late_subjects,
    generation_subject_allowed_slots,
    generation_subject_forbidden_slots,
    generation_teacher_daily_limits,
    generation_teacher_period_minima,
)
from app.services.org.staff_roles import replace_staff_roles
from app.services.academic.auto_teaching import (
    TeacherScopeRule,
    apply_subject_periods,
    assignments_outside_rebuild_scope,
    build_auto_assignments,
    target_class_ids,
)
from app.services.org.cohort import expected_cohort_label, normalize_cohort_label
from app.workers.scheduling.generate import (
    WorkerTimeout,
    run_daytime_cpsat,
    run_evening_cpsat,
    solver_worker_count,
    spawn_generate_job,
)

router = APIRouter(prefix="/scheduling", tags=["排课管理"], dependencies=[Depends(require_management_user)])
logger = logging.getLogger(__name__)
SCHEDULING_GRID_CONFIG_KEY = "scheduling_grid_config"
SCHEDULING_RULE_GROUP_CONFIG_KEY = "scheduling_rule_group"
SUBJECT_DISPLAY_ORDER = (
    "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理", "体育",
    "音乐", "美术", "心理", "校本", "班会", "生涯",
)


def _sort_subjects(subjects: list[Subject]) -> list[Subject]:
    order = {name: index for index, name in enumerate(SUBJECT_DISPLAY_ORDER)}
    return sorted(subjects, key=lambda item: (order.get(item.name, len(order)), item.name, item.id or 0))


def _worker_timeout_http(exc: WorkerTimeout) -> HTTPException:
    return HTTPException(
        status_code=504,
        detail={
            "message": exc.message,
            "timeout_seconds": exc.timeout_seconds,
        },
    )


def _cpsat_retry_seeds(base_seed: int, count: int) -> list[int]:
    """同一起始种子下给出互不重复的求解种子；相邻值不要用等差，避免搜索空间挤在一起。"""
    modulus = 2_147_483_647
    base = int(base_seed) % modulus
    seeds = [base]
    seen = {base}
    rng = random.Random(base)
    while len(seeds) < max(1, int(count)):
        nxt = rng.randrange(modulus)
        if nxt in seen:
            continue
        seen.add(nxt)
        seeds.append(nxt)
    return seeds


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
    weekly_periods: float = Field(default=4, ge=0, le=20, multiple_of=0.5)
    weekday_periods: float | None = Field(default=None, ge=0, le=20, multiple_of=0.5)
    saturday_periods: float = Field(default=0, ge=0, le=10, multiple_of=0.5)
    week_parity: WeekParity = WeekParity.all
    evening_periods_odd: int = Field(default=0, ge=0, le=1)
    evening_periods_even: int = Field(default=0, ge=0, le=1)
    evening_parity: EveningParity = EveningParity.all

    @model_validator(mode="after")
    def validate_week_parity(self):
        if self.weekday_periods is None:
            self.weekday_periods = self.weekly_periods
        self.weekly_periods = round(self.weekday_periods + self.saturday_periods, 2)
        has_half_period = any(
            value % 1 != 0 for value in (self.weekday_periods, self.saturday_periods)
        )
        if not has_half_period and self.week_parity != WeekParity.all:
            raise ValueError("只有包含 0.5 节隔周课时的方案才能选择单周或双周")
        odd = self.evening_periods_odd
        even = self.evening_periods_even
        if self.evening_parity == EveningParity.either:
            if odd <= 0 or even <= 0:
                raise ValueError("晚课无规定单双时，单周和双周额度都应记 1，由程序只排其中一侧")
        elif self.evening_parity == EveningParity.odd and (odd <= 0 or even > 0):
            raise ValueError("晚课指定单周时，只能勾单周额度")
        elif self.evening_parity == EveningParity.even and (even <= 0 or odd > 0):
            raise ValueError("晚课指定双周时，只能勾双周额度")
        elif self.evening_parity == EveningParity.all and (odd > 0) != (even > 0):
            self.evening_parity = EveningParity.odd if odd > 0 else EveningParity.even
        return self


class AssignmentIn(BaseModel):
    teacher_id: int | None = None
    subject_id: int | None = None
    class_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    weekly_periods: float = Field(default=4, ge=0, le=20, multiple_of=0.5)
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


class LockedScheduleItemIn(BaseModel):
    """A grid cell that the generator must preserve during preview or generation."""
    assignment_id: int | None = Field(default=None, ge=1)
    class_id: int = Field(ge=1)
    subject_id: int = Field(ge=1)
    teacher_id: int | None = Field(default=None, ge=1)
    weekday: int = Field(ge=1, le=7)
    period: int = Field(ge=1, le=12)
    week_parity: WeekParity = WeekParity.all


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
    rule_group_id: str | None = Field(default=None, max_length=80)
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
    solver: str = Field(default="cpsat", description="求解器：cpsat=全局最优（推荐）/ greedy=贪心快速")
    random_seed: int | None = Field(
        default=None,
        ge=0,
        le=2_147_483_647,
        description="随机种子；不传则每次生成随机起始种子，再按轮次递增重试（最多 5 组）",
    )
    preview: bool = Field(default=False, description="只生成预览，不写入正式课表")
    locked_items: list[LockedScheduleItemIn] = Field(default_factory=list, max_length=500)
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
        if self.enable_evening and self.periods_per_day is not None:
            # 不写死第 9 节：正式课上限变化后自动接到其后
            if (
                self.evening_start_period is None
                or self.evening_start_period <= self.periods_per_day
            ):
                self.evening_start_period = self.periods_per_day + 1
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
        if self.enable_evening:
            # 正式课节数上调后（如 8→9），旧的 evening_start_period=9 会失效；自动接到正式课之后
            if (
                self.evening_start_period is None
                or self.evening_start_period <= self.periods_per_day
            ):
                self.evening_start_period = self.periods_per_day + 1
            if self.evening_start_period + max(evening_profiles, default=0) - 1 > 12:
                raise ValueError("晚自习结束节次不能超过第 12 节")
        else:
            self.evening_start_period = None
        if self.term_start_monday and self.term_start_monday.weekday() != 0:
            raise ValueError("学期开始日期必须为周一")
        if self.first_week_parity is WeekParity.all:
            raise ValueError("首周类型只能是单周或双周")
        return self


class ScheduleMoveIn(BaseModel):
    schedule_id: int
    target_weekday: int = Field(ge=1, le=7)
    target_period: int = Field(ge=1, le=12)
    target_week_parity: WeekParity | None = None
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    days: int | None = Field(default=None, ge=1, le=7)
    periods_per_day: int | None = Field(default=None, ge=1, le=12)
    # 前端勾选完全部检查项后强制执行（含对调）
    force: bool = False


class ScheduleAdjustPreviewIn(BaseModel):
    schedule_id: int
    target_weekday: int = Field(ge=1, le=7)
    target_period: int = Field(ge=1, le=12)
    target_week_parity: WeekParity | None = None
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    days: int | None = Field(default=None, ge=1, le=7)
    periods_per_day: int | None = Field(default=None, ge=1, le=12)


class RuleGroupValidationIn(BaseModel):
    group: RuleGroupDocument
    use_current_schedule: bool = True


class ApplySuggestionIn(BaseModel):
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    group_id: str = Field(min_length=1, max_length=80)
    suggestion: dict[str, Any] = Field(default_factory=dict)


class VerifyScheduleIn(BaseModel):
    """用综合规则对已保存课表做反向校验。"""
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    class_id: int | None = Field(default=None, ge=1, description="按班级推断年级并匹配综合规则")
    grade_id: int | None = Field(default=None, ge=1)
    rule_group_id: str | None = Field(default=None, max_length=80)


class RuleGroupCatalogIn(BaseModel):
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", min_length=1, max_length=20)
    active_id: str | None = None
    groups: list[RuleGroupDocument] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def align_term_and_ids(self):
        seen: set[str] = set()
        for group in self.groups:
            if group.id in seen:
                raise ValueError(f"规则组 ID 重复：{group.id}")
            seen.add(group.id)
            if group.academic_year != self.academic_year or group.term != self.term:
                raise ValueError("规则组学年学期必须与目录一致")
        if self.active_id and self.active_id not in seen and self.groups:
            raise ValueError("active_id 必须指向目录中的规则组")
        return self


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
    exclude_ids: set[int] | None = None,
) -> bool:
    skipped = set(exclude_ids or ())
    if exclude_id is not None:
        skipped.add(exclude_id)
    return any(
        row.weekday == weekday
        and row.period == period
        and row.id not in skipped
        and match(row)
        and parity_conflicts(row.week_parity, parity)
        for row in rows
    )


def _evening_period_forbidden(grid: dict, subject_id: int | None, parity: WeekParity | str, period: int) -> bool:
    if not subject_id:
        return False
    start = grid.get("evening_start_period")
    return bool(
        grid.get("enable_evening")
        and start
        and period >= start
        and subject_id not in _evening_subject_ids_for_parity(grid, parity)
    )


def _period_band(grid: dict, period: int) -> Literal["daytime", "evening"]:
    start = grid.get("evening_start_period") if grid.get("enable_evening") else None
    if start and period >= int(start):
        return "evening"
    return "daytime"


def _slot_lane_block(
    *,
    grid: dict,
    source: Schedule,
    target_weekday: int,
    target_period: int,
    move_parity: WeekParity,
) -> str | None:
    """调课通道：
    - 白天工作日 ↔ 白天工作日
    - 周六：整课 all 只能对 all（单双同格一起动）；0.5 可单六↔双六并改单双周
    - 晚自习：整晚 all 对 all；0.5 可跨单双周（不可与白天对调）
    """
    source_band = _period_band(grid, source.period)
    target_band = _period_band(grid, target_period)
    if source_band != target_band:
        return "晚自习不能与白天课对调"

    source_parity = WeekParity(source.week_parity)
    # 整课/整晚不可拆成单侧，否则另一侧会空（例如英语整课被单周数学顶掉）
    if source_parity is WeekParity.all and move_parity is not WeekParity.all:
        return "单双周相同的课需两格一起调动"
    if source_parity is not WeekParity.all and move_parity is WeekParity.all:
        return "隔周课不能改成单双周相同"

    if source_band == "evening":
        return None

    source_sat = source.weekday == 6
    target_sat = target_weekday == 6
    if source_sat and not target_sat:
        return "周六课只能在单六/双六内对调，不能调到工作日"
    if (not source_sat) and target_sat:
        return "工作日课不能调到单六/双六"
    return None


def _class_peers_at(
    rows: list[Schedule],
    *,
    class_id: int,
    weekday: int,
    period: int,
    parity: WeekParity | str,
    exclude_id: int,
) -> list[Schedule]:
    return [
        row for row in rows
        if row.id != exclude_id
        and row.class_id == class_id
        and row.weekday == weekday
        and row.period == period
        and parity_conflicts(row.week_parity, parity)
    ]


def _check(key: str, label: str, passed: bool, *, severity: str = "hard") -> dict[str, Any]:
    return {"key": key, "label": label, "passed": passed, "severity": severity}


def _evaluate_move_or_swap(
    rows: list[Schedule],
    *,
    source: Schedule,
    target_weekday: int,
    target_period: int,
    grid: dict,
    target_parity: WeekParity | str | None = None,
    subject_names: dict[int, str] | None = None,
    teacher_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    """空位=挪课；同班占位=对调。返回逐条 checks，供前端勾选确认。"""
    subject_names = subject_names or {}
    teacher_names = teacher_names or {}
    move_parity = WeekParity(target_parity) if target_parity is not None else WeekParity(source.week_parity)
    lane_block = _slot_lane_block(
        grid=grid,
        source=source,
        target_weekday=target_weekday,
        target_period=target_period,
        move_parity=move_parity,
    )
    if lane_block:
        return {
            "mode": "move",
            "selectable": False,
            "available": False,
            "checks": [_check("slot_lane", lane_block, False)],
            "reason": lane_block,
            "week_parity": move_parity.value,
            "swap_schedule_id": None,
            "swap_with_subject": None,
            "swap_with_teacher": None,
        }
    checks: list[dict[str, Any]] = []
    peers = _class_peers_at(
        rows,
        class_id=source.class_id,
        weekday=target_weekday,
        period=target_period,
        parity=move_parity,
        exclude_id=source.id,
    )

    evening_ok = not _evening_period_forbidden(grid, source.subject_id, move_parity, target_period)
    checks.append(_check("evening_source", "调入后本课晚自习学科允许", evening_ok))

    if not peers:
        teacher_ok = True
        if source.teacher_id is not None:
            teacher_ok = not _slot_has_conflict(
                rows,
                weekday=target_weekday,
                period=target_period,
                parity=move_parity,
                match=lambda row: row.teacher_id == source.teacher_id,
                exclude_id=source.id,
            )
        checks.append(_check("teacher_source", "任课教师在目标时段不撞课", teacher_ok))
        checks.append(_check("class_empty", "目标时段本班为空位（直接挪课）", True))
        failed = [item["label"] for item in checks if not item["passed"]]
        # 撞课是硬障碍：不可点，前端显示「撞课」
        if not teacher_ok:
            return {
                "mode": "move",
                "selectable": False,
                "available": False,
                "checks": checks,
                "reason": "挪到该时段会撞课（你在该时段已有其他班）",
                "week_parity": move_parity.value,
                "swap_schedule_id": None,
                "swap_with_subject": None,
                "swap_with_teacher": None,
            }
        return {
            "mode": "move",
            "selectable": True,
            "available": not failed,
            "checks": checks,
            "reason": "；".join(failed) if failed else "可调课",
            "week_parity": move_parity.value,
            "swap_schedule_id": None,
            "swap_with_subject": None,
            "swap_with_teacher": None,
        }

    if len(peers) > 1:
        checks.append(_check("class_unique", "目标时段本班课程唯一，可对调", False))
        return {
            "mode": "swap",
            "selectable": False,
            "available": False,
            "checks": checks,
            "reason": "目标时段班级课程重叠，无法对调",
            "week_parity": move_parity.value,
            "swap_schedule_id": None,
            "swap_with_subject": None,
            "swap_with_teacher": None,
        }

    peer = peers[0]
    source_parity = WeekParity(source.week_parity)
    peer_parity = WeekParity(peer.week_parity)
    # 整课与 0.5 互相对调会拆格（另一侧变空），禁止
    if source_parity is WeekParity.all and peer_parity is not WeekParity.all:
        return {
            "mode": "swap",
            "selectable": False,
            "available": False,
            "checks": checks,
            "reason": "目标是隔周课，单双相同的整课不能与之对调",
            "week_parity": move_parity.value,
            "swap_schedule_id": peer.id,
            "swap_with_subject": subject_names.get(peer.subject_id or 0) or "对方课程",
            "swap_with_teacher": teacher_names.get(peer.teacher_id or 0) if peer.teacher_id else "未安排教师",
        }
    if source_parity is not WeekParity.all and peer_parity is WeekParity.all:
        return {
            "mode": "swap",
            "selectable": False,
            "available": False,
            "checks": checks,
            "reason": "目标是单双相同整课，隔周课对调会拆开对方",
            "week_parity": move_parity.value,
            "swap_schedule_id": peer.id,
            "swap_with_subject": subject_names.get(peer.subject_id or 0) or "对方课程",
            "swap_with_teacher": teacher_names.get(peer.teacher_id or 0) if peer.teacher_id else "未安排教师",
        }
    pair_exclude = {source.id, peer.id}
    peer_subject = subject_names.get(peer.subject_id or 0) or "对方课程"
    peer_teacher = teacher_names.get(peer.teacher_id or 0) if peer.teacher_id else "未安排教师"
    # 对调后对方落到源格，沿用源课原单双周
    peer_back_parity = WeekParity(source.week_parity)

    checks.append(_check(
        "swap_target",
        f"与「{peer_subject}」" + (f"（{peer_teacher}）" if peer_teacher else "") + "对调",
        True,
        severity="info",
    ))

    peer_evening_ok = not _evening_period_forbidden(grid, peer.subject_id, peer_back_parity, source.period)
    checks.append(_check(
        "evening_peer",
        f"对调后「{peer_subject}」晚自习学科允许",
        peer_evening_ok,
    ))

    source_teacher_ok = True
    if source.teacher_id is not None:
        source_teacher_ok = not _slot_has_conflict(
            rows,
            weekday=target_weekday,
            period=target_period,
            parity=move_parity,
            match=lambda row: row.teacher_id == source.teacher_id,
            exclude_ids=pair_exclude,
        )
    checks.append(_check(
        "teacher_source_swap",
        "对调后：你到对方时段不撞课",
        source_teacher_ok,
    ))

    peer_teacher_ok = True
    if peer.teacher_id is not None:
        peer_teacher_ok = not _slot_has_conflict(
            rows,
            weekday=source.weekday,
            period=source.period,
            parity=peer_back_parity,
            match=lambda row: row.teacher_id == peer.teacher_id,
            exclude_ids=pair_exclude,
        )
    checks.append(_check(
        "teacher_peer_swap",
        f"对调后：{peer_teacher}到你原时段不撞课",
        peer_teacher_ok,
    ))

    failed = [item["label"] for item in checks if not item["passed"]]
    label = f"可与{peer_subject}" + (f"（{peer_teacher}）" if peer_teacher else "") + "对调"
    # 对调后任一方教师撞课：硬拦。悬停文案说清方向，不用检查项里的「不撞课」肯定句。
    if not source_teacher_ok or not peer_teacher_ok:
        collision_bits: list[str] = []
        if not source_teacher_ok:
            # 你去对方时段：你在对方那个点已有其他班的课
            collision_bits.append("你去对方时段会撞课（你在该时段已有其他班）")
        if not peer_teacher_ok:
            # 对方来你时段：对方在你原来那个点已有其他班的课
            collision_bits.append(
                f"{peer_teacher}来你原时段会撞课（对方在该时段已有其他班）"
            )
        return {
            "mode": "swap",
            "selectable": False,
            "available": False,
            "checks": checks,
            "reason": "；".join(collision_bits) if collision_bits else "对调后教师会撞课",
            "week_parity": move_parity.value,
            "swap_schedule_id": peer.id,
            "swap_with_subject": peer_subject,
            "swap_with_teacher": peer_teacher,
        }
    return {
        "mode": "swap",
        "selectable": True,
        "available": not failed,
        "checks": checks,
        "reason": "；".join(failed) if failed else label,
        "week_parity": move_parity.value,
        "swap_schedule_id": peer.id,
        "swap_with_subject": peer_subject,
        "swap_with_teacher": peer_teacher,
    }


def _iter_adjustment_targets(
    *,
    source: Schedule,
    days: int,
    periods_per_day: int,
    grid: dict,
) -> list[tuple[int, int, WeekParity]]:
    """按课位通道生成目标：工作日白天 / 单六与双六 / 晚自习（单双均可）。"""
    evening_start = grid.get("evening_start_period") if grid.get("enable_evening") else None
    daytime_end = periods_per_day
    if evening_start:
        daytime_end = max(0, min(periods_per_day, int(evening_start) - 1))
    source_parity = WeekParity(source.week_parity)
    source_band = _period_band(grid, source.period)
    targets: list[tuple[int, int, WeekParity]] = []

    if source_band == "evening":
        if not evening_start:
            return targets
        eve = int(evening_start)
        # 整晚只出 all；0.5 出单+双（可跨单双周）
        eve_parities = (
            [WeekParity.all]
            if source_parity is WeekParity.all
            else [WeekParity.odd, WeekParity.even]
        )
        for weekday in range(1, days + 1):
            for parity in eve_parities:
                targets.append((weekday, eve, parity))
        return targets

    # 周六：整课只出 all；0.5 出单六+双六
    if source.weekday == 6:
        sat_parities = (
            [WeekParity.all]
            if source_parity is WeekParity.all
            else [WeekParity.odd, WeekParity.even]
        )
        for period in range(1, daytime_end + 1):
            for parity in sat_parities:
                targets.append((6, period, parity))
        return targets

    weekday_limit = min(5, days)
    for weekday in range(1, weekday_limit + 1):
        for period in range(1, daytime_end + 1):
            targets.append((weekday, period, source_parity))
    return targets


async def _rule_checks_after_adjustment(
    session: AsyncSession,
    *,
    tenant_id: int,
    academic_year: str,
    term: str,
    rows: list[Schedule],
    source: Schedule,
    target_weekday: int,
    target_period: int,
    target_parity: WeekParity | str | None,
    swap_schedule_id: int | None,
    class_id: int,
) -> list[dict[str, Any]]:
    """对调/挪课「之后」相对「之前」新增的硬规则失败项（后端 evaluate_rule_group）。

    调整前就存在的同样违规不列出，避免把旧账当成这次对调造成的。
    """
    grade_id = (
        await session.execute(
            select(Class.grade_id).where(Class.tenant_id == tenant_id, Class.id == class_id)
        )
    ).scalar_one_or_none()
    groups, active_id = await _load_rule_catalog(session, tenant_id, academic_year, term)
    group = pick_rule_group(groups, grade_id=int(grade_id) if grade_id else None, active_id=active_id)
    if group is None:
        return []

    move_parity = WeekParity(target_parity) if target_parity is not None else WeekParity(source.week_parity)
    origin_parity = WeekParity(source.week_parity)
    baseline = [schedule_item_from_row(row) for row in rows]
    hypothetical: list[ScheduleItem] = []
    for row in rows:
        item = schedule_item_from_row(row)
        if row.id == source.id:
            item = replace(item, weekday=target_weekday, period=target_period, week_parity=move_parity)
        elif swap_schedule_id and row.id == swap_schedule_id:
            item = replace(item, weekday=source.weekday, period=source.period, week_parity=origin_parity)
        hypothetical.append(item)

    class_ids = {item.class_id for item in hypothetical}
    class_head_teacher_ids = {
        int(cid): head_teacher_id
        for cid, head_teacher_id in (
            await session.execute(
                select(Class.id, Class.head_teacher_id).where(
                    Class.tenant_id == tenant_id,
                    Class.id.in_(class_ids),
                )
            )
        ).all()
    } if class_ids else {}
    grid = await _load_grid_config(session, tenant_id, academic_year, term)
    rule_group = normalize_legacy_rule_group(group)
    evening_start = grid.get("evening_start_period")
    try:
        before_summary = evaluate_rule_group(
            rule_group,
            baseline,
            schedule_available=True,
            evening_start_period=evening_start,
            class_head_teacher_ids=class_head_teacher_ids,
        )
        after_summary = evaluate_rule_group(
            rule_group,
            hypothetical,
            schedule_available=True,
            evening_start_period=evening_start,
            class_head_teacher_ids=class_head_teacher_ids,
        )
    except ValueError:
        return []

    def _failure_sig(item: Any) -> tuple[str, str]:
        return (
            str(item.rule_id or item.code or ""),
            (item.message or "").strip(),
        )

    before_sigs = {_failure_sig(item) for item in blocking_rule_results(before_summary)}
    out: list[dict[str, Any]] = []
    for item in blocking_rule_results(after_summary):
        if _failure_sig(item) in before_sigs:
            continue
        detail = (item.message or item.title or item.code or "").strip()
        out.append(_check(
            f"rule:{item.rule_id or item.code}",
            f"调整后硬规则：{item.title}"
            + (f" — {detail}" if detail and detail != item.title else ""),
            False,
            severity="hard",
        ))
    return out


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
            payload["evening_parity"] = (
                plan.evening_parity.value if isinstance(plan.evening_parity, EveningParity) else plan.evening_parity
            )
            payload["week_parity"] = plan.week_parity.value if isinstance(plan.week_parity, WeekParity) else plan.week_parity
            if has_scheduled_hours(payload):
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
        if plan.evening_periods_odd > 0 or plan.evening_parity == EveningParity.either:
            odd[plan.class_id].add(plan.subject_id)
        if plan.evening_periods_even > 0 or plan.evening_parity == EveningParity.either:
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
            "evening_periods_odd", "evening_periods_even", "evening_parity",
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


async def _execute_schedule_generation(
    session: AsyncSession,
    body: GenerateIn,
    tenant_id: int,
    *,
    on_progress=None,
    persisted_job_id: str | None = None,
) -> dict:
    async def _progress(stage: str, message: str, **extra) -> None:
        if on_progress is not None:
            await on_progress(stage, message, **extra)
            # 让出事件循环，便于 SSE 先把进度推给前端
            await asyncio.sleep(0)

    await _progress("validating", "正在校验任教与课位资源", percent=5)
    grid = await _load_grid_config(session, tenant_id, body.academic_year, body.term)
    periods_per_day = body.periods_per_day if body.periods_per_day is not None else grid["periods_per_day"]
    evening_start = body.evening_start_period
    if body.enable_evening or any(body.evening_daily_periods_odd) or any(body.evening_daily_periods_even):
        if evening_start is None or evening_start <= periods_per_day:
            evening_start = periods_per_day + 1
    body = body.model_copy(update={
        "days": body.days if body.days is not None else grid["days"],
        "periods_per_day": periods_per_day,
        "evening_start_period": evening_start,
        "forbidden_slots": sorted({*body.forbidden_slots, *_grid_forbidden_slots(grid)}),
    })
    assignments = await _generation_assignment_payloads(session, body, tenant_id)
    if not assignments:
        raise HTTPException(status_code=422, detail="请先配置当前学年学期的任教关系")
    rule_group = await _resolve_generation_rule_group(session, tenant_id, body)
    # 预校验的「同科日上限」按容量估算；连堂学科（数学）允许某天 2 节，
    # 若前端传来 1 会把周课时 7 的数学误判为无解。求解器内仍按非连堂≤1、连堂≤2 硬约束。
    validation_body = body
    if body.solver == "cpsat" and (body.max_same_subject_per_day or 0) <= 1:
        validation_body = body.model_copy(update={"max_same_subject_per_day": 2})
    validation = _validate_generation(
        assignments,
        validation_body,
        await _administrative_primary_subject_ids(session, tenant_id),
    )
    if not validation.valid:
        msg = "排课条件无解，请先根据校验结果调整条件"
        diagnosis = diagnose_generation_failure(
            failure_kind="capacity",
            message=msg,
            rule_group=rule_group,
        )
        diagnosis["reasons"] = [
            msg,
            f"共 {len(validation.issues)} 项容量/师资冲突，请先在「校验」结果中处理。",
            *diagnosis.get("reasons", [])[1:],
        ]
        raise HTTPException(
            status_code=422,
            detail={
                "message": msg,
                "diagnosis": diagnosis,
                "reasons": diagnosis["reasons"],
                "suggestions": diagnosis["suggestions"],
                "issues": [asdict(issue) for issue in validation.issues[:20]],
            },
        )
    slot_patterns = generation_slot_patterns(rule_group) if rule_group else []
    teacher_forbidden_slots = generation_teacher_forbidden_slots(rule_group) if rule_group else {}
    gen_class_ids = sorted({int(item["class_id"]) for item in assignments})
    class_head_teacher_ids: dict[int, int | None] = {}
    if rule_group and gen_class_ids:
        class_head_teacher_ids = {
            int(class_id): head_teacher_id
            for class_id, head_teacher_id in (await session.execute(select(Class.id, Class.head_teacher_id).where(
                Class.tenant_id == tenant_id,
                Class.id.in_(gen_class_ids),
            ))).all()
        }
    teacher_class_forbidden_slots = (
        generation_teacher_class_forbidden_slots(rule_group, class_head_teacher_ids)
        if rule_group
        else {}
    )
    subject_forbidden_slots: dict[int, set[tuple[int, int]]] = dict(
        generation_subject_forbidden_slots(rule_group)
    ) if rule_group else {}
    if rule_group:
        # “允许课位”取反成全局禁排补集，让体育允许课位这类规则直接约束排课算法。
        allowed_map = generation_subject_allowed_slots(rule_group)
        universe = {
            (weekday, period)
            for weekday in range(1, (body.days or 5) + 1)
            for period in range(1, (body.periods_per_day or 7) + 1)
        }
        for subject_id, allowed in allowed_map.items():
            subject_forbidden_slots.setdefault(subject_id, set()).update(universe - allowed)
    class_slot_allowed: dict[int, dict[tuple[int, int], set[int]]] = (
        generation_class_slot_allowed_subjects(rule_group)
    ) if rule_group else {}
    if rule_group and gen_class_ids:
        # 全局课位禁排：展开到本次生成涉及的每一个班（课位必须空着）。
        for weekday, period in generation_global_forbidden_slots(rule_group):
            for class_id in gen_class_ids:
                class_slot_allowed.setdefault(class_id, {})[(weekday, period)] = set()
    class_required_subject_slots: dict[int, dict[tuple[int, int], set[int]]] = (
        generation_class_required_subject_slots(rule_group)
    ) if rule_group else {}
    pe_subject = (await session.execute(select(Subject).where(Subject.name == "体育"))).scalars().first()
    # 学科目标的每日上限：按任教关系展开到教师。
    teachers_by_subject: dict[int, set[int]] = {}
    for item in assignments:
        if item.get("teacher_id") is None:
            continue
        teachers_by_subject.setdefault(int(item["subject_id"]), set()).add(int(item["teacher_id"]))
    # 规则组的教师日上限与体育专项日上限合并：同一教师取更严格的值。
    merged_teacher_daily_limits: dict[int, int] = dict(
        generation_teacher_daily_limits(rule_group, teachers_by_subject=teachers_by_subject)
    ) if rule_group else {}
    if body.max_pe_teacher_lessons_per_day is not None and pe_subject is not None:
        for item in assignments:
            if (
                item["subject_id"] == pe_subject.id
                and item.get("teacher_id") is not None
            ):
                teacher_id = int(item["teacher_id"])
                pe_limit = int(body.max_pe_teacher_lessons_per_day)
                current = merged_teacher_daily_limits.get(teacher_id)
                merged_teacher_daily_limits[teacher_id] = (
                    min(current, pe_limit) if current is not None else pe_limit
                )
    teacher_daily_limits = merged_teacher_daily_limits or None
    evening_pairs = generation_evening_parity_pairs(rule_group) if rule_group else []
    evening_free_days = generation_evening_free_days(rule_group) if rule_group else None
    evening_self_study_candidates = (
        generation_evening_self_study_candidates(rule_group) if rule_group else None
    )
    class_gap_free_weekdays = (
        generation_class_gap_free_weekdays(rule_group) if rule_group else []
    )
    class_gap_free = bool(class_gap_free_weekdays)
    # 与导出脚本一致：有班级无空堂规则时，周一～周六第1～7节全部打包
    #（脚本写死 class_gap_free=True 且不限 weekdays）。
    if class_gap_free or (
        rule_group is not None
        and any(r.enabled and r.code == "class_gap_free" and r.priority == "hard" for r in rule_group.rules)
    ):
        class_gap_free = True
        class_gap_free_weekdays = []
    gap_free_groups = generation_gap_free_groups(
        rule_group, teachers_by_subject=teachers_by_subject
    ) if rule_group else None
    balance_scope = generation_slot_teacher_balance_scope(rule_group) if rule_group else None
    slot_teacher_cap = (
        {"weekdays": balance_scope[0], "periods": balance_scope[1], "cap": balance_scope[2]}
        if balance_scope and len(balance_scope) == 3 and balance_scope[2]
        else None
    )
    consecutive_requirements = (
        generation_consecutive_requirements(rule_group) if rule_group else None
    )
    early_subject_ids = generation_early_subject_ids(rule_group) if rule_group else set()
    early_subject_prefs = generation_early_subject_prefs(rule_group) if rule_group else []
    gap_fill_ids, gap_fill_late_from = (
        generation_gap_fill_late_subjects(rule_group) if rule_group else (set(), 8)
    )
    # 存在节次均衡规则时，自动叠加“节次摊散”策略，让第5节等节次摊给不同教师。
    effective_strategy_codes = list(body.strategy_codes)
    if (
        rule_group is not None
        and generation_slot_teacher_balance_scope(rule_group) is not None
        and "slot_teacher_spread" not in effective_strategy_codes
    ):
        effective_strategy_codes.append("slot_teacher_spread")
    await _progress("generating", "正在构建约束并求解课表", percent=12)
    class_ids = sorted({item["class_id"] for item in assignments})
    try:
        if body.solver == "cpsat":
            weekday_cap = int(body.periods_per_day or 9)
            saturday_cap = 7
            daily = grid.get("daily_periods") if isinstance(grid, dict) else None
            if isinstance(daily, list) and len(daily) >= 6 and daily[5]:
                saturday_cap = int(daily[5])
            # 单轮求解时限可用环境变量放宽；2 核小服务器 + 单双周课时结构下
            # 150s 常搜不到首个可行解（UNKNOWN→误报无解），实测 300s 内 170s 即出解。
            max_solve = float(os.environ.get("SCHEDULING_MAX_SOLVE_SECONDS", "300"))
            # 递增时限重试：难实例「换种子」收效甚微（每轮都 UNKNOWN 打满），加时才有效
            # （实测 150s UNKNOWN → 2线程 + 加时 170s 出解）。每轮时限 ×1/×2/×3。
            solve_rounds = [max_solve, max_solve * 2, max_solve * 3]
            seed_attempts = len(solve_rounds)
            # 不传 seed：每次任务随机起步；某一组超时/晚课对不上时换独立种子，不要整单失败。
            if body.random_seed is not None:
                base_seed = int(body.random_seed)
            else:
                base_seed = secrets.randbelow(1_000_000_000)
            seeds = _cpsat_retry_seeds(base_seed, seed_attempts)
            need_evening = any(body.evening_daily_periods_odd) or any(body.evening_daily_periods_even)

            async def _run_daytime(seed: int, attempt: int, total: int, limit: float):
                loop = asyncio.get_running_loop()
                solve_started = time.perf_counter()
                stop_tick = asyncio.Event()
                latest_solver: dict = {"solutions": 0, "message": "白天课求解中…"}
                prefix = f"第 {attempt}/{total} 次（时限{int(limit)}s）seed={seed}"

                def _solver_progress(info: dict) -> None:
                    latest_solver.update(info)
                    elapsed = float(info.get("elapsed") or (time.perf_counter() - solve_started))
                    percent = 12 + int((attempt - 1) / total * 60) + min(8, int(elapsed / limit * 8))
                    message = f"{prefix} · {info.get('message') or '白天课求解中…'}"
                    asyncio.run_coroutine_threadsafe(
                        _progress(
                            "generating",
                            message,
                            percent=percent,
                            elapsed=round(elapsed, 1),
                            solutions=info.get("solutions"),
                            phase=info.get("phase") or "daytime_search",
                        ),
                        loop,
                    )

                async def _heartbeat() -> None:
                    while not stop_tick.is_set():
                        elapsed = time.perf_counter() - solve_started
                        percent = 12 + int((attempt - 1) / total * 60) + min(8, int(elapsed / limit * 8))
                        solutions = int(latest_solver.get("solutions") or 0)
                        base = str(latest_solver.get("message") or "白天课求解中…")
                        await _progress(
                            "generating",
                            f"{prefix} · {base} · 已用时 {int(elapsed)}s"
                            + (f" · 已找到 {solutions} 个可行解" if solutions else ""),
                            percent=percent,
                            elapsed=round(elapsed, 1),
                            solutions=solutions,
                            phase="daytime_search",
                        )
                        try:
                            await asyncio.wait_for(stop_tick.wait(), timeout=1.0)
                        except asyncio.TimeoutError:
                            pass

                tick_task = asyncio.create_task(_heartbeat())
                try:
                    return await run_daytime_cpsat(
                        timeout=limit + 45,
                        assignments=assignments,
                        days=body.days, periods_per_day=body.periods_per_day,
                        forbidden_slots=set(body.forbidden_slots),
                        max_class_lessons_per_day=weekday_cap,
                        max_teacher_lessons_per_day=None,
                        max_class_lessons_on_saturday=min(7, saturday_cap),
                        max_teacher_lessons_on_saturday=7,
                        max_same_subject_per_day=None, max_teacher_weekly_periods=None,
                        teacher_daily_limits=merged_teacher_daily_limits or None,
                        teacher_forbidden_slots=teacher_forbidden_slots,
                        teacher_class_forbidden_slots=teacher_class_forbidden_slots or None,
                        subject_forbidden_slots=subject_forbidden_slots or None,
                        class_slot_allowed_subjects=class_slot_allowed or None,
                        class_required_subject_slots=class_required_subject_slots or None,
                        daytime_parity_pairs=generation_daytime_parity_pairs(rule_group) if rule_group else None,
                        class_gap_free=class_gap_free,
                        class_gap_free_weekdays=class_gap_free_weekdays or None,
                        subject_daily_spread=True,
                        gap_free_groups=gap_free_groups,
                        slot_teacher_cap=slot_teacher_cap,
                        slot_patterns=slot_patterns,
                        consecutive_requirements=consecutive_requirements,
                        teacher_period_minima=generation_teacher_period_minima(rule_group) if rule_group else None,
                        early_subject_ids=early_subject_ids or None,
                        early_subject_prefs=early_subject_prefs or None,
                        gap_fill_subject_ids=gap_fill_ids or None,
                        gap_fill_late_from_period=gap_fill_late_from,
                        random_seed=seed,
                        num_search_workers=solver_worker_count(),
                        max_time_seconds=limit,
                        # 首个可行解之后的软目标优化时长（质量换时间）；
                        # 2 线程下首解约 20s，总时长 ≈ 首解 + 本打磨上限。
                        polish_seconds=float(os.environ.get("SCHEDULING_POLISH_SECONDS", "150")),
                        on_progress=_solver_progress,
                    )
                finally:
                    stop_tick.set()
                    await tick_task

            evening_ctx: dict = {}
            if need_evening:
                evening_ctx["required_teacher_by_slot"] = (
                    merge_required_teachers_by_slot(rule_group, class_head_teacher_ids)
                    if rule_group else {}
                )
                evening_ctx["links"] = generation_teacher_evening_daytime_links(rule_group) if rule_group else []
                evening_ctx["preferred_eve"] = (
                    generation_teacher_preferred_evening_weekdays(rule_group) if rule_group else None
                )
                evening_ctx["required_eve_days"] = (
                    generation_teacher_required_evening_weekdays(rule_group) if rule_group else None
                )
                evening_ctx["first_eve"] = body.evening_start_period or body.periods_per_day + 1
                pe_id = (
                    await session.execute(select(Subject.id).where(Subject.tenant_id == tenant_id, Subject.name == "体育"))
                ).scalar_one_or_none()
                activity_id = (
                    await session.execute(
                        select(Subject.id).where(Subject.tenant_id == tenant_id, Subject.name == "自主学习")
                    )
                ).scalar_one_or_none()
                r15_exclude = {int(pe_id)} if pe_id is not None else set()
                if activity_id is not None:
                    r15_exclude.add(int(activity_id))
                if rule_group is not None:
                    for rule in rule_group.rules:
                        if rule.code == "teacher_multi_class_evening_adjacent":
                            rule.params["exclude_subject_ids"] = sorted(r15_exclude)
                evening_ctx["r15_exclude"] = r15_exclude
                evening_ctx["class_head_teacher_ids"] = class_head_teacher_ids

            last_error = "未开始求解"
            result = None
            last_blocked: list = []

            def _hard_blocks(items: list) -> list:
                if rule_group is None:
                    return []
                return blocking_rule_results(
                    evaluate_rule_group(
                        rule_group,
                        items,
                        schedule_available=True,
                        evening_start_period=body.evening_start_period,
                        class_head_teacher_ids=class_head_teacher_ids,
                    )
                )

            await _progress(
                "generating",
                f"本次起始种子 {base_seed}，最多 {len(seeds)} 轮（时限逐轮递增至 {int(solve_rounds[-1])}s）",
                percent=12,
                phase="daytime_search",
            )
            for attempt, (seed, limit) in enumerate(zip(seeds, solve_rounds), start=1):
                await _progress(
                    "generating",
                    f"开始第 {attempt}/{len(seeds)} 轮求解（时限{int(limit)}s，seed={seed}）",
                    percent=12 + int((attempt - 1) / len(seeds) * 60),
                    phase="daytime_search",
                )
                try:
                    cp = await _run_daytime(seed, attempt, len(seeds), limit)
                except WorkerTimeout as exc:
                    last_error = f"白天课超时（seed={seed}，{int(exc.timeout_seconds)}s）"
                    await _progress(
                        "generating",
                        f"{last_error}，将加时重试",
                        percent=12 + int(attempt / len(seeds) * 60),
                        phase="daytime_retry",
                    )
                    continue
                await _progress(
                    "generating",
                    f"第 {attempt} 次白天课完成（{cp.status}，{cp.solve_seconds:.1f}s）",
                    percent=70,
                    elapsed=round(cp.solve_seconds, 1),
                    phase="daytime_done",
                )
                if cp.status == "INFEASIBLE":
                    msg = "当前规则组合数学上无解（CP-SAT 已证明）"
                    diagnosis = diagnose_generation_failure(
                        failure_kind="cpsat_infeasible",
                        message=msg,
                        rule_group=rule_group,
                        solver_status=cp.status,
                    )
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "message": msg,
                            "solver": cp.status,
                            "diagnosis": diagnosis,
                            "reasons": diagnosis["reasons"],
                            "suggestions": diagnosis["suggestions"],
                        },
                    )
                if cp.status not in ("OPTIMAL", "FEASIBLE"):
                    last_error = f"白天课 {cp.status}（seed={seed}）"
                    continue
                candidate = ScheduleResult(
                    items=cp.items, unplaced=list(cp.unplaced),
                    staffing_issues=diagnose_staffing_gaps(cp.items),
                )
                if not need_evening:
                    blocked = _hard_blocks(candidate.items)
                    if blocked:
                        last_blocked = blocked
                        last_error = (
                            "硬规则验算未过："
                            + "、".join(item.rule_id for item in blocked[:4])
                            + f"（seed={seed}）"
                        )
                        await _progress(
                            "generating",
                            f"{last_error}，将加时重试",
                            percent=12 + int(attempt / len(seeds) * 60),
                            phase="hard_rule_retry",
                        )
                        continue
                    result = candidate
                    break
                await _progress(
                    "generating",
                    f"第 {attempt} 次白天课已可行，正在求解晚自习（seed={seed}）…",
                    percent=78,
                    phase="evening_search",
                )
                daytime_items = ensure_teacher_evening_daytime_anchors(
                    list(candidate.items),
                    links=evening_ctx["links"],
                    assignments=assignments,
                    teacher_forbidden_slots=teacher_forbidden_slots,
                    subject_forbidden_slots=subject_forbidden_slots,
                    evening_start_period=int(evening_ctx["first_eve"]),
                )
                try:
                    evening_result = await run_evening_cpsat(
                        assignments,
                        class_ids=class_ids,
                        first_evening_period=evening_ctx["first_eve"],
                        evening_daily_periods_odd=body.evening_daily_periods_odd,
                        evening_daily_periods_even=body.evening_daily_periods_even,
                        activity_subject_id=None,
                        required_teacher_by_slot=evening_ctx["required_teacher_by_slot"],
                        teacher_forbidden_slots=teacher_forbidden_slots,
                        class_slot_allowed_subjects=class_slot_allowed or None,
                        parity_subject_pairs=evening_pairs or None,
                        free_evening_days=evening_free_days or None,
                        anchor_items=daytime_items,
                        teacher_evening_daytime_links=evening_ctx["links"],
                        teacher_preferred_evening_weekdays=evening_ctx["preferred_eve"],
                        teacher_required_evening_weekdays=evening_ctx["required_eve_days"],
                        r15_exclude_subject_ids=evening_ctx["r15_exclude"],
                        r15_exclude_teacher_ids=generation_r15_exempt_teacher_ids(rule_group) if rule_group else None,
                        r15_enabled=bool(
                            rule_group
                            and any(
                                r.enabled and r.code == "teacher_multi_class_evening_adjacent" and r.priority == "hard"
                                for r in rule_group.rules
                            )
                        ),
                        random_seed=seed,
                        max_time_seconds=100.0,
                        num_search_workers=solver_worker_count(),
                        timeout=145,
                    )
                except WorkerTimeout as exc:
                    last_error = f"晚课超时（seed={seed}，{int(exc.timeout_seconds)}s）"
                    await _progress(
                        "generating",
                        f"{last_error}，将加时重试",
                        percent=12 + int(attempt / len(seeds) * 60),
                        phase="evening_retry",
                    )
                    continue
                if evening_result.status in ("OPTIMAL", "FEASIBLE"):
                    combined = replace(candidate, items=[*daytime_items, *evening_result.items])
                    blocked = _hard_blocks(combined.items)
                    if blocked:
                        last_blocked = blocked
                        last_error = (
                            "硬规则验算未过："
                            + "、".join(item.rule_id for item in blocked[:4])
                            + f"（seed={seed}）"
                        )
                        await _progress(
                            "generating",
                            f"{last_error}，将加时重试",
                            percent=12 + int(attempt / len(seeds) * 60),
                            phase="hard_rule_retry",
                        )
                        continue
                    result = combined
                    await _progress(
                        "generating",
                        f"第 {attempt} 次晚课求解成功（{evening_result.status}）",
                        percent=88,
                        phase="evening_done",
                    )
                    break
                last_error = f"晚课 {evening_result.status}（seed={seed}）"
                await _progress(
                    "generating",
                    f"{last_error}，将加时重试",
                    percent=12 + int(attempt / len(seeds) * 60),
                    phase="evening_retry",
                )
            if result is None:
                msg = (
                    f"已尝试 {len(seeds)} 轮递增时限求解（最高 {int(solve_rounds[-1])}s），仍无法排出可通过硬规则验算的课表。"
                    f"最后失败：{last_error}"
                    if "硬规则" in str(last_error)
                    else (
                        f"已尝试 {len(seeds)} 轮递增时限求解（最高 {int(solve_rounds[-1])}s），仍无法同时排出白天课和晚课。"
                        f"最后失败：{last_error}"
                    )
                )
                kind = (
                    "hard_rule_postcheck"
                    if "硬规则" in str(last_error)
                    else "evening_infeasible"
                    if "晚课" in str(last_error)
                    else "seed_exhausted"
                )
                diagnosis = diagnose_generation_failure(
                    failure_kind=kind,
                    message=msg,
                    rule_group=rule_group,
                    last_error=str(last_error),
                    seed_attempts=len(seeds),
                    hard_rule_failures=last_blocked or None,
                )
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": msg,
                        "diagnosis": diagnosis,
                        "reasons": diagnosis["reasons"],
                        "suggestions": diagnosis["suggestions"],
                    },
                )
        else:
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
            strategy_codes=effective_strategy_codes,
            random_seed=body.random_seed,
            max_teacher_weekly_periods=body.max_teacher_weekly_periods,
            slot_patterns=slot_patterns,
            teacher_forbidden_slots=teacher_forbidden_slots,
            teacher_class_forbidden_slots=teacher_class_forbidden_slots or None,
            subject_forbidden_slots=subject_forbidden_slots or None,
            class_slot_allowed_subjects=class_slot_allowed or None,
            consecutive_requirements=consecutive_requirements,
            locked_items=[item.model_dump(mode="json") for item in body.locked_items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    class_ids = gen_class_ids
    required_teacher_by_slot: dict[tuple[int, int], dict[int, int]] = (
        merge_required_teachers_by_slot(rule_group, class_head_teacher_ids)
        if rule_group
        else {}
    )
    if body.solver != "cpsat" and (
        any(body.evening_daily_periods_odd) or any(body.evening_daily_periods_even)
    ):
        await _progress("generating", "白天课已就绪，正在求解晚自习…", percent=78, phase="evening_search")
        evening_links = generation_teacher_evening_daytime_links(rule_group) if rule_group else []
        preferred_eve = (
            generation_teacher_preferred_evening_weekdays(rule_group) if rule_group else None
        )
        required_eve_days = (
            generation_teacher_required_evening_weekdays(rule_group) if rule_group else None
        )
        first_eve = body.evening_start_period or body.periods_per_day + 1
        daytime_items = ensure_teacher_evening_daytime_anchors(
            list(result.items),
            links=evening_links,
            assignments=assignments,
            teacher_forbidden_slots=teacher_forbidden_slots,
            subject_forbidden_slots=subject_forbidden_slots,
            evening_start_period=int(first_eve),
        )
        pe_id = (
            await session.execute(select(Subject.id).where(Subject.tenant_id == tenant_id, Subject.name == "体育"))
        ).scalar_one_or_none()
        activity_id = (
            await session.execute(
                select(Subject.id).where(Subject.tenant_id == tenant_id, Subject.name == "自主学习")
            )
        ).scalar_one_or_none()
        r15_exclude = {int(pe_id)} if pe_id is not None else set()
        if activity_id is not None:
            r15_exclude.add(int(activity_id))
        if rule_group is not None:
            for rule in rule_group.rules:
                if rule.code == "teacher_multi_class_evening_adjacent":
                    rule.params["exclude_subject_ids"] = sorted(r15_exclude)
        evening_result = generate_evening_schedule(
            assignments,
            class_ids=class_ids,
            first_evening_period=first_eve,
            evening_daily_periods_odd=body.evening_daily_periods_odd,
            evening_daily_periods_even=body.evening_daily_periods_even,
            activity_subject_id=None,
            required_teacher_by_slot=required_teacher_by_slot,
            teacher_forbidden_slots=teacher_forbidden_slots,
            class_slot_allowed_subjects=class_slot_allowed or None,
            parity_subject_pairs=evening_pairs or None,
            free_evening_days=evening_free_days or None,
            anchor_items=daytime_items,
            teacher_evening_daytime_links=evening_links,
            teacher_preferred_evening_weekdays=preferred_eve,
            teacher_required_evening_weekdays=required_eve_days,
            r15_exclude_subject_ids=r15_exclude,
            r15_exclude_teacher_ids=generation_r15_exempt_teacher_ids(rule_group) if rule_group else None,
            r15_enabled=bool(
                rule_group
                and any(
                    r.enabled and r.code == "teacher_multi_class_evening_adjacent" and r.priority == "hard"
                    for r in rule_group.rules
                )
            ),
            max_time_seconds=30.0,
            num_search_workers=solver_worker_count(),
        )
        if evening_result.status not in ("OPTIMAL", "FEASIBLE"):
            raise HTTPException(
                status_code=422,
                detail=f"晚课 CP-SAT 无解或超时：{evening_result.status}",
            )
        result = replace(result, items=[*daytime_items, *evening_result.items])
    if early_subject_ids or gap_fill_ids:
        before_soft = list(result.items)
        improved = improve_soft_period_preferences(
            before_soft,
            early_subject_ids=early_subject_ids or None,
            gap_fill_subject_ids=gap_fill_ids or None,
            late_from_period=gap_fill_late_from,
            evening_start_period=int(body.evening_start_period or body.periods_per_day + 1),
            forbidden_slots={tuple(slot) for slot in body.forbidden_slots},
            teacher_forbidden_slots=teacher_forbidden_slots,
            teacher_class_forbidden_slots=teacher_class_forbidden_slots or None,
            subject_forbidden_slots=subject_forbidden_slots or None,
            class_slot_allowed_subjects=class_slot_allowed or None,
            rule_group=rule_group,
            class_head_teacher_ids=class_head_teacher_ids or None,
            max_time_seconds=8.0,
        )
        if rule_group and blocking_rule_results(
            evaluate_rule_group(
                rule_group,
                improved.items,
                schedule_available=True,
                evening_start_period=body.evening_start_period,
                class_head_teacher_ids=class_head_teacher_ids,
            )
        ):
            result = replace(result, items=before_soft)
        else:
            result = replace(result, items=improved.items)
    final_conflicts = find_schedule_conflicts(result.items)
    if final_conflicts:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "生成结果存在教师或班级课位冲突，未保存课表",
                "code": "schedule_conflict_postcheck",
                "conflicts": final_conflicts[:50],
            },
        )
    rule_validation = None
    if rule_group:
        rule_validation = evaluate_rule_group(
            rule_group,
            result.items,
            schedule_available=bool(result.items),
            evening_start_period=body.evening_start_period,
            class_head_teacher_ids=class_head_teacher_ids,
        )
        hard_rule_failures = blocking_rule_results(rule_validation)
        if hard_rule_failures:
            msg = "生成结果不满足硬性班级课位规则，未保存课表"
            diagnosis = diagnose_generation_failure(
                failure_kind="hard_rule_postcheck",
                message=msg,
                rule_group=rule_group,
                hard_rule_failures=hard_rule_failures,
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "message": msg,
                    "rule_validation": rule_validation.model_dump(mode="json"),
                    "diagnosis": diagnosis,
                    "reasons": diagnosis["reasons"],
                    "suggestions": diagnosis["suggestions"],
                },
            )
    if body.preview:
        return {
            "preview": True,
            "created": len(result.items),
            "unplaced": result.unplaced,
            "class_count": len(class_ids),
            "strategy_codes": body.strategy_codes,
            "staffing_issues": result.staffing_issues,
            "items": [{
                "assignment_id": item.assignment_id,
                "class_id": item.class_id,
                "weekday": item.weekday,
                "period": item.period,
                "subject_id": item.subject_id,
                "teacher_id": item.teacher_id,
                "room": item.room,
                "week_parity": item.week_parity.value,
            } for item in result.items],
            "validation": {
                "assignment_count": validation.assignment_count,
                "requested_lessons": validation.requested_lessons,
                "available_slots": validation.available_slots,
            },
            "rule_validation": rule_validation.model_dump(mode="json") if rule_validation else None,
            "can_rollback": False,
        }
    await _progress("refreshing", "正在保存课表", percent=90)
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
    raw_history = history_config.config_value if history_config else None
    if isinstance(raw_history, list):
        history_list = [v for v in raw_history if isinstance(v, dict)]
    elif isinstance(raw_history, dict) and isinstance(raw_history.get("versions"), list):
        history_list = [v for v in raw_history["versions"] if isinstance(v, dict)]
    else:
        history_list = []
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
    response = {
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
        "rule_validation": rule_validation.model_dump(mode="json") if rule_validation else None,
        "can_rollback": bool(previous_rows),
    }
    if persisted_job_id:
        from app.services.scheduling.generate_job_store import stage_success

        await stage_success(session, persisted_job_id, tenant_id, response)
    await session.commit()
    return response


def _reject_generate_busy(exc: GenerateBusy) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": 429,
            "message": exc.message,
            "data": {"retry_after": exc.retry_after},
        },
        headers={"Retry-After": str(exc.retry_after)},
    )


@router.post("/generate", summary="生成周课表")
async def create_schedule(
    body: GenerateIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    from app.services.scheduling.generate_jobs import (
        GenerateBusy,
        release_generate_slot,
        try_acquire_generate_slot,
    )

    try:
        try_acquire_generate_slot(tenant_id)
    except GenerateBusy as exc:
        raise _reject_generate_busy(exc) from exc
    try:
        data = await _execute_schedule_generation(session, body, tenant_id)
        return {"code": 0, "message": "ok", "data": data}
    finally:
        release_generate_slot(tenant_id)


@router.post("/generate-jobs", summary="异步提交排课生成任务")
async def start_generate_job(
    body: GenerateIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    from app.services.scheduling.generate_jobs import (
        GenerateBusy,
        release_generate_slot,
        try_acquire_generate_slot,
    )
    from app.services.scheduling.generate_job_store import active_job, register_job

    payload = body.model_dump(mode="json")
    existing = await active_job(session, tenant_id, body.academic_year, body.term)
    if existing is not None:
        return {
            "code": 0,
            "message": "ok",
            "data": {"job_id": existing.id, "resumed": True},
        }

    try:
        try_acquire_generate_slot(tenant_id)
    except GenerateBusy as exc:
        raise _reject_generate_busy(exc) from exc

    job_id = uuid.uuid4().hex
    try:
        await register_job(session, job_id, tenant_id, payload)
        await session.commit()
        spawn_generate_job(tenant_id, payload, job_id=job_id)
    except Exception:
        release_generate_slot(tenant_id)
        raise

    return {"code": 0, "message": "ok", "data": {"job_id": job_id, "resumed": False}}


@router.get("/generate-jobs/active", summary="查询当前学期正在执行的排课任务")
async def get_active_generate_job(
    academic_year: str,
    term: str = "1",
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    from app.services.scheduling.generate_job_store import active_job, job_snapshot

    row = await active_job(session, tenant_id, academic_year, term)
    return {"code": 0, "message": "ok", "data": job_snapshot(row) if row else None}


@router.get("/generate-jobs/{job_id}/events", summary="SSE 订阅排课生成进度")
async def stream_generate_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    import json

    from fastapi.responses import StreamingResponse
    from app.models.scheduling import SchedulingGenerateJob
    from app.services.scheduling.generate_job_store import job_snapshot
    from app.services.scheduling.generate_jobs import get_job, restore_job

    job = get_job(job_id)
    if job is None:
        durable = await session.get(SchedulingGenerateJob, job_id)
        if durable is not None and durable.tenant_id == tenant_id:
            job = restore_job(job_snapshot(durable))
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="生成任务不存在")

    async def event_stream():
        queue = job.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # 无事件时仍检查心跳，Worker 异常退出后让订阅端得到明确失败。
                    get_job(job_id)
                    # 注释行保活，逼代理/浏览器冲刷缓冲，避免进度停在前几秒
                    yield ": keepalive\n\n"
                    continue
                payload = json.dumps(event, ensure_ascii=False)
                yield "event: " + event["type"] + "\ndata: " + payload + "\n\n"
                if event.get("type") in {"done", "error"}:
                    break
        finally:
            job.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    try:
        history_config = (await session.execute(select(TenantConfig).where(
            TenantConfig.tenant_id == tenant_id,
            TenantConfig.config_key == "scheduling_version_history",
        ))).scalars().first()
        raw = history_config.config_value if history_config else None
        # 兼容历史误存成 {"versions": [...]} 的形态
        if isinstance(raw, list):
            history_list = [v for v in raw if isinstance(v, dict)]
        elif isinstance(raw, dict) and isinstance(raw.get("versions"), list):
            history_list = [v for v in raw["versions"] if isinstance(v, dict)]
        else:
            history_list = []
        summary = []
        for idx, item in enumerate(history_list):
            saved_at = str(item.get("saved_at") or "")
            saved_label = saved_at[:19].replace("T", " ") if saved_at else "未知时间"
            version_number = item.get("version_number", idx + 1)
            class_ids = item.get("class_ids") or []
            items = item.get("items") or []
            summary.append({
                "version_id": item.get("version_id"),
                "saved_at": item.get("saved_at"),
                "academic_year": item.get("academic_year"),
                "term": item.get("term"),
                "class_count": item.get("class_count", len(class_ids) if isinstance(class_ids, list) else 0),
                "lesson_count": item.get("lesson_count", len(items) if isinstance(items, list) else 0),
                "label": f"版本 {version_number} · {saved_label}",
            })
        return {"code": 0, "message": "ok", "data": summary}
    except Exception as exc:  # noqa: BLE001 — 版本列表非主路径，避免拖垮课表页
        logger.exception("list_schedule_versions failed: %s", exc)
        return {"code": 0, "message": "ok", "data": []}


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
    raw_history = history_config.config_value if history_config else None
    if isinstance(raw_history, list):
        history_list = [v for v in raw_history if isinstance(v, dict)]
    elif isinstance(raw_history, dict) and isinstance(raw_history.get("versions"), list):
        history_list = [v for v in raw_history["versions"] if isinstance(v, dict)]
    else:
        history_list = []
    target = next((v for v in history_list if int(v.get("version_id") or 0) == int(version_id)), None)
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


async def _load_rule_catalog(
    session: AsyncSession,
    tenant_id: int,
    academic_year: str,
    term: str,
) -> tuple[list[RuleGroupDocument], str | None]:
    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == SCHEDULING_RULE_GROUP_CONFIG_KEY,
    ))).scalars().first()
    saved = row.config_value if row and isinstance(row.config_value, dict) else {}
    value = saved.get(f"{academic_year}:{term}")
    if not isinstance(value, dict):
        return [], None
    return parse_stored_rule_groups(value)


async def _load_rule_group(
    session: AsyncSession,
    tenant_id: int,
    academic_year: str,
    term: str,
    *,
    group_id: str | None = None,
    grade_id: int | None = None,
) -> RuleGroupDocument | None:
    groups, active_id = await _load_rule_catalog(session, tenant_id, academic_year, term)
    return pick_rule_group(groups, group_id=group_id, grade_id=grade_id, active_id=active_id)


async def _resolve_generation_rule_group(
    session: AsyncSession,
    tenant_id: int,
    body: GenerateIn,
) -> RuleGroupDocument | None:
    groups, active_id = await _load_rule_catalog(session, tenant_id, body.academic_year, body.term)
    class_grade_ids: set[int] = set()
    if body.class_ids:
        rows = list((await session.execute(select(Class.grade_id).where(
            Class.tenant_id == tenant_id,
            Class.id.in_(body.class_ids),
        ))).all())
        class_grade_ids = {int(grade_id) for (grade_id,) in rows if grade_id is not None}
    shared_grade_id = next(iter(class_grade_ids)) if len(class_grade_ids) == 1 else None
    group = pick_rule_group(
        groups,
        group_id=body.rule_group_id,
        grade_id=None if body.rule_group_id else shared_grade_id,
        active_id=active_id,
    )
    if body.rule_group_id and group is None:
        raise HTTPException(status_code=422, detail="未找到所选综合规则")
    if (
        group is not None
        and group.grade_id is not None
        and class_grade_ids
        and class_grade_ids != {group.grade_id}
    ):
        raise HTTPException(status_code=422, detail="所选班级与综合规则关联的年级不一致")
    return group


async def _persist_rule_catalog(
    session: AsyncSession,
    tenant_id: int,
    user_id: int,
    academic_year: str,
    term: str,
    groups: list[RuleGroupDocument],
    active_id: str | None,
) -> None:
    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == SCHEDULING_RULE_GROUP_CONFIG_KEY,
    ))).scalars().first()
    config = _rule_group_config(row)
    config[f"{academic_year}:{term}"] = dump_stored_rule_groups(groups, active_id)
    if row is None:
        session.add(TenantConfig(
            tenant_id=tenant_id,
            config_key=SCHEDULING_RULE_GROUP_CONFIG_KEY,
            config_value=config,
            updated_by=user_id,
        ))
    else:
        row.config_value = config
        row.updated_by = user_id
        row.updated_at = datetime.utcnow()


def _rule_group_config(
    row: TenantConfig | None,
) -> dict[str, dict]:
    if row is None or not isinstance(row.config_value, dict):
        return {}
    return {
        str(key): value
        for key, value in row.config_value.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


@router.get("/rule-groups", summary="查询学年学期下全部综合规则组")
async def list_rule_groups(
    academic_year: str,
    term: str = "1",
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    groups, active_id = await _load_rule_catalog(session, tenant_id, academic_year, term)
    return {"code": 0, "message": "ok", "data": {
        "catalog_version": 2,
        "active_id": active_id,
        "groups": [item.model_dump(mode="json") for item in groups],
    }}


@router.put("/rule-groups", summary="保存学年学期综合规则组目录")
async def save_rule_groups(
    body: RuleGroupCatalogIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    try:
        compiled = [item for group in body.groups for item in compile_rule_group(group)]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    active_id = body.active_id or (body.groups[0].id if body.groups else None)
    await _persist_rule_catalog(
        session, tenant_id, user.id, body.academic_year, body.term, body.groups, active_id,
    )
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "catalog_version": 2,
        "active_id": active_id,
        "groups": [item.model_dump(mode="json") for item in body.groups],
        "compiler": [item.model_dump() for item in compiled],
    }}


@router.get("/rule-group", summary="查询结构化排课规则组")
async def rule_group(
    academic_year: str,
    term: str = "1",
    grade_id: int | None = None,
    group_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    group = await _load_rule_group(
        session, tenant_id, academic_year, term, group_id=group_id, grade_id=grade_id,
    )
    return {"code": 0, "message": "ok", "data": group.model_dump(mode="json") if group else None}


@router.put("/rule-group", summary="保存结构化排课规则组")
async def save_rule_group(
    group: RuleGroupDocument,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    try:
        compiled = compile_rule_group(group)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    groups, active_id = await _load_rule_catalog(
        session, tenant_id, group.academic_year, group.term,
    )
    replaced = False
    next_groups: list[RuleGroupDocument] = []
    for item in groups:
        if item.id == group.id:
            if group.grade_id is None and item.grade_id is not None:
                group = group.model_copy(update={"grade_id": item.grade_id})
            next_groups.append(group)
            replaced = True
        else:
            next_groups.append(item)
    if not replaced:
        next_groups.append(group)
    await _persist_rule_catalog(
        session, tenant_id, user.id, group.academic_year, group.term, next_groups, group.id,
    )
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "group": group.model_dump(mode="json"),
        "compiler": [item.model_dump() for item in compiled],
    }}


@router.post("/rule-group/apply-suggestion", summary="应用生成失败诊断建议到综合规则")
async def apply_rule_suggestion(
    body: ApplySuggestionIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    group = await _load_rule_group(
        session,
        tenant_id,
        body.academic_year,
        body.term,
        group_id=body.group_id,
    )
    if group is None:
        raise HTTPException(status_code=404, detail="未找到综合规则")
    try:
        updated, note = apply_suggestion_to_group(group, body.suggestion)
        compiled = compile_rule_group(updated)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    groups, active_id = await _load_rule_catalog(
        session, tenant_id, body.academic_year, body.term,
    )
    next_groups = [updated if item.id == updated.id else item for item in groups]
    if not any(item.id == updated.id for item in next_groups):
        next_groups.append(updated)
    await _persist_rule_catalog(
        session,
        tenant_id,
        user.id,
        body.academic_year,
        body.term,
        next_groups,
        active_id or updated.id,
    )
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "note": note,
        "group": updated.model_dump(mode="json"),
        "compiler": [item.model_dump() for item in compiled],
    }}


@router.post("/rule-group/validate", summary="校验结构化排课规则组")
async def validate_rule_group(
    body: RuleGroupValidationIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    group = normalize_legacy_rule_group(body.group)
    grid = await _load_grid_config(session, tenant_id, group.academic_year, group.term)
    schedule_items: list[ScheduleItem] = []
    if body.use_current_schedule:
        rows = list((await session.execute(select(Schedule).where(
            Schedule.tenant_id == tenant_id,
            Schedule.academic_year == group.academic_year,
            Schedule.term == group.term,
        ))).scalars().all())
        schedule_items = [schedule_item_from_row(row) for row in rows]
    class_head_teacher_ids: dict[int, int | None] = {}
    if schedule_items:
        class_head_teacher_ids = {
            int(class_id): head_teacher_id
            for class_id, head_teacher_id in (
                await session.execute(
                    select(Class.id, Class.head_teacher_id).where(
                        Class.tenant_id == tenant_id,
                        Class.id.in_({item.class_id for item in schedule_items}),
                    )
                )
            ).all()
        }
    try:
        result = evaluate_rule_group(
            group,
            schedule_items,
            schedule_available=body.use_current_schedule and bool(schedule_items),
            evening_start_period=grid.get("evening_start_period"),
            class_head_teacher_ids=class_head_teacher_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": result.model_dump(mode="json")}


@router.post("/verify-schedule", summary="对已保存课表做综合规则反向校验")
async def verify_schedule(
    body: VerifyScheduleIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    grade_id = body.grade_id
    if grade_id is None and body.class_id is not None:
        grade_id = (
            await session.execute(
                select(Class.grade_id).where(
                    Class.tenant_id == tenant_id,
                    Class.id == body.class_id,
                )
            )
        ).scalar_one_or_none()
        if grade_id is None:
            raise HTTPException(status_code=404, detail="未找到所选班级")
        grade_id = int(grade_id) if grade_id is not None else None

    groups, active_id = await _load_rule_catalog(
        session, tenant_id, body.academic_year, body.term,
    )
    group = pick_rule_group(
        groups,
        group_id=body.rule_group_id,
        grade_id=grade_id,
        active_id=active_id,
    )
    if group is None:
        raise HTTPException(status_code=422, detail="未找到可匹配的综合规则，请先在「建立规则」中配置")

    grade_class_ids: set[int] = set()
    if group.grade_id is not None:
        grade_class_ids = {
            int(cid)
            for (cid,) in (
                await session.execute(
                    select(Class.id).where(
                        Class.tenant_id == tenant_id,
                        Class.grade_id == group.grade_id,
                    )
                )
            ).all()
        }

    schedule_stmt = select(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year,
        Schedule.term == body.term,
    )
    if grade_class_ids:
        schedule_stmt = schedule_stmt.where(Schedule.class_id.in_(grade_class_ids))
    rows = list((await session.execute(schedule_stmt)).scalars().all())
    schedule_items = [schedule_item_from_row(row) for row in rows]
    if not schedule_items:
        raise HTTPException(status_code=422, detail="当前年级尚无已保存课表，请先生成课表后再校验")

    class_ids = {item.class_id for item in schedule_items}
    class_head_teacher_ids = {
        int(class_id): head_teacher_id
        for class_id, head_teacher_id in (
            await session.execute(
                select(Class.id, Class.head_teacher_id).where(
                    Class.tenant_id == tenant_id,
                    Class.id.in_(class_ids),
                )
            )
        ).all()
    }
    grid = await _load_grid_config(session, tenant_id, body.academic_year, body.term)
    try:
        result = evaluate_rule_group(
            normalize_legacy_rule_group(group),
            schedule_items,
            schedule_available=True,
            evening_start_period=grid.get("evening_start_period"),
            class_head_teacher_ids=class_head_teacher_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    hard_failures = blocking_rule_results(result)
    soft_failures = [
        item for item in result.results
        if item.priority == "soft" and item.status == "fail"
    ]
    return {"code": 0, "message": "ok", "data": {
        "rule_group_id": group.id,
        "rule_group_name": group.name,
        "grade_id": group.grade_id,
        "class_count": len(class_ids),
        "hard_failure_count": len(hard_failures),
        "soft_failure_count": len(soft_failures),
        "validation": result.model_dump(mode="json"),
    }}


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
    validation_body = body
    if (body.max_same_subject_per_day or 0) <= 1:
        # 与生成一致：数学连堂需要某天 2 节，容量按每日最多 2 估算
        validation_body = body.model_copy(update={"max_same_subject_per_day": 2})
    result = _validate_generation(
        assignments,
        validation_body,
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
    configured = bool(stored_scope)
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
    if value["enable_evening"]:
        start = value.get("evening_start_period")
        if not start or int(start) <= int(value["periods_per_day"]):
            value["evening_start_period"] = int(value["periods_per_day"]) + 1
    else:
        value["evening_start_period"] = None
    if isinstance(value.get("term_start_monday"), str):
        value["term_start_monday"] = date.fromisoformat(value["term_start_monday"])
    value["configured"] = configured
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
    subject_ids = {row.subject_id for row in rows if row.subject_id}
    teacher_ids = {row.teacher_id for row in rows if row.teacher_id}
    subject_names = {
        sid: name for sid, name in (await session.execute(
            select(Subject.id, Subject.name).where(Subject.id.in_(subject_ids))
        )).all()
    } if subject_ids else {}
    teacher_names = {
        tid: name for tid, name in (await session.execute(
            select(User.id, User.name).where(User.id.in_(teacher_ids))
        )).all()
    } if teacher_ids else {}
    options = []
    for weekday, period, parity in _iter_adjustment_targets(
        source=source,
        days=days,
        periods_per_day=periods_per_day,
        grid=grid,
    ):
        evaluated = _evaluate_move_or_swap(
            rows,
            source=source,
            target_weekday=weekday,
            target_period=period,
            target_parity=parity,
            grid=grid,
            subject_names=subject_names,
            teacher_names=teacher_names,
        )
        if teaching_relation is None:
            relation_check = _check("teaching_relation", "教师已配置该班该学科任教关系", False)
            evaluated["checks"] = [relation_check, *evaluated.get("checks", [])]
            evaluated["available"] = False
            evaluated["selectable"] = False
            evaluated["reason"] = "教师未配置该班该学科的任教关系"
        options.append({
            "weekday": weekday,
            "period": period,
            "week_parity": parity.value,
            "available": evaluated["available"],
            "selectable": evaluated.get("selectable", evaluated["available"]),
            "reason": evaluated["reason"],
            "mode": evaluated["mode"],
            "checks": evaluated.get("checks", []),
            "swap_schedule_id": evaluated["swap_schedule_id"],
            "swap_with_subject": evaluated["swap_with_subject"],
            "swap_with_teacher": evaluated["swap_with_teacher"],
        })
    return {"code": 0, "message": "ok", "data": options}


@router.post("/adjustments/preview", summary="预览调课/对调检查项")
async def preview_schedule_adjustment(
    body: ScheduleAdjustPreviewIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    grid = await _load_grid_config(session, tenant_id, body.academic_year, body.term)
    days = body.days if body.days is not None else grid["days"]
    periods_per_day = body.periods_per_day if body.periods_per_day is not None else grid["periods_per_day"]
    evening_start = grid.get("evening_start_period") if grid.get("enable_evening") else None
    max_period = max(periods_per_day, int(evening_start or 0))
    if body.target_weekday > days or body.target_period > max_period:
        raise HTTPException(status_code=422, detail="目标时段不在当前排课规则范围内")
    source = (await session.execute(select(Schedule).where(
        Schedule.id == body.schedule_id,
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year,
        Schedule.term == body.term,
    ))).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="课表记录不存在")
    rows = list((await session.execute(select(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year,
        Schedule.term == body.term,
    ))).scalars().all())
    subject_ids = {row.subject_id for row in rows if row.subject_id}
    teacher_ids = {row.teacher_id for row in rows if row.teacher_id}
    subject_names = {
        sid: name for sid, name in (await session.execute(
            select(Subject.id, Subject.name).where(Subject.id.in_(subject_ids))
        )).all()
    } if subject_ids else {}
    teacher_names = {
        tid: name for tid, name in (await session.execute(
            select(User.id, User.name).where(User.id.in_(teacher_ids))
        )).all()
    } if teacher_ids else {}
    target_parity = body.target_week_parity or WeekParity(source.week_parity)
    evaluated = _evaluate_move_or_swap(
        rows,
        source=source,
        target_weekday=body.target_weekday,
        target_period=body.target_period,
        target_parity=target_parity,
        grid=grid,
        subject_names=subject_names,
        teacher_names=teacher_names,
    )
    if not evaluated.get("selectable", False):
        raise HTTPException(status_code=409, detail=evaluated.get("reason") or "目标时段不可调")
    rule_checks = await _rule_checks_after_adjustment(
        session,
        tenant_id=tenant_id,
        academic_year=body.academic_year,
        term=body.term,
        rows=rows,
        source=source,
        target_weekday=body.target_weekday,
        target_period=body.target_period,
        target_parity=target_parity,
        swap_schedule_id=evaluated.get("swap_schedule_id"),
        class_id=source.class_id,
    )
    checks = [*evaluated.get("checks", []), *rule_checks]
    failed = [item["label"] for item in checks if not item["passed"]]
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "weekday": body.target_weekday,
            "period": body.target_period,
            "week_parity": target_parity.value,
            "mode": evaluated["mode"],
            "available": not failed,
            "selectable": True,
            "reason": "；".join(failed) if failed else evaluated["reason"],
            "checks": checks,
            "swap_schedule_id": evaluated["swap_schedule_id"],
            "swap_with_subject": evaluated["swap_with_subject"],
            "swap_with_teacher": evaluated["swap_with_teacher"],
        },
    }


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
    evening_start = grid.get("evening_start_period") if grid.get("enable_evening") else None
    max_period = max(periods_per_day, int(evening_start or 0))
    if body.target_weekday > days or body.target_period > max_period:
        raise HTTPException(status_code=422, detail="目标时段不在当前排课规则范围内")
    rows = list((await session.execute(select(Schedule).where(
        Schedule.tenant_id == tenant_id,
        Schedule.academic_year == body.academic_year,
        Schedule.term == body.term,
    ))).scalars().all())
    subject_ids = {row.subject_id for row in rows if row.subject_id}
    teacher_ids = {row.teacher_id for row in rows if row.teacher_id}
    subject_names = {
        sid: name for sid, name in (await session.execute(
            select(Subject.id, Subject.name).where(Subject.id.in_(subject_ids))
        )).all()
    } if subject_ids else {}
    teacher_names = {
        tid: name for tid, name in (await session.execute(
            select(User.id, User.name).where(User.id.in_(teacher_ids))
        )).all()
    } if teacher_ids else {}
    target_parity = body.target_week_parity or WeekParity(source.week_parity)
    evaluated = _evaluate_move_or_swap(
        rows,
        source=source,
        target_weekday=body.target_weekday,
        target_period=body.target_period,
        target_parity=target_parity,
        grid=grid,
        subject_names=subject_names,
        teacher_names=teacher_names,
    )
    if not evaluated.get("selectable", False):
        raise HTTPException(status_code=409, detail=evaluated.get("reason") or "目标时段不可调")
    if not evaluated["available"] and not body.force:
        raise HTTPException(
            status_code=409,
            detail=evaluated["reason"] or "存在未通过检查项，请勾选确认后强制调整",
        )

    origin_weekday, origin_period = source.weekday, source.period
    origin_parity = WeekParity(source.week_parity)
    if evaluated["mode"] == "swap" and evaluated["swap_schedule_id"]:
        peer = next((row for row in rows if row.id == evaluated["swap_schedule_id"]), None)
        if peer is None:
            raise HTTPException(status_code=409, detail="对调目标课程不存在")
        # 唯一约束 (class, weekday, period, week_parity)：不能同时把 peer 写进源格。
        # 先把源课停到空闲临时格，再交换，最后落到目标。
        occupied = {
            (row.weekday, row.period, WeekParity(row.week_parity))
            for row in rows
            if row.class_id == source.class_id
        }
        park_weekday, park_period, park_parity = 7, 99, WeekParity.all
        for wd in range(1, 8):
            for pd in range(1, 100):
                for pr in (WeekParity.all, WeekParity.odd, WeekParity.even):
                    key = (wd, pd, pr)
                    if key not in occupied:
                        park_weekday, park_period, park_parity = wd, pd, pr
                        break
                else:
                    continue
                break
            else:
                continue
            break
        source.weekday = park_weekday
        source.period = park_period
        source.week_parity = park_parity
        await session.flush()
        peer.weekday = origin_weekday
        peer.period = origin_period
        peer.week_parity = origin_parity
        await session.flush()
        source.weekday = body.target_weekday
        source.period = body.target_period
        source.week_parity = target_parity
        await session.commit()
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "id": source.id,
                "weekday": source.weekday,
                "period": source.period,
                "week_parity": source.week_parity.value if isinstance(source.week_parity, WeekParity) else source.week_parity,
                "mode": "swap",
                "forced": bool(body.force and not evaluated["available"]),
                "swap_schedule_id": peer.id,
                "swap_with_subject": evaluated["swap_with_subject"],
                "swap_with_teacher": evaluated["swap_with_teacher"],
            },
        }

    source.weekday = body.target_weekday
    source.period = body.target_period
    source.week_parity = target_parity
    await session.commit()
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "id": source.id,
            "weekday": source.weekday,
            "period": source.period,
            "week_parity": source.week_parity.value if isinstance(source.week_parity, WeekParity) else source.week_parity,
            "mode": "move",
            "forced": bool(body.force and not evaluated["available"]),
        },
    }
