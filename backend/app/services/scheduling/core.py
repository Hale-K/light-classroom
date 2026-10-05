"""排课与排座的纯算法。

算法不依赖数据库，便于用单元测试验证硬约束。API 层只负责加载数据和持久化结果。
"""
from dataclasses import dataclass, replace
from datetime import date, timedelta
import random
from typing import Any, Iterable, Mapping
from collections import defaultdict

from app.models.enums import EveningParity, WeekParity
from app.services.scheduling.blocks import repair_consecutive_blocks
from app.services.scheduling.strategies import CandidateContext, build_schedule_strategy


def select_invigilator_ids(users: Iterable[Any]) -> list[int]:
    """Return every active school teacher, independent of the examined grade."""
    return [
        user.id for user in users
        if getattr(getattr(user, 'role', None), 'value', getattr(user, 'role', None)) == 'teacher'
        and getattr(getattr(user, 'status', None), 'value', getattr(user, 'status', None)) == 'active'
    ]


def resolve_exam_room_status(
    resource_status: str,
    *,
    selected: bool = False,
    scheduled_dates: Iterable[date] = (),
    today: date | None = None,
) -> str:
    """Resolve the visible room state from resource state and exam progress."""
    if resource_status in {'maintenance', 'disabled'}:
        return resource_status
    dates = sorted(set(scheduled_dates))
    current = today or date.today()
    if current in dates:
        return 'ongoing'
    if dates and dates[-1] < current:
        return 'completed'
    if dates:
        return 'scheduled'
    return 'selected' if selected else 'available'


def parity_conflicts(left: WeekParity | str, right: WeekParity | str) -> bool:
    """Return whether two week-parity lessons cannot occupy the same slot."""
    left_value = WeekParity(left)
    right_value = WeekParity(right)
    return WeekParity.all in {left_value, right_value} or left_value == right_value


def evening_parity_mode(row: Mapping[str, Any]) -> str:
    """晚课周次：显式 evening_parity 优先；旧数据才用白天 week_parity 推断。"""
    raw = row.get("evening_parity")
    if raw not in (None, ""):
        return raw.value if isinstance(raw, EveningParity) else str(raw)
    odd = max(0, int(row.get("evening_periods_odd") or 0))
    even = max(0, int(row.get("evening_periods_even") or 0))
    plan = row.get("week_parity", WeekParity.all.value)
    plan = plan.value if isinstance(plan, WeekParity) else str(plan)
    if odd and even:
        return EveningParity.either.value if plan != WeekParity.all.value else EveningParity.all.value
    if odd:
        return EveningParity.odd.value
    if even:
        return EveningParity.even.value
    return EveningParity.all.value


def evening_is_flex_half(row: Mapping[str, Any]) -> bool:
    """0.5 晚课且单双无规定：只占单周或双周其中一侧。"""
    odd = max(0, int(row.get("evening_periods_odd") or 0))
    even = max(0, int(row.get("evening_periods_even") or 0))
    return odd > 0 and even > 0 and evening_parity_mode(row) == EveningParity.either.value


def plan_evening_count_for_parity(row: Mapping[str, Any], parity: WeekParity) -> int:
    """某课在指定单双周上的晚课额度；无规定时两侧都可排，但求解时只占一侧。"""
    mode = evening_parity_mode(row)
    if mode == EveningParity.either.value:
        return 1
    if mode in {EveningParity.odd.value, EveningParity.even.value}:
        return 1 if mode == parity.value else 0
    field = "evening_periods_odd" if parity is WeekParity.odd else "evening_periods_even"
    return max(0, int(row.get(field) or 0))


def has_scheduled_hours(assignment: Mapping[str, Any]) -> bool:
    """Return whether an assignment has any daytime or evening lesson volume."""
    has_split = "weekday_periods" in assignment or "saturday_periods" in assignment
    if has_split:
        daytime_hours = float(assignment.get("weekday_periods", 0) or 0) + float(
            assignment.get("saturday_periods", 0) or 0
        )
    else:
        daytime_hours = float(assignment.get("weekly_periods", 0) or 0)
    evening_hours = float(assignment.get("evening_periods_odd", 0) or 0) + float(
        assignment.get("evening_periods_even", 0) or 0
    )
    return daytime_hours > 0 or evening_hours > 0


def filter_zero_hour_assignments(
    assignments: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Exclude assignments with no daytime and no odd/even evening volume."""
    return [dict(assignment) for assignment in assignments if has_scheduled_hours(assignment)]


def occupancy_keys(
    owner_id: int,
    weekday: int,
    period: int,
    parity: WeekParity | str,
) -> list[tuple[int, int, int, str]]:
    """Expand an all-week lesson into both odd and even occupancy legs."""
    value = WeekParity(parity)
    legs = (WeekParity.odd, WeekParity.even) if value is WeekParity.all else (value,)
    return [(owner_id, weekday, period, leg.value) for leg in legs]


def find_schedule_conflicts(items: Iterable["ScheduleItem"]) -> list[dict[str, Any]]:
    """Return hard class/teacher collisions using the actual odd/even week legs."""
    seen: dict[tuple[str, int, int, int, str], ScheduleItem] = {}
    conflicts: list[dict[str, Any]] = []
    for item in items:
        owners = [("class", item.class_id)]
        if item.teacher_id is not None:
            owners.append(("teacher", item.teacher_id))
        for owner_type, owner_id in owners:
            for _, weekday, period, leg in occupancy_keys(
                owner_id, item.weekday, item.period, item.week_parity,
            ):
                key = (owner_type, owner_id, weekday, period, leg)
                previous = seen.get(key)
                if previous is not None:
                    conflicts.append({
                        "type": owner_type,
                        "entity_id": owner_id,
                        "weekday": weekday,
                        "period": period,
                        "week_parity": leg,
                        "assignment_ids": [previous.assignment_id, item.assignment_id],
                    })
                else:
                    seen[key] = item
    return conflicts


@dataclass(frozen=True)
class ScheduleItem:
    assignment_id: int
    class_id: int
    subject_id: int
    teacher_id: int | None
    weekday: int
    period: int
    room: str | None = None
    week_parity: WeekParity = WeekParity.all


@dataclass(frozen=True)
class DatedScheduleItem(ScheduleItem):
    lesson_date: date = date.min


@dataclass(frozen=True)
class ScheduleResult:
    items: list[ScheduleItem]
    unplaced: list[dict[str, int | float]]
    staffing_issues: list[dict[str, int]]


@dataclass(frozen=True)
class ScheduleValidationSuggestion:
    code: str
    label: str
    field: str
    recommended_value: int
    reason: str
    tradeoff: str


@dataclass(frozen=True)
class ScheduleRuleExplanation:
    code: str
    label: str
    formula: str
    result: int
    description: str


@dataclass(frozen=True)
class ScheduleValidationIssue:
    code: str
    message: str
    entity_type: str
    entity_id: int
    requested: int | float
    capacity: int | float
    related_id: int | None = None
    severity: str = "error"
    rule_code: str | None = None
    formula: str | None = None
    suggestions: tuple[ScheduleValidationSuggestion, ...] = ()


@dataclass(frozen=True)
class ScheduleValidationResult:
    valid: bool
    issues: list[ScheduleValidationIssue]
    assignment_count: int
    requested_lessons: int | float
    available_slots: int
    rules: tuple[ScheduleRuleExplanation, ...] = ()


@dataclass(frozen=True)
class SeatItem:
    row: int
    col: int
    student_id: int


@dataclass(frozen=True)
class ExamScheduleItem:
    paper_id: int
    subject_id: int
    grade_id: int
    exam_date: date
    session_index: int
    start_time: str
    end_time: str
    invigilator_id: int | None
    room: str
    paper_teacher_id: int | None = None


@dataclass(frozen=True)
class ExamRoomResource:
    name: str
    capacity: int


def normalize_exam_room_resources(
    rooms: Iterable[ExamRoomResource],
) -> list[ExamRoomResource]:
    """Normalize a confirmed venue list and reject ambiguous duplicate names."""
    result: list[ExamRoomResource] = []
    seen: set[str] = set()
    for room in rooms:
        name = room.name.strip()
        if not name:
            raise ValueError("考场名称不能为空")
        if name in seen:
            raise ValueError(f"考场名称重复：{name}")
        if room.capacity < 1:
            raise ValueError(f"考场容量必须大于 0：{name}")
        seen.add(name)
        result.append(ExamRoomResource(name=name, capacity=room.capacity))
    if not result:
        raise ValueError("请至少创建或选择一个考场")
    return result


@dataclass(frozen=True)
class ExamRoomAssignment:
    paper_id: int
    subject_id: int
    grade_id: int
    exam_date: date
    session_index: int
    room_name: str
    capacity: int
    candidate_count: int
    invigilator_ids: tuple[int, ...]


@dataclass(frozen=True)
class ExamCandidateSeat:
    paper_id: int
    subject_id: int
    grade_id: int
    student_id: int
    exam_date: date
    session_index: int
    start_time: str
    end_time: str
    room_name: str
    seat_no: int


@dataclass(frozen=True)
class ExamArrangementResult:
    rooms: list[ExamRoomAssignment]
    seats: list[ExamCandidateSeat]


@dataclass(frozen=True)
class ExamTemplateSlot:
    day_index: int
    session_index: int
    start_time: str
    end_time: str
    subject_names: frozenset[str]


class ExamScheduleStrategy:
    mode: str
    slots: tuple[ExamTemplateSlot, ...] = ()

    def build(
        self,
        papers: list[dict[str, Any]],
        *,
        start_date: date,
        teacher_ids: list[int],
        sessions: tuple[tuple[str, str], ...],
        room: str,
        excluded_dates: set[date],
        subject_names: Mapping[int, str],
    ) -> list[ExamScheduleItem]:
        raise NotImplementedError


_EXAM_SCHEDULE_STRATEGIES: dict[str, ExamScheduleStrategy] = {}


def register_exam_schedule_strategy(strategy_type: type[ExamScheduleStrategy]):
    strategy = strategy_type()
    if strategy.mode in _EXAM_SCHEDULE_STRATEGIES:
        raise RuntimeError(f"排考策略重复注册: {strategy.mode}")
    _EXAM_SCHEDULE_STRATEGIES[strategy.mode] = strategy
    return strategy_type


def get_exam_schedule_strategy(mode: str) -> ExamScheduleStrategy:
    try:
        return _EXAM_SCHEDULE_STRATEGIES[mode]
    except KeyError as exc:
        raise ValueError(f"不支持的高考排考模式: {mode}") from exc


def _available_exam_days(start_date: date, count: int, excluded_dates: set[date]) -> list[date]:
    days: list[date] = []
    current = start_date
    while len(days) < count:
        if current.weekday() < 5 and current not in excluded_dates:
            days.append(current)
        current += timedelta(days=1)
    return days


def _paper_invigilator(paper: Mapping[str, Any], teacher_ids: list[int], offset: int) -> int | None:
    paper_teacher = paper.get("teacher_id")
    for index in range(len(teacher_ids)):
        candidate = teacher_ids[(offset + index) % len(teacher_ids)]
        if candidate != paper_teacher:
            return candidate
    return None


class _TemplateExamScheduleStrategy(ExamScheduleStrategy):
    def build(
        self,
        papers: list[dict[str, Any]],
        *,
        start_date: date,
        teacher_ids: list[int],
        sessions: tuple[tuple[str, str], ...],
        room: str,
        excluded_dates: set[date],
        subject_names: Mapping[int, str],
    ) -> list[ExamScheduleItem]:
        del sessions
        slot_by_subject = {
            subject_name: slot
            for slot in self.slots
            for subject_name in slot.subject_names
        }
        exam_days = _available_exam_days(
            start_date,
            max(slot.day_index for slot in self.slots) + 1,
            excluded_dates,
        )
        result: list[ExamScheduleItem] = []
        for paper_index, paper in enumerate(papers):
            subject_name = subject_names.get(int(paper["subject_id"]), "")
            slot = slot_by_subject.get(subject_name)
            if slot is None:
                raise ValueError(f"{subject_name or '未知学科'}未配置在{self.mode}高考排考模板中")
            result.append(ExamScheduleItem(
                paper_id=int(paper["id"]),
                subject_id=int(paper["subject_id"]),
                grade_id=int(paper["grade_id"]),
                exam_date=exam_days[slot.day_index],
                session_index=slot.session_index,
                start_time=slot.start_time,
                end_time=slot.end_time,
                invigilator_id=_paper_invigilator(paper, teacher_ids, paper_index),
                room=str(paper.get("room") or room),
                paper_teacher_id=paper.get("teacher_id"),
            ))
        return sorted(result, key=lambda item: (
            item.exam_date, item.session_index, item.grade_id, item.subject_id, item.paper_id,
        ))


@register_exam_schedule_strategy
class ThreeOneTwoExamScheduleStrategy(_TemplateExamScheduleStrategy):
    mode = "3+1+2"
    slots = (
        ExamTemplateSlot(0, 1, "09:00", "11:30", frozenset({"语文"})),
        ExamTemplateSlot(0, 2, "15:00", "17:00", frozenset({"数学"})),
        ExamTemplateSlot(1, 3, "09:00", "10:15", frozenset({"物理", "历史"})),
        ExamTemplateSlot(1, 4, "15:00", "17:00", frozenset({"英语", "外语"})),
        ExamTemplateSlot(2, 5, "08:30", "09:45", frozenset({"化学"})),
        ExamTemplateSlot(2, 6, "11:00", "12:15", frozenset({"地理"})),
        ExamTemplateSlot(2, 7, "14:30", "15:45", frozenset({"政治", "思想政治"})),
        ExamTemplateSlot(2, 8, "17:00", "18:15", frozenset({"生物", "生物学"})),
    )


@register_exam_schedule_strategy
class ThreePlusThreeExamScheduleStrategy(_TemplateExamScheduleStrategy):
    mode = "3+3"
    slots = (
        ExamTemplateSlot(0, 1, "09:00", "11:30", frozenset({"语文"})),
        ExamTemplateSlot(0, 2, "15:00", "17:00", frozenset({"数学"})),
        ExamTemplateSlot(1, 3, "15:00", "17:00", frozenset({"英语", "外语"})),
        ExamTemplateSlot(2, 4, "08:30", "10:00", frozenset({"物理"})),
        ExamTemplateSlot(2, 5, "11:00", "12:30", frozenset({"政治", "思想政治"})),
        ExamTemplateSlot(2, 6, "15:00", "16:30", frozenset({"化学"})),
        ExamTemplateSlot(3, 7, "08:30", "10:00", frozenset({"历史"})),
        ExamTemplateSlot(3, 8, "11:00", "12:30", frozenset({"生物", "生物学"})),
        ExamTemplateSlot(3, 9, "15:00", "16:30", frozenset({"地理"})),
    )


def validate_schedule_requirements(
    assignments: Iterable[dict[str, Any]],
    *,
    days: int = 5,
    periods_per_day: int = 8,
    forbidden_slots: set[tuple[int, int]] | None = None,
    max_class_lessons_per_day: int | None = None,
    max_teacher_lessons_per_day: int | None = None,
    max_class_lessons_on_saturday: int | None = None,
    max_teacher_lessons_on_saturday: int | None = None,
    max_same_subject_per_day: int | None = None,
    require_full_week: bool = False,
    max_teacher_weekly_periods: int | None = None,
) -> ScheduleValidationResult:
    """在运行排课算法前检查班级、教师和学科课时是否超过可用容量。"""
    if not 1 <= days <= 7 or not 1 <= periods_per_day <= 12:
        raise ValueError("教学日或每日节次数量不合法")
    rows = [dict(item) for item in assignments]
    forbidden = forbidden_slots or set()
    available_by_day = {
        weekday: sum(
            (weekday, period) not in forbidden
            for period in range(1, periods_per_day + 1)
        )
        for weekday in range(1, days + 1)
    }
    def daily_limit(weekday: int, weekday_limit: int | None, saturday_limit: int | None) -> int | None:
        return saturday_limit if weekday == 6 and saturday_limit is not None else weekday_limit

    class_capacity = sum(
        min(slots, limit) if (limit := daily_limit(
            weekday, max_class_lessons_per_day, max_class_lessons_on_saturday,
        )) is not None else slots
        for weekday, slots in available_by_day.items()
    )
    teacher_capacity = sum(
        min(slots, limit) if (limit := daily_limit(
            weekday, max_teacher_lessons_per_day, max_teacher_lessons_on_saturday,
        )) is not None else slots
        for weekday, slots in available_by_day.items()
    )
    subject_capacity = sum(
        min(slots, max_same_subject_per_day) if max_same_subject_per_day is not None else slots
        for slots in available_by_day.values()
    )

    def capacity_formula(limit: int | None, capacity: int, saturday_limit: int | None = None) -> str:
        active_days = [(weekday, slots) for weekday, slots in available_by_day.items() if slots > 0]
        contributions = [
            min(slots, day_limit) if (day_limit := daily_limit(weekday, limit, saturday_limit)) is not None else slots
            for weekday, slots in active_days
        ]
        if saturday_limit is None and limit is not None and active_days and all(slots >= limit for _, slots in active_days):
            return f"{len(active_days)} 个可排教学日 × 每日最多 {limit} 节 = {capacity} 节"
        return f"各可排教学日容量 {' + '.join(map(str, contributions)) or '0'} = {capacity} 节"

    def minimum_daily_limit(requested: int) -> int | None:
        for limit in range(1, periods_per_day + 1):
            if sum(min(slots, limit) for slots in available_by_day.values()) >= requested:
                return limit
        return None

    class_formula = capacity_formula(
        max_class_lessons_per_day, class_capacity, max_class_lessons_on_saturday,
    )
    teacher_formula = capacity_formula(
        max_teacher_lessons_per_day, teacher_capacity, max_teacher_lessons_on_saturday,
    )
    subject_formula = capacity_formula(max_same_subject_per_day, subject_capacity)
    rules = (
        ScheduleRuleExplanation(
            code="calendar_capacity",
            label="基础时段容量",
            formula=f"{days} 个教学日 × 每日 {periods_per_day} 节 - {len(forbidden)} 个禁排时段 = {sum(available_by_day.values())} 节",
            result=sum(available_by_day.values()),
            description="所有班级、教师和学科约束计算的基础时段池。",
        ),
        ScheduleRuleExplanation(
            code="max_class_lessons_per_day",
            label="单班周容量",
            formula=class_formula,
            result=class_capacity,
            description="一个班级在当前规则下每周最多能够安排的总课时。",
        ),
        ScheduleRuleExplanation(
            code="max_teacher_lessons_per_day",
            label="教师周容量",
            formula=teacher_formula,
            result=teacher_capacity,
            description="一名教师在当前规则下每周最多能够承担的总课时。",
        ),
        ScheduleRuleExplanation(
            code="max_same_subject_per_day",
            label="单班单科周容量",
            formula=subject_formula,
            result=subject_capacity,
            description="同一班级的同一学科受每日上限约束后的周容量。",
        ),
    )
    class_loads: dict[int, float] = {}
    teacher_loads: dict[int, float] = {}
    subject_loads: dict[tuple[int, int], float] = {}
    for item in rows:
        required = max(0.0, float(item.get("weekly_periods", 0) or 0))
        class_id = int(item["class_id"])
        subject_id = int(item["subject_id"])
        class_loads[class_id] = class_loads.get(class_id, 0) + required
        subject_key = (class_id, subject_id)
        subject_loads[subject_key] = subject_loads.get(subject_key, 0) + required
        if item.get("teacher_id") is not None and item.get("counts_toward_teacher_load", True):
            teacher_id = int(item["teacher_id"])
            teacher_loads[teacher_id] = teacher_loads.get(teacher_id, 0) + required

    issues: list[ScheduleValidationIssue] = []
    for class_id, requested in sorted(class_loads.items()):
        if require_full_week and requested < sum(available_by_day.values()):
            missing = sum(available_by_day.values()) - requested
            issues.append(ScheduleValidationIssue(
                code="class_weekly_load_incomplete",
                message=f"班级 {class_id} 当前配置 {requested} 节课，距离每周排满还缺少 {missing} 节",
                entity_type="class",
                entity_id=class_id,
                requested=requested,
                capacity=sum(available_by_day.values()),
                rule_code="require_full_week",
                formula=f"{sum(available_by_day.values())} 节满课位 - {requested} 节已配置 = {missing} 节缺口",
                suggestions=(ScheduleValidationSuggestion(
                    code="add_class_weekly_periods",
                    label=f"补充该班 {missing} 节学科周课时",
                    field="weekly_periods",
                    recommended_value=missing,
                    reason="当前要求每天 7 节正式课，空余课位不能由算法凭空生成课程。",
                    tradeoff="需要在任教关系中补充真实课程或校本课程。",
                ),),
            ))
        if requested > class_capacity:
            recommended_limit = minimum_daily_limit(requested)
            class_suggestion = (
                ScheduleValidationSuggestion(
                    code="increase_class_daily_limit",
                    label=f"将班级每日上限调整为 {recommended_limit} 节",
                    field="max_class_lessons_per_day",
                    recommended_value=recommended_limit,
                    reason="提升单班周容量，使总课时存在可行空间。",
                    tradeoff="班级个别教学日的课程会更密集。",
                ) if recommended_limit is not None else ScheduleValidationSuggestion(
                    code="reduce_class_weekly_load",
                    label=f"将班级总周课时降到 {sum(available_by_day.values())} 节以内，或增加教学时段",
                    field="class_total_weekly_periods",
                    recommended_value=sum(available_by_day.values()),
                    reason="即使每天排满，当前教学周也容纳不下全部课程，单纯放宽每日上限无效。",
                    tradeoff="需要重新核定各学科周课时，或增加教学日、晚自习等有效时段。",
                )
            )
            issues.append(ScheduleValidationIssue(
                code="class_capacity_exceeded",
                message=f"班级 {class_id} 需要 {requested} 节课，但当前条件最多可排 {class_capacity} 节",
                entity_type="class",
                entity_id=class_id,
                requested=requested,
                capacity=class_capacity,
                rule_code="max_class_lessons_per_day",
                formula=class_formula,
                suggestions=(class_suggestion,),
            ))
    for teacher_id, requested in sorted(teacher_loads.items()):
        if requested > teacher_capacity:
            recommended_limit = minimum_daily_limit(requested)
            teacher_suggestion = (
                ScheduleValidationSuggestion(
                    code="increase_teacher_daily_limit",
                    label=f"将教师每日上限调整为 {recommended_limit} 节",
                    field="max_teacher_lessons_per_day",
                    recommended_value=recommended_limit,
                    reason="提升该教师的周授课容量。",
                    tradeoff="教师个别教学日的连续授课压力可能增加；也可改配其他教师。",
                ) if recommended_limit is not None else ScheduleValidationSuggestion(
                    code="split_teacher_weekly_load",
                    label=f"将该教师周课时降到 {sum(available_by_day.values())} 节以内并增配教师",
                    field="teacher_total_weekly_periods",
                    recommended_value=sum(available_by_day.values()),
                    reason="即使所有时段都授课，当前教师仍无法承担全部任务。",
                    tradeoff="需要拆分任教关系或增加同学科师资。",
                )
            )
            issues.append(ScheduleValidationIssue(
                code="teacher_capacity_exceeded",
                message=f"教师 {teacher_id} 承担 {requested} 节课，但当前条件最多可排 {teacher_capacity} 节",
                entity_type="teacher",
                entity_id=teacher_id,
                requested=requested,
                capacity=teacher_capacity,
                rule_code="max_teacher_lessons_per_day",
                formula=teacher_formula,
                suggestions=(teacher_suggestion,),
            ))
        if max_teacher_weekly_periods is not None and requested > max_teacher_weekly_periods:
            issues.append(ScheduleValidationIssue(
                code="teacher_weekly_capacity_exceeded",
                message=f"教师 {teacher_id} 承担 {requested} 节课，超过每周上限 {max_teacher_weekly_periods} 节",
                entity_type="teacher",
                entity_id=teacher_id,
                requested=requested,
                capacity=max_teacher_weekly_periods,
                rule_code="max_teacher_weekly_periods",
                formula=f"{requested} 节 > 每周上限 {max_teacher_weekly_periods} 节",
                suggestions=(ScheduleValidationSuggestion(
                    code="split_teacher_weekly_load",
                    label=f"将该教师周课时降到 {max_teacher_weekly_periods} 节以内",
                    field="teacher_total_weekly_periods",
                    recommended_value=max_teacher_weekly_periods,
                    reason="超过教师每周课时上限，继续排课会有课无法安排。",
                    tradeoff="拆分任教关系给同学科其他教师，或在负荷上限中上调每周上限。",
                ),),
            ))
    for (class_id, subject_id), requested in sorted(subject_loads.items()):
        if requested > subject_capacity:
            recommended_limit = minimum_daily_limit(requested)
            subject_suggestions = []
            if recommended_limit is not None:
                subject_suggestions.append(ScheduleValidationSuggestion(
                    code="increase_subject_daily_limit",
                    label=f"将同科每日上限调整为 {recommended_limit} 节",
                    field="max_same_subject_per_day",
                    recommended_value=recommended_limit,
                    reason=f"当前需要 {requested} 节，提高每日上限后可形成足够的周容量。",
                    tradeoff="部分日期可能出现同一学科两节课；可由连续课策略进一步控制是否连排。",
                ))
            subject_suggestions.append(ScheduleValidationSuggestion(
                code="reduce_assignment_weekly_periods",
                label=f"将该任教关系周课时调整为 {subject_capacity} 节",
                field="weekly_periods",
                recommended_value=subject_capacity,
                reason="保持当前同科每日上限时，周课时不能超过当前单科容量。",
                tradeoff="会减少该学科教学总量，需要确认课程计划允许。",
            ))
            issues.append(ScheduleValidationIssue(
                code="subject_capacity_exceeded",
                message=f"班级 {class_id} 的学科 {subject_id} 需要 {requested} 节课，但当前条件最多可排 {subject_capacity} 节",
                entity_type="class_subject",
                entity_id=class_id,
                requested=requested,
                capacity=subject_capacity,
                related_id=subject_id,
                rule_code="max_same_subject_per_day",
                formula=subject_formula,
                suggestions=tuple(subject_suggestions),
            ))
    return ScheduleValidationResult(
        valid=not issues,
        issues=issues,
        assignment_count=len(rows),
        requested_lessons=sum(max(0.0, float(item.get("weekly_periods", 0) or 0)) for item in rows),
        available_slots=sum(available_by_day.values()),
        rules=rules,
    )


def _can_place_schedule_item(
    candidate: ScheduleItem,
    items: list[ScheduleItem],
    *,
    days: int,
    periods_per_day: int,
    forbidden_slots: set[tuple[int, int]],
    max_class_lessons_per_day: int | None,
    max_teacher_lessons_per_day: int | None,
    max_same_subject_per_day: int | None,
    avoid_consecutive_teacher_lessons: bool = False,
    teacher_daily_limits: dict[int, int] | None = None,
    max_teacher_lessons_on_saturday: int | None = None,
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    teacher_class_forbidden_slots: Mapping[tuple[int, int], set[tuple[int, int]]] | None = None,
    subject_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    ignored_index: int | None = None,
) -> bool:
    if not 1 <= candidate.weekday <= days or not 1 <= candidate.period <= periods_per_day:
        return False
    if (candidate.weekday, candidate.period) in forbidden_slots:
        return False
    if candidate.teacher_id is not None:
        tid = int(candidate.teacher_id)
        slot = (candidate.weekday, candidate.period)
        if slot in (teacher_forbidden_slots or {}).get(tid, set()):
            return False
        if slot in (teacher_class_forbidden_slots or {}).get((tid, int(candidate.class_id)), set()):
            return False
    if (candidate.weekday, candidate.period) in (subject_forbidden_slots or {}).get(candidate.subject_id, set()):
        return False
    allowed_at_slot = (class_slot_allowed_subjects or {}).get(candidate.class_id, {}).get(
        (candidate.weekday, candidate.period)
    )
    if allowed_at_slot is not None and candidate.subject_id not in allowed_at_slot:
        return False
    relevant = [item for index, item in enumerate(items) if index != ignored_index]
    if any(
        item.weekday == candidate.weekday
        and item.period == candidate.period
        and (
            item.class_id == candidate.class_id
            or (
                candidate.teacher_id is not None
                and item.teacher_id == candidate.teacher_id
            )
        )
        for item in relevant
    ):
        return False
    if avoid_consecutive_teacher_lessons and candidate.teacher_id is not None and any(
        item.teacher_id == candidate.teacher_id
        and item.weekday == candidate.weekday
        and abs(item.period - candidate.period) == 1
        for item in relevant
    ):
        return False
    class_day_load = sum(
        item.class_id == candidate.class_id and item.weekday == candidate.weekday
        for item in relevant
    )
    teacher_day_load = sum(
        candidate.teacher_id is not None
        and item.teacher_id == candidate.teacher_id
        and item.weekday == candidate.weekday
        for item in relevant
    )
    same_subject_today = sum(
        item.class_id == candidate.class_id
        and item.subject_id == candidate.subject_id
        and item.weekday == candidate.weekday
        for item in relevant
    )
    teacher_daily_limit = (
        teacher_daily_limits.get(candidate.teacher_id, max_teacher_lessons_per_day)
        if teacher_daily_limits is not None and candidate.teacher_id is not None
        else max_teacher_lessons_per_day
    )
    if candidate.weekday == 6 and max_teacher_lessons_on_saturday is not None:
        teacher_daily_limit = max_teacher_lessons_on_saturday
    return not (
        max_class_lessons_per_day is not None
        and class_day_load >= max_class_lessons_per_day
        or teacher_daily_limit is not None
        and teacher_day_load >= teacher_daily_limit
        or max_same_subject_per_day is not None
        and same_subject_today >= max_same_subject_per_day
    )


def _class_gap_count(
    items: Iterable[ScheduleItem],
    forbidden_slots: set[tuple[int, int]] | None = None,
) -> int:
    forbidden = forbidden_slots or set()
    periods_by_class_day: dict[tuple[int, int], set[int]] = {}
    for item in items:
        periods_by_class_day.setdefault((item.class_id, item.weekday), set()).add(item.period)
    return sum(
        sum(
            period not in periods and (weekday, period) not in forbidden
            for period in range(1, max(periods))
        )
        for (class_id, weekday), periods in periods_by_class_day.items()
        if periods
    )


def _assignment_placement_groups(
    assignment: Mapping[str, Any],
    *,
    days: int,
) -> list[tuple[tuple[int, ...], float]]:
    """Split course hours into weekday and Saturday placement pools when configured."""
    has_split = "weekday_periods" in assignment or "saturday_periods" in assignment
    if not has_split:
        return [(tuple(range(1, days + 1)), float(assignment.get("weekly_periods", 0) or 0))]

    saturday_periods = float(assignment.get("saturday_periods", 0) or 0)
    weekday_periods = assignment.get("weekday_periods")
    if weekday_periods is None:
        weekday_periods = float(assignment.get("weekly_periods", 0) or 0) - saturday_periods
    groups: list[tuple[tuple[int, ...], float]] = [(
        tuple(range(1, min(days, 5) + 1)),
        float(weekday_periods or 0),
    )]
    if saturday_periods:
        groups.append(((6,), saturday_periods) if days >= 6 else ((), saturday_periods))
    return [(allowed, count) for allowed, count in groups if count > 0]


def _phase_groups(normalized: list[Mapping[str, Any]], phase: int, *, days: int):
    """三段式排课的阶段1（工作日白天）与阶段2（周六白天）放置组产出器。

    阶段3（晚自习）由 generate_evening_schedule（CP-SAT）单独生成。分段后各阶段
    可用自己的规则收口（工作日连堂/周六连堂），互不干扰。
    """
    for assignment in normalized:
        class_id = int(assignment["class_id"])
        subject_id = int(assignment["subject_id"])
        raw_teacher_id = assignment.get("teacher_id")
        teacher_id = int(raw_teacher_id) if raw_teacher_id is not None else None
        for allowed_weekdays, group_weekly in _assignment_placement_groups(assignment, days=days):
            is_saturday = 6 in allowed_weekdays
            if (phase == 1) == is_saturday:
                continue
            yield assignment, class_id, subject_id, teacher_id, allowed_weekdays, group_weekly


def _normalize_slot_patterns(
    slot_patterns: Iterable[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    """Index executable subject slot patterns for the greedy generator.

    The rule engine owns the schema validation. The generator only consumes the
    already-compiled, typed payload and deliberately ignores global patterns,
    class-wide patterns, or patterns with multiple competing targets.
    """
    normalized: list[Mapping[str, Any]] = []
    for pattern in slot_patterns or ():
        target_type = pattern.get("target_type")
        target_ids = pattern.get("target_ids") or []
        if target_type != "subject" or len(target_ids) != 1:
            continue
        subject_id = int(target_ids[0])
        alternatives = pattern.get("alternatives")
        if not isinstance(alternatives, list) or not alternatives:
            continue
        if subject_id > 0:
            normalized.append(pattern)
    return normalized


def _pattern_applies_to_assignment(
    pattern: Mapping[str, Any],
    *,
    class_id: int,
    subject_id: int,
) -> bool:
    if pattern.get("target_type") == "subject":
        return subject_id in {int(value) for value in pattern.get("target_ids") or []}
    if pattern.get("target_type") == "class":
        return class_id in {int(value) for value in pattern.get("target_ids") or []}
    return False


def _pattern_group_matches(group: Mapping[str, Any], weekday: int, period: int) -> bool:
    return weekday in group.get("weekdays", ()) and period in group.get("periods", ())


def _locked_schedule_items(
    locked_items: Iterable[Mapping[str, Any]] | None,
    assignments: list[dict[str, Any]],
    *,
    days: int,
    periods_per_day: int,
    forbidden_slots: set[tuple[int, int]],
) -> list[ScheduleItem]:
    """Normalize manually locked grid cells into generator-owned schedule items."""
    by_id = {int(item["id"]): item for item in assignments if item.get("id") is not None}
    by_scope: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for assignment in assignments:
        by_scope[(int(assignment["class_id"]), int(assignment["subject_id"]))].append(assignment)

    result: list[ScheduleItem] = []
    occupied_classes: set[tuple[int, int, int]] = set()
    occupied_teachers: set[tuple[int, int, int]] = set()
    for raw in locked_items or ():
        class_id = int(raw["class_id"])
        subject_id = int(raw["subject_id"])
        weekday = int(raw["weekday"])
        period = int(raw["period"])
        if not 1 <= weekday <= days or not 1 <= period <= periods_per_day:
            raise ValueError("预排锁定课位超出当前课位结构")
        if (weekday, period) in forbidden_slots:
            raise ValueError(f"预排锁定课位命中禁排时段：周{weekday}第{period}节")

        assignment_id = raw.get("assignment_id")
        assignment = by_id.get(int(assignment_id)) if assignment_id is not None else None
        if assignment is None:
            candidates = by_scope.get((class_id, subject_id), [])
            assignment = candidates[0] if len(candidates) == 1 else None
        if assignment is None:
            raise ValueError("预排锁定课位找不到对应的任教关系")
        if int(assignment["class_id"]) != class_id or int(assignment["subject_id"]) != subject_id:
            raise ValueError("预排锁定课位与任教关系不匹配")

        teacher_id = assignment.get("teacher_id")
        if raw.get("teacher_id") is not None and teacher_id != int(raw["teacher_id"]):
            raise ValueError("预排锁定课位中的教师与任教关系不匹配")
        class_slot = (class_id, weekday, period)
        teacher_slot = (int(teacher_id), weekday, period) if teacher_id is not None else None
        if class_slot in occupied_classes or (teacher_slot and teacher_slot in occupied_teachers):
            raise ValueError("预排锁定课位存在班级或教师冲突")
        occupied_classes.add(class_slot)
        if teacher_slot:
            occupied_teachers.add(teacher_slot)
        result.append(ScheduleItem(
            assignment_id=int(assignment["id"]),
            class_id=class_id,
            subject_id=subject_id,
            teacher_id=int(teacher_id) if teacher_id is not None else None,
            weekday=weekday,
            period=period,
            room=assignment.get("room"),
            week_parity=WeekParity(raw.get("week_parity") or assignment.get("week_parity", WeekParity.all)),
        ))
    return result


def diagnose_staffing_gaps(items: Iterable[ScheduleItem]) -> list[dict[str, int]]:
    """Explain remaining interior gaps caused by a teacher teaching another class."""
    rows = list(items)
    periods_by_class_day: dict[tuple[int, int], set[int]] = {}
    for item in rows:
        periods_by_class_day.setdefault((item.class_id, item.weekday), set()).add(item.period)
    issues: list[dict[str, int]] = []
    for (class_id, weekday), periods in sorted(periods_by_class_day.items()):
        for gap_period in range(min(periods), max(periods)):
            if gap_period in periods:
                continue
            scheduled = min(
                (
                    item for item in rows
                    if item.class_id == class_id
                    and item.weekday == weekday
                    and item.period > gap_period
                ),
                key=lambda item: item.period,
            )
            if scheduled.teacher_id is None:
                continue
            blocker = next((
                item for item in rows
                if item.teacher_id == scheduled.teacher_id
                and item.weekday == weekday
                and item.period == gap_period
            ), None)
            if blocker is None:
                continue
            issues.append({
                "class_id": class_id,
                "subject_id": scheduled.subject_id,
                "teacher_id": scheduled.teacher_id,
                "weekday": weekday,
                "gap_period": gap_period,
                "scheduled_period": scheduled.period,
                "blocking_class_id": blocker.class_id,
                "additional_teachers": 1,
            })
    return issues


def repair_class_gaps(
    items: list[ScheduleItem],
    *,
    days: int = 5,
    periods_per_day: int = 8,
    forbidden_slots: set[tuple[int, int]] | None = None,
    max_class_lessons_per_day: int | None = None,
    max_teacher_lessons_per_day: int | None = None,
    max_same_subject_per_day: int | None = None,
    avoid_consecutive_teacher_lessons: bool = False,
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    subject_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    protected_assignment_ids: set[int] | None = None,
    max_moves: int = 30,
    max_candidate_checks: int = 200,
) -> list[ScheduleItem]:
    """Relocate at most one teacher blocker at a time to close class-table gaps."""
    result = list(items)
    forbidden = forbidden_slots or set()
    protected = protected_assignment_ids or set()
    candidate_checks = 0
    for _ in range(max_moves):
        before = _class_gap_count(result, forbidden)
        if before == 0:
            break
        periods_by_class_day: dict[tuple[int, int], set[int]] = {}
        for item in result:
            periods_by_class_day.setdefault((item.class_id, item.weekday), set()).add(item.period)
        repaired = False
        for (class_id, weekday), periods in sorted(periods_by_class_day.items()):
            gaps = [
                period for period in range(1, max(periods))
                if period not in periods and (weekday, period) not in forbidden
            ]
            for gap in gaps:
                source_indexes = sorted(
                    (
                        index for index, item in enumerate(result)
                        if item.class_id == class_id
                        and item.weekday == weekday
                        and item.period > gap
                        and item.assignment_id not in protected
                    ),
                    key=lambda index: result[index].period,
                )
                for source_index in source_indexes:
                    candidate_checks += 1
                    if candidate_checks > max_candidate_checks:
                        return result
                    source = result[source_index]
                    target = replace(source, period=gap)
                    blockers = [
                        index for index, item in enumerate(result)
                        if index != source_index
                        and item.weekday == weekday
                        and item.period == gap
                        and source.teacher_id is not None
                        and item.teacher_id == source.teacher_id
                    ]
                    candidate_result: list[ScheduleItem] | None = None
                    if not blockers and _can_place_schedule_item(
                        target, result,
                        days=days, periods_per_day=periods_per_day,
                        forbidden_slots=forbidden,
                        max_class_lessons_per_day=max_class_lessons_per_day,
                        max_teacher_lessons_per_day=max_teacher_lessons_per_day,
                        max_same_subject_per_day=max_same_subject_per_day,
                        avoid_consecutive_teacher_lessons=avoid_consecutive_teacher_lessons,
                        teacher_forbidden_slots=teacher_forbidden_slots,
                        subject_forbidden_slots=subject_forbidden_slots,
                        class_slot_allowed_subjects=class_slot_allowed_subjects,
                        ignored_index=source_index,
                    ):
                        candidate_result = list(result)
                        candidate_result[source_index] = target
                    elif len(blockers) == 1:
                        blocker_index = blockers[0]
                        blocker = result[blocker_index]
                        if blocker.assignment_id in protected:
                            continue
                        for alternate_day in range(1, days + 1):
                            for alternate_period in range(1, periods_per_day + 1):
                                moved_blocker = replace(blocker, weekday=alternate_day, period=alternate_period)
                                moved_items = list(result)
                                moved_items[blocker_index] = moved_blocker
                                if not _can_place_schedule_item(
                                    target, moved_items,
                                    days=days, periods_per_day=periods_per_day,
                                    forbidden_slots=forbidden,
                                    max_class_lessons_per_day=max_class_lessons_per_day,
                                    max_teacher_lessons_per_day=max_teacher_lessons_per_day,
                                    max_same_subject_per_day=max_same_subject_per_day,
                                    avoid_consecutive_teacher_lessons=avoid_consecutive_teacher_lessons,
                                    teacher_forbidden_slots=teacher_forbidden_slots,
                                    subject_forbidden_slots=subject_forbidden_slots,
                                    class_slot_allowed_subjects=class_slot_allowed_subjects,
                                    ignored_index=source_index,
                                ):
                                    continue
                                moved_items[source_index] = target
                                if not _can_place_schedule_item(
                                    moved_blocker, moved_items,
                                    days=days, periods_per_day=periods_per_day,
                                    forbidden_slots=forbidden,
                                    max_class_lessons_per_day=max_class_lessons_per_day,
                                    max_teacher_lessons_per_day=max_teacher_lessons_per_day,
                                    max_same_subject_per_day=max_same_subject_per_day,
                                    avoid_consecutive_teacher_lessons=avoid_consecutive_teacher_lessons,
                                    teacher_forbidden_slots=teacher_forbidden_slots,
                                    subject_forbidden_slots=subject_forbidden_slots,
                                    class_slot_allowed_subjects=class_slot_allowed_subjects,
                                    ignored_index=blocker_index,
                                ):
                                    continue
                                candidate_result = moved_items
                                break
                            if candidate_result is not None:
                                break
                    if candidate_result is not None and _class_gap_count(candidate_result, forbidden) < before:
                        result = candidate_result
                        repaired = True
                        break
                if repaired:
                    break
            if repaired:
                break
        if not repaired:
            break
    return result


def compact_class_gaps(
    items: list[ScheduleItem],
    *,
    days: int = 5,
    periods_per_day: int = 8,
    forbidden_slots: set[tuple[int, int]] | None = None,
    max_class_lessons_per_day: int | None = None,
    max_teacher_lessons_per_day: int | None = None,
    max_same_subject_per_day: int | None = None,
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    subject_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    protected_assignment_ids: set[int] | None = None,
) -> list[ScheduleItem]:
    """快速前移不冲突课程，让每个班每天的空白只出现在最后。"""
    result = list(items)
    forbidden = forbidden_slots or set()
    protected = protected_assignment_ids or set()
    periods_by_class_day: dict[tuple[int, int], set[int]] = {}
    for item in result:
        periods_by_class_day.setdefault((item.class_id, item.weekday), set()).add(item.period)

    for (class_id, weekday), periods in sorted(periods_by_class_day.items()):
        while True:
            gaps = [
                period for period in range(1, max(periods))
                if period not in periods and (weekday, period) not in forbidden
            ]
            if not gaps:
                break
            gap = gaps[0]
            source_indexes = sorted(
                (
                    index for index, item in enumerate(result)
                    if item.class_id == class_id
                    and item.weekday == weekday
                    and item.period > gap
                    and item.assignment_id not in protected
                ),
                key=lambda index: result[index].period,
            )
            for source_index in source_indexes:
                source_period = result[source_index].period
                target = replace(result[source_index], period=gap)
                if not _can_place_schedule_item(
                    target,
                    result,
                    days=days,
                    periods_per_day=periods_per_day,
                    forbidden_slots=forbidden,
                    max_class_lessons_per_day=max_class_lessons_per_day,
                    max_teacher_lessons_per_day=max_teacher_lessons_per_day,
                    max_same_subject_per_day=max_same_subject_per_day,
                    teacher_forbidden_slots=teacher_forbidden_slots,
                    subject_forbidden_slots=subject_forbidden_slots,
                    class_slot_allowed_subjects=class_slot_allowed_subjects,
                    # 压紧优先级高于“避免教师连上”这一软约束。
                    avoid_consecutive_teacher_lessons=False,
                    ignored_index=source_index,
                ):
                    continue
                result[source_index] = target
                periods.remove(source_period)
                periods.add(gap)
                break
            else:
                # 最早空位被教师硬冲突挡住时，避免反复尝试同一个空位。
                break
    return result


def _repair_unplaced_lessons(
    items: list[ScheduleItem],
    unplaced: list[dict[str, Any]],
    assignments: dict[int, dict[str, Any]],
    *,
    days: int,
    periods_per_day: int,
    forbidden_slots: set[tuple[int, int]],
    max_class_lessons_per_day: int | None,
    max_teacher_lessons_per_day: int | None,
    max_same_subject_per_day: int | None,
    avoid_consecutive_teacher_lessons: bool = False,
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    subject_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    protected_assignment_ids: set[int] | None = None,
) -> tuple[list[ScheduleItem], list[dict[str, Any]]]:
    """通过移动一个阻塞课程，尝试修复贪心初排留下的课程。"""
    remaining: list[dict[str, Any]] = []
    protected = protected_assignment_ids or set()
    for entry in unplaced:
        assignment = assignments[entry["assignment_id"]]
        target_days = tuple(entry.get("allowed_weekdays") or range(1, days + 1))
        if int(entry["assignment_id"]) in protected:
            remaining.append({
                "assignment_id": entry["assignment_id"],
                "count": entry["count"],
                "allowed_weekdays": target_days,
            })
            continue
        repaired = 0
        for _ in range(entry["count"]):
            target_template = ScheduleItem(
                assignment_id=int(assignment["id"]),
                class_id=int(assignment["class_id"]),
                subject_id=int(assignment["subject_id"]),
                teacher_id=int(assignment["teacher_id"]) if assignment.get("teacher_id") is not None else None,
                weekday=1,
                period=1,
                room=assignment.get("room"),
            )
            placed = False
            for target_day in target_days:
                for target_period in range(1, periods_per_day + 1):
                    target = replace(target_template, weekday=target_day, period=target_period)
                    blockers = [
                        index for index, item in enumerate(items)
                        if item.weekday == target_day
                        and item.period == target_period
                        and (
                            item.class_id == target.class_id
                            or target.teacher_id is not None and item.teacher_id == target.teacher_id
                        )
                    ]
                    if len(blockers) != 1:
                        continue
                    blocker_index = blockers[0]
                    blocker = items[blocker_index]
                    if blocker.assignment_id in protected:
                        continue
                    for alternate_day in range(1, days + 1):
                        for alternate_period in range(1, periods_per_day + 1):
                            if (alternate_day, alternate_period) == (target_day, target_period):
                                continue
                            moved = replace(blocker, weekday=alternate_day, period=alternate_period)
                            if not _can_place_schedule_item(
                                moved, items,
                                days=days,
                                periods_per_day=periods_per_day,
                                forbidden_slots=forbidden_slots,
                                max_class_lessons_per_day=max_class_lessons_per_day,
                                max_teacher_lessons_per_day=max_teacher_lessons_per_day,
                                max_same_subject_per_day=max_same_subject_per_day,
                                avoid_consecutive_teacher_lessons=avoid_consecutive_teacher_lessons,
                                teacher_forbidden_slots=teacher_forbidden_slots,
                                subject_forbidden_slots=subject_forbidden_slots,
                                class_slot_allowed_subjects=class_slot_allowed_subjects,
                                ignored_index=blocker_index,
                            ):
                                continue
                            candidate_items = list(items)
                            candidate_items[blocker_index] = moved
                            if not _can_place_schedule_item(
                                target, candidate_items,
                                days=days,
                                periods_per_day=periods_per_day,
                                forbidden_slots=forbidden_slots,
                                max_class_lessons_per_day=max_class_lessons_per_day,
                                max_teacher_lessons_per_day=max_teacher_lessons_per_day,
                                max_same_subject_per_day=max_same_subject_per_day,
                                avoid_consecutive_teacher_lessons=avoid_consecutive_teacher_lessons,
                                teacher_forbidden_slots=teacher_forbidden_slots,
                                subject_forbidden_slots=subject_forbidden_slots,
                                class_slot_allowed_subjects=class_slot_allowed_subjects,
                            ):
                                continue
                            items = candidate_items
                            items.append(target)
                            repaired += 1
                            placed = True
                            break
                        if placed:
                            break
                    if placed:
                        break
                if placed:
                    break
            if not placed:
                break
        if repaired < entry["count"]:
            remaining.append({
                "assignment_id": entry["assignment_id"],
                "count": entry["count"] - repaired,
                "allowed_weekdays": target_days,
            })
    return items, remaining


def _place_half_week_lessons(
    items: list[ScheduleItem],
    assignments: list[dict[str, Any]],
    *,
    days: int,
    periods_per_day: int,
    forbidden_slots: set[tuple[int, int]],
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    teacher_class_forbidden_slots: Mapping[tuple[int, int], set[tuple[int, int]]] | None = None,
    subject_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    max_teacher_lessons_per_day: int | None = None,
    max_teacher_lessons_on_saturday: int | None = None,
    teacher_daily_limits: dict[int, int] | None = None,
) -> list[dict[str, int | float]]:
    """Place each residual half-period in an odd/even leg of the same timetable slot.

    The source assignment list has no elective-group dimension, so halves are paired in
    stable assignment order within a class.  A later half is allowed to reuse the
    first half's slot only when the parity legs differ.
    """
    next_parity: dict[tuple[int, tuple[int, ...]], WeekParity] = {}
    unplaced: list[dict[str, int | float | tuple[int, ...]]] = []
    for assignment in assignments:
        class_id = int(assignment["class_id"])
        teacher_id = int(assignment["teacher_id"]) if assignment.get("teacher_id") is not None else None
        for allowed_weekdays, weekly in _assignment_placement_groups(assignment, days=days):
            if weekly - int(weekly) < 0.49:
                continue
            parity_key = (class_id, allowed_weekdays)
            configured_parity = assignment.get("week_parity")
            parity = (
                WeekParity(configured_parity)
                if configured_parity and configured_parity != WeekParity.all
                else next_parity.get(parity_key, WeekParity.odd)
            )
            placed = False
            for weekday in allowed_weekdays:
                for period in range(1, periods_per_day + 1):
                    if (weekday, period) in forbidden_slots:
                        continue
                    if teacher_id is not None:
                        slot = (weekday, period)
                        if slot in (teacher_forbidden_slots or {}).get(teacher_id, set()):
                            continue
                        if slot in (teacher_class_forbidden_slots or {}).get((teacher_id, class_id), set()):
                            continue
                    if teacher_id is not None:
                        # 单双周腿按周实例计入教师日上限，避免隔周课把当天顶超限。
                        limit = (
                            teacher_daily_limits.get(teacher_id, max_teacher_lessons_per_day)
                            if teacher_daily_limits is not None
                            else max_teacher_lessons_per_day
                        )
                        if weekday == 6 and max_teacher_lessons_on_saturday is not None:
                            limit = max_teacher_lessons_on_saturday
                        if limit is not None:
                            all_count = sum(
                                1 for it in items
                                if it.teacher_id == teacher_id and it.weekday == weekday
                                and it.week_parity == WeekParity.all
                            )
                            leg_count = sum(
                                1 for it in items
                                if it.teacher_id == teacher_id and it.weekday == weekday
                                and it.week_parity == parity
                            )
                            if all_count + leg_count + 1 > limit:
                                continue
                    if (weekday, period) in (subject_forbidden_slots or {}).get(int(assignment["subject_id"]), set()):
                        continue
                    allowed_at_slot = (class_slot_allowed_subjects or {}).get(class_id, {}).get((weekday, period))
                    if allowed_at_slot is not None and int(assignment["subject_id"]) not in allowed_at_slot:
                        continue
                    if any(
                        item.weekday == weekday and item.period == period
                        and parity_conflicts(item.week_parity, parity)
                        and (item.class_id == class_id or (teacher_id is not None and item.teacher_id == teacher_id))
                        for item in items
                    ):
                        continue
                    items.append(ScheduleItem(
                        assignment_id=int(assignment["id"]), class_id=class_id,
                        subject_id=int(assignment["subject_id"]), teacher_id=teacher_id,
                        weekday=weekday, period=period, room=assignment.get("room"), week_parity=parity,
                    ))
                    next_parity[parity_key] = WeekParity.even if parity is WeekParity.odd else WeekParity.odd
                    placed = True
                    break
                if placed:
                    break
            if not placed:
                unplaced.append({
                    "assignment_id": int(assignment["id"]),
                    "count": 0.5,
                    "allowed_weekdays": allowed_weekdays,
                })
    return unplaced


def _daytime_link_satisfied(
    items: Iterable[ScheduleItem],
    *,
    teacher_id: int,
    weekday: int,
    evening_start: int,
    required_period: int,
) -> bool:
    """Evening day only requires the linked daytime period (e.g. period 7)."""
    return any(
        item.teacher_id == teacher_id
        and item.weekday == weekday
        and item.period < evening_start
        and item.period == required_period
        for item in items
    )


def ensure_teacher_evening_daytime_anchors(
    items: list[ScheduleItem],
    *,
    links: Iterable[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]],
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    subject_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    evening_start_period: int = 9,
) -> list[ScheduleItem]:
    """把晚课联动教师的白天课挪到 required_period，避免整周没有锚点导致晚课落不下。

    例：黄丽娟「有晚课的那天必须有第7节」——若 CP-SAT 白天从未排第7节，
    晚课构建会因联动失败而整周跳过该教师的 0.5 晚课。
    """
    working = list(items)
    forbidden = teacher_forbidden_slots or {}
    subject_forbidden = subject_forbidden_slots or {}
    assignment_rows = [dict(row) for row in assignments]
    link_rows = [dict(link) for link in links]

    def subject_banned(subject_id: int, weekday: int, period: int) -> bool:
        return (weekday, period) in subject_forbidden.get(int(subject_id), set())

    def evening_day_need(teacher_id: int) -> int:
        odd = even = 0
        for row in assignment_rows:
            if row.get("teacher_id") is None or int(row["teacher_id"]) != teacher_id:
                continue
            odd += max(0, int(row.get("evening_periods_odd") or 0))
            even += max(0, int(row.get("evening_periods_even") or 0))
        return max(odd, even)

    def anchor_days(teacher_id: int, required_period: int, evening_start: int) -> set[int]:
        return {
            item.weekday
            for item in working
            if item.teacher_id == teacher_id
            and item.period == required_period
            and item.period < evening_start
        }

    def teacher_busy(teacher_id: int | None, weekday: int, period: int, ignore: ScheduleItem | None = None) -> bool:
        if teacher_id is None:
            return False
        return any(
            item.teacher_id == teacher_id
            and item.weekday == weekday
            and item.period == period
            and item is not ignore
            for item in working
        )

    def class_at(class_id: int, weekday: int, period: int) -> list[ScheduleItem]:
        return [
            item
            for item in working
            if item.class_id == class_id and item.weekday == weekday and item.period == period
        ]

    for link in link_rows:
        teacher_id = int(link["teacher_id"])
        required_period = int(link["required_daytime_period"])
        evening_start = int(link.get("evening_start_period") or evening_start_period)
        need = evening_day_need(teacher_id)
        if need <= 0:
            continue
        # 只需覆盖晚课天数；把所有白天课都挪到锚点节会破坏「第3/4/5节至少2节」等规则。
        # 周六晚课多为班主任保留位，锚点配额只认周一～五；周六第7节不算“已满足”。
        target_anchors = need
        ban = forbidden.get(teacher_id, set())
        for _ in range(target_anchors + 8):
            have = {day for day in anchor_days(teacher_id, required_period, evening_start) if day <= 5}
            if len(have) >= target_anchors:
                break
            candidates = [
                item
                for item in working
                if item.teacher_id == teacher_id
                and item.period < evening_start
                and item.weekday <= 5
                and item.weekday not in have
            ]
            candidates.sort(key=lambda item: (item.weekday, item.period))
            moved = False
            for item in candidates:
                weekday = item.weekday
                if (weekday, required_period) in ban:
                    continue
                if teacher_busy(teacher_id, weekday, required_period, ignore=item):
                    continue
                if subject_banned(item.subject_id, weekday, required_period):
                    continue
                occupants = class_at(item.class_id, weekday, required_period)
                if not occupants:
                    working.remove(item)
                    working.append(replace(item, period=required_period))
                    moved = True
                    break
                other = occupants[0]
                if len(occupants) > 1:
                    continue
                if subject_banned(other.subject_id, weekday, item.period):
                    continue
                if other.teacher_id is not None:
                    other_tid = int(other.teacher_id)
                    if teacher_busy(other_tid, weekday, item.period, ignore=other):
                        continue
                    if (weekday, item.period) in forbidden.get(other_tid, set()):
                        continue
                working.remove(item)
                working.remove(other)
                working.append(replace(item, period=required_period))
                working.append(replace(other, period=item.period))
                moved = True
                break
            # 直换失败时同日三步倒：锚点课→第7节，第7节课→中转节，中转节课→原锚点节。
            # 例：周三 生物@4、政治@7、美术@8，且政治不能落4 → 生→7、政→8、美→4。
            if not moved:
                for item in candidates:
                    weekday = item.weekday
                    if (weekday, required_period) in ban:
                        continue
                    if teacher_busy(teacher_id, weekday, required_period, ignore=item):
                        continue
                    if subject_banned(item.subject_id, weekday, required_period):
                        continue
                    occupants = class_at(item.class_id, weekday, required_period)
                    if len(occupants) != 1:
                        continue
                    other = occupants[0]
                    for relay_period in range(1, evening_start):
                        if relay_period in {item.period, required_period}:
                            continue
                        relays = class_at(item.class_id, weekday, relay_period)
                        if len(relays) != 1:
                            continue
                        relay = relays[0]
                        # other → relay_period
                        if subject_banned(other.subject_id, weekday, relay_period):
                            continue
                        if other.teacher_id is not None:
                            ot = int(other.teacher_id)
                            if teacher_busy(ot, weekday, relay_period, ignore=other):
                                continue
                            if (weekday, relay_period) in forbidden.get(ot, set()):
                                continue
                        # relay → item.period
                        if subject_banned(relay.subject_id, weekday, item.period):
                            continue
                        if relay.teacher_id is not None:
                            rt = int(relay.teacher_id)
                            if teacher_busy(rt, weekday, item.period, ignore=relay):
                                continue
                            if (weekday, item.period) in forbidden.get(rt, set()):
                                continue
                        working.remove(item)
                        working.remove(other)
                        working.remove(relay)
                        working.append(replace(item, period=required_period))
                        working.append(replace(other, period=relay_period))
                        working.append(replace(relay, period=item.period))
                        moved = True
                        break
                    if moved:
                        break
            if not moved:
                # 同日对调失败时：把该教师一节白天课跨日挪到「本班第7节可腾出」的工作日。
                for item in candidates:
                    for weekday in range(1, 6):
                        if weekday in have or weekday == item.weekday:
                            continue
                        if (weekday, required_period) in ban:
                            continue
                        if teacher_busy(teacher_id, weekday, required_period):
                            continue
                        if subject_banned(item.subject_id, weekday, required_period):
                            continue
                        # 目标日该班不能已有该教师其它课（避免同日两节超负荷冲突未建模时硬撞）。
                        if any(
                            row.teacher_id == teacher_id
                            and row.class_id == item.class_id
                            and row.weekday == weekday
                            and row.period < evening_start
                            for row in working
                        ):
                            continue
                        occupants = class_at(item.class_id, weekday, required_period)
                        if not occupants:
                            working.remove(item)
                            working.append(replace(item, weekday=weekday, period=required_period))
                            moved = True
                            break
                        if len(occupants) > 1:
                            continue
                        other = occupants[0]
                        # 不要拆同日学科连堂（如第 6-7 节），否则会打爆 R05。
                        if any(
                            row.class_id == other.class_id
                            and row.subject_id == other.subject_id
                            and row.weekday == other.weekday
                            and abs(row.period - other.period) == 1
                            for row in working
                            if row is not other
                        ):
                            continue
                        # 先把占第7节的课挤到该日空节，再接入锚点课。
                        # 若空节上该教师在别班有课，尝试把别班那节挪开后再挤入。
                        free_period = None
                        for period in range(1, evening_start):
                            if period == required_period:
                                continue
                            if class_at(item.class_id, weekday, period):
                                continue
                            if subject_banned(other.subject_id, weekday, period):
                                continue
                            if other.teacher_id is None:
                                free_period = period
                                break
                            other_tid = int(other.teacher_id)
                            if (weekday, period) in forbidden.get(other_tid, set()):
                                continue
                            blockers = [
                                row
                                for row in working
                                if row.teacher_id == other_tid
                                and row.weekday == weekday
                                and row.period == period
                                and row is not other
                            ]
                            can_clear = True
                            local_clears: list[tuple[object, int]] = []
                            for blocker in blockers:
                                dest = next(
                                    (
                                        p
                                        for p in range(1, evening_start)
                                        if p != period
                                        and not class_at(blocker.class_id, weekday, p)
                                        and not subject_banned(blocker.subject_id, weekday, p)
                                        and not teacher_busy(other_tid, weekday, p, ignore=blocker)
                                        and (weekday, p) not in forbidden.get(other_tid, set())
                                    ),
                                    None,
                                )
                                if dest is None:
                                    can_clear = False
                                    break
                                local_clears.append((blocker, dest))
                            if not can_clear:
                                continue
                            for blocker, dest in local_clears:
                                working.remove(blocker)
                                working.append(replace(blocker, period=dest))
                            free_period = period
                            break
                        if free_period is None:
                            continue
                        working.remove(item)
                        working.remove(other)
                        working.append(replace(other, period=free_period))
                        working.append(replace(item, weekday=weekday, period=required_period))
                        moved = True
                        break
                    if moved:
                        break
                if not moved:
                    break
    return working


def _evening_half_pair_catalog(
    declared_pairs: list[tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """仅规则声明的强制对课（如物|史），去重后的 (a, b) 列表。

    化/政/生/地等其余 0.5 不在此目录，由 ``_resolve_evening_half_pairs`` 任意互配。
    """
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for pair in list(declared_pairs or []):
        key = (int(pair[0]), int(pair[1]))
        rev = (key[1], key[0])
        if key in seen or rev in seen:
            continue
        seen.add(key)
        pairs.append(key)
    return pairs


def _evening_half_pair_subject_ids(
    declared_pairs: list[tuple[int, int]] | None = None,
) -> set[int]:
    return {sid for pair in _evening_half_pair_catalog(declared_pairs) for sid in pair}


def _half_evening_subject_ids(
    assignment_rows: Iterable[Mapping[str, Any]],
    *,
    class_id: int | None = None,
    evening_count_fn=None,
) -> set[int]:
    """本班（或全部）课时方案里仅单侧有晚课的学科。"""
    ids: set[int] = set()
    for row in assignment_rows:
        if class_id is not None and int(row["class_id"]) != class_id:
            continue
        sid = int(row["subject_id"])
        if evening_count_fn is not None:
            odd_n = int(evening_count_fn(row, WeekParity.odd))
            even_n = int(evening_count_fn(row, WeekParity.even))
        else:
            odd_n = max(0, int(row.get("evening_periods_odd") or 0))
            even_n = max(0, int(row.get("evening_periods_even") or 0))
        if evening_is_flex_half(row) or (odd_n > 0) ^ (even_n > 0):
            ids.add(sid)
    return ids


def repair_evening_hard_constraints(
    items: list[ScheduleItem],
    *,
    assignments: Iterable[Mapping[str, Any]],
    first_evening_period: int,
    evening_daily_periods_odd: list[int],
    evening_daily_periods_even: list[int],
    parity_subject_pairs: list[tuple[int, int]],
    free_evening_days: Mapping[int, set[int]],
    required_teacher_by_slot: Mapping[tuple[int, int], Mapping[int, int]],
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]],
    activity_subject_id: int | None,
    anchor_items: Iterable[ScheduleItem],
    teacher_evening_daytime_links: list[Mapping[str, Any]],
    self_study_candidates: Mapping[int, set[int]] | None = None,
    teacher_preferred_evening_weekdays: Mapping[int, set[int]] | None = None,
) -> list[ScheduleItem]:
    """Force hard evening constraints that the greedy pass may leave unmet."""
    working = list(items)
    assignment_rows = [dict(row) for row in assignments]
    anchor = list(anchor_items)
    preferred_days = {
        int(teacher_id): {int(day) for day in days}
        for teacher_id, days in (teacher_preferred_evening_weekdays or {}).items()
        if days
    }

    pinned_self_study = {int(class_id): set(days) for class_id, days in (free_evening_days or {}).items()}
    study_candidates = {
        int(class_id): set(days)
        for class_id, days in (self_study_candidates or {}).items()
    }
    self_study_choose = {class_id: max(1, len(days)) for class_id, days in pinned_self_study.items()}
    free_evening_days = pinned_self_study

    def evening_slots() -> list[tuple[int, int]]:
        odd = {
            (weekday, first_evening_period + offset)
            for weekday, count in enumerate(evening_daily_periods_odd, start=1)
            for offset in range(count)
        }
        even = {
            (weekday, first_evening_period + offset)
            for weekday, count in enumerate(evening_daily_periods_even, start=1)
            for offset in range(count)
        }
        return sorted(odd & even)

    def teacher_busy(
        teacher_id: int | None,
        weekday: int,
        period: int,
        parity: WeekParity,
        *,
        ignore: set[int] | None = None,
    ) -> bool:
        if teacher_id is None:
            return False
        skip = ignore or set()
        for item in working:
            if id(item) in skip:
                continue
            if item.teacher_id != teacher_id or item.weekday != weekday or item.period != period:
                continue
            if parity_conflicts(item.week_parity, parity):
                return True
        return False

    def class_busy(class_id: int, weekday: int, period: int, parity: WeekParity, *, allow_activity: bool) -> bool:
        for item in working:
            if item.class_id != class_id or item.weekday != weekday or item.period != period:
                continue
            if allow_activity and activity_subject_id is not None and item.subject_id == activity_subject_id:
                continue
            if parity_conflicts(item.week_parity, parity):
                return True
        return False

    def fill_leftover_activity(class_id: int, weekday: int, period: int, parity: WeekParity) -> None:
        if activity_subject_id is None:
            return
        if class_busy(class_id, weekday, period, parity, allow_activity=False):
            return
        working.append(ScheduleItem(
            assignment_id=0,
            class_id=class_id,
            subject_id=activity_subject_id,
            teacher_id=None,
            weekday=weekday,
            period=period,
            week_parity=parity,
        ))

    def teacher_banned(teacher_id: int | None, weekday: int, period: int) -> bool:
        if teacher_id is None:
            return False
        return (weekday, period) in teacher_forbidden_slots.get(int(teacher_id), set())

    def items_at(class_id: int, weekday: int, period: int) -> list[ScheduleItem]:
        return [
            item for item in working
            if item.class_id == class_id and item.weekday == weekday and item.period == period
        ]

    def is_self_study_slot(class_id: int, weekday: int, period: int) -> bool:
        rows = items_at(class_id, weekday, period)
        if not rows:
            return True
        if activity_subject_id is None:
            return False
        return all(item.subject_id == activity_subject_id for item in rows)

    def evening_link_ok(teacher_id: int | None, weekday: int) -> bool:
        if teacher_id is None:
            return True
        link = next(
            (
                row for row in teacher_evening_daytime_links
                if int(row["teacher_id"]) == int(teacher_id)
            ),
            None,
        )
        if link is None:
            return True
        evening_start = int(link.get("evening_start_period") or first_evening_period)
        required_period = int(link["required_daytime_period"])
        return _daytime_link_satisfied(
            [*anchor, *working],
            teacher_id=int(teacher_id),
            weekday=weekday,
            evening_start=evening_start,
            required_period=required_period,
        )

    def group_is_complete_block(group: list[ScheduleItem]) -> bool:
        """整组才允许挪：单双都在，或本来就是整周课。拆一条腿不算能挪。"""
        if not group:
            return False
        if any(item.week_parity is WeekParity.all for item in group):
            return True
        has_odd = any(item.week_parity is WeekParity.odd for item in group)
        has_even = any(item.week_parity is WeekParity.even for item in group)
        return has_odd and has_even

    def class_study_candidates(class_id: int) -> set[int]:
        return study_candidates.get(class_id) or free_evening_days.get(class_id, set())

    def can_take_class_self_study(class_id: int, dest_weekday: int, origin_weekday: int) -> bool:
        """班级自习日只能调到当前课位，且当前课位必须仍是候选日。"""
        if dest_weekday not in free_evening_days.get(class_id, set()):
            return True
        candidates = class_study_candidates(class_id)
        return origin_weekday in candidates and dest_weekday in candidates

    def transfer_class_self_study(class_id: int, from_day: int, to_day: int) -> None:
        days = free_evening_days.setdefault(class_id, set())
        if from_day in days:
            days.discard(from_day)
            days.add(to_day)

    def group_can_sit(
        group: list[ScheduleItem],
        weekday: int,
        period: int,
        *,
        ignore: Iterable[ScheduleItem] = (),
    ) -> bool:
        if not group:
            return False
        class_id = group[0].class_id
        if not can_take_class_self_study(class_id, weekday, group[0].weekday):
            return False
        head_id = required_teacher_by_slot.get((weekday, period), {}).get(class_id)
        if head_id is not None and not any(item.teacher_id == int(head_id) for item in group):
            return False
        skip = {id(item) for item in group} | {id(item) for item in ignore}
        for item in group:
            if teacher_banned(item.teacher_id, weekday, period):
                return False
            if not evening_link_ok(item.teacher_id, weekday):
                return False
            if teacher_busy(
                int(item.teacher_id) if item.teacher_id is not None else None,
                weekday,
                period,
                item.week_parity,
                ignore=skip,
            ):
                return False
        return True

    def move_group(group: list[ScheduleItem], weekday: int, period: int) -> None:
        # 去重并跳过已被置换挪走的课节，避免 list.remove 抛错。
        unique: list[ScheduleItem] = []
        seen: set[int] = set()
        for item in group:
            key = id(item)
            if key in seen or item not in working:
                continue
            seen.add(key)
            unique.append(item)
        if not unique:
            return
        class_id = unique[0].class_id
        origin_day, origin_period = unique[0].weekday, unique[0].period
        taking_study = weekday in free_evening_days.get(class_id, set())
        clear_activity(class_id, weekday, period)
        for item in unique:
            working.remove(item)
            working.append(replace(item, weekday=weekday, period=period))
        fill_leftover_activity(class_id, origin_day, origin_period, WeekParity.odd)
        fill_leftover_activity(class_id, origin_day, origin_period, WeekParity.even)
        fill_leftover_activity(class_id, origin_day, origin_period, WeekParity.all)
        if taking_study:
            transfer_class_self_study(class_id, weekday, origin_day)

    def slot_required_head(class_id: int, weekday: int, period: int) -> int | None:
        head = required_teacher_by_slot.get((weekday, period), {}).get(class_id)
        return int(head) if head is not None else None

    def group_pins_required_head(group: list[ScheduleItem]) -> bool:
        """班主任保留位上的班主任学科（整周或单双拼格）不得整组挪走。"""
        if not group:
            return False
        class_id = group[0].class_id
        head_id = slot_required_head(class_id, group[0].weekday, group[0].period)
        return head_id is not None and any(item.teacher_id == head_id for item in group)

    def teacher_pref_day_ok(teacher_id: int | None, weekday: int) -> bool:
        if teacher_id is None:
            return True
        allowed = preferred_days.get(int(teacher_id))
        return allowed is None or int(weekday) in allowed

    def group_pref_day_ok(group: list[ScheduleItem], weekday: int) -> bool:
        return all(teacher_pref_day_ok(item.teacher_id, weekday) for item in group)

    def group_pinned_by_pref(group: list[ScheduleItem]) -> bool:
        """硬偏好教师已落在偏好日上的整组，禁止被挤到偏好外。"""
        for item in group:
            if item.teacher_id is None:
                continue
            allowed = preferred_days.get(int(item.teacher_id))
            if allowed and int(item.weekday) in allowed:
                return True
        return False

    def find_relocate_plan(group: list[ScheduleItem]) -> tuple[str, int, int, list[ScheduleItem]] | None:
        """先看能不能整组落到合法课位；找不到落点就返回 None，不改课表。

        偏好日优先；为保住晚课满格，必要时允许落到偏好外，也可挤开已在偏好日上的整组。
        """
        if not group_is_complete_block(group):
            return None
        if group_pins_required_head(group):
            return None
        class_id = group[0].class_id
        origin_day, origin_period = group[0].weekday, group[0].period
        ids = {id(item) for item in group}
        candidate_slots = sorted(
            evening_slots(),
            key=lambda slot: (0 if group_pref_day_ok(group, slot[0]) else 1, slot[0], slot[1]),
        )

        def try_study(require_pref: bool) -> tuple[str, int, int, list[ScheduleItem]] | None:
            for weekday, period in candidate_slots:
                if weekday == origin_day and period == origin_period:
                    continue
                if require_pref and not group_pref_day_ok(group, weekday):
                    continue
                if not (
                    is_self_study_slot(class_id, weekday, period)
                    or weekday in free_evening_days.get(class_id, set())
                ):
                    continue
                if group_can_sit(group, weekday, period):
                    return ("study", weekday, period, [])
            return None

        def try_swap(require_pref: bool, *, respect_pinned: bool) -> tuple[str, int, int, list[ScheduleItem]] | None:
            for weekday, period in candidate_slots:
                if weekday == origin_day and period == origin_period:
                    continue
                if require_pref and not group_pref_day_ok(group, weekday):
                    continue
                other = [
                    item for item in items_at(class_id, weekday, period)
                    if item.teacher_id is not None and id(item) not in ids
                ]
                if not group_is_complete_block(other):
                    continue
                if respect_pinned and group_pinned_by_pref(other):
                    continue
                if not group_can_sit(group, weekday, period, ignore=other):
                    continue
                if not group_can_sit(other, origin_day, origin_period, ignore=group):
                    continue
                if require_pref and not group_pref_day_ok(other, origin_day):
                    continue
                return ("swap", weekday, period, other)
            return None

        return (
            try_study(True)
            or try_swap(True, respect_pinned=True)
            or try_study(False)
            or try_swap(False, respect_pinned=True)
            or try_swap(False, respect_pinned=False)
        )

    def apply_relocate_plan(
        group: list[ScheduleItem],
        plan: tuple[str, int, int, list[ScheduleItem]],
    ) -> None:
        kind, weekday, period, other = plan
        if kind == "study":
            move_group(group, weekday, period)
            return
        for item in group:
            working.remove(item)
        for item in other:
            working.remove(item)
        origin_day, origin_period = group[0].weekday, group[0].period
        working.extend(replace(item, weekday=weekday, period=period) for item in group)
        working.extend(replace(item, weekday=origin_day, period=origin_period) for item in other)

    def clear_activity(class_id: int, weekday: int, period: int) -> None:
        if activity_subject_id is None:
            return
        working[:] = [
            item for item in working
            if not (
                item.class_id == class_id
                and item.weekday == weekday
                and item.period == period
                and item.subject_id == activity_subject_id
            )
        ]

    # --- 0.5 对课：整组落位。抽调时必须把被占班级的对课整组挪走，课时不能丢。 ---
    # 强制对课（规则）+ 各班剩余 0.5 任意互配结果。
    def _plan_evening_count(row: Mapping[str, Any], parity: WeekParity) -> int:
        return plan_evening_count_for_parity(row, parity)

    half_pair_subjects = _half_evening_subject_ids(assignment_rows) | _evening_half_pair_subject_ids(
        parity_subject_pairs
    )
    # 规则强制对课全局适用；其余 0.5 任意互配按班级各自锁定，禁止把 A 班的化|政
    # 套到 B 班（B 班可能已是化|地），否则 strip_unpaired 会拆掉已排满的晚课。
    declared_pairs = list(_evening_half_pair_catalog(parity_subject_pairs))
    pairs_by_class: dict[int, list[tuple[int, int]]] = defaultdict(list)
    _class_ids_for_pairs = sorted({int(row["class_id"]) for row in assignment_rows})
    for _cid in _class_ids_for_pairs:
        _consumed: dict[tuple[int, WeekParity], int] = defaultdict(int)
        for item in working:
            if item.class_id != _cid or item.period < first_evening_period:
                continue
            if item.week_parity is WeekParity.all:
                _consumed[(item.subject_id, WeekParity.odd)] += 1
                _consumed[(item.subject_id, WeekParity.even)] += 1
            else:
                _consumed[(item.subject_id, item.week_parity)] += 1
        seen_local = set(declared_pairs) | {(b, a) for a, b in declared_pairs}
        for odd_sid, even_sid in _resolve_evening_half_pairs(
            assignment_rows,
            class_id=_cid,
            evening_count=_plan_evening_count,
            pair_consumed=_consumed,
            declared_pairs=parity_subject_pairs,
        ):
            key = (int(odd_sid), int(even_sid))
            rev = (key[1], key[0])
            if key in seen_local or rev in seen_local:
                continue
            seen_local.add(key)
            pairs_by_class[_cid].append(key)

    def iter_evening_pairs(class_id: int) -> list[tuple[int, int]]:
        return [*declared_pairs, *pairs_by_class.get(int(class_id), [])]

    for class_id in _class_ids_for_pairs:
        for subject_a, subject_b in iter_evening_pairs(class_id):
            assign_a = next((row for row in assignment_rows if int(row["class_id"]) == class_id and int(row["subject_id"]) == subject_a), None)
            assign_b = next((row for row in assignment_rows if int(row["class_id"]) == class_id and int(row["subject_id"]) == subject_b), None)
            if assign_a is None or assign_b is None:
                continue

            def evening_count(row: Mapping[str, Any], parity: WeekParity) -> int:
                return plan_evening_count_for_parity(row, parity)

            forward_needed = evening_count(assign_a, WeekParity.odd) > 0 and evening_count(assign_b, WeekParity.even) > 0
            reverse_needed = evening_count(assign_a, WeekParity.even) > 0 and evening_count(assign_b, WeekParity.odd) > 0
            if not (forward_needed or reverse_needed):
                continue

            def slots_of(subject_id: int, parity: WeekParity) -> set[tuple[int, int]]:
                return {
                    (item.weekday, item.period)
                    for item in working
                    if item.class_id == class_id
                    and item.subject_id == subject_id
                    and item.period >= first_evening_period
                    and item.week_parity is parity
                }

            a_odd, a_even = slots_of(subject_a, WeekParity.odd), slots_of(subject_a, WeekParity.even)
            b_odd, b_even = slots_of(subject_b, WeekParity.odd), slots_of(subject_b, WeekParity.even)
            if (forward_needed and a_odd == b_even and a_odd) or (reverse_needed and a_even == b_odd and a_even):
                continue

            pair_subjects = {subject_a, subject_b}
            saved_legs = [
                item for item in working
                if item.class_id == class_id
                and item.subject_id in pair_subjects
                and item.period >= first_evening_period
            ]
            working[:] = [
                item for item in working
                if not (
                    item.class_id == class_id
                    and item.subject_id in pair_subjects
                    and item.period >= first_evening_period
                )
            ]
            odd_subject, even_subject, odd_assign, even_assign = (
                (subject_a, subject_b, assign_a, assign_b)
                if forward_needed else
                (subject_b, subject_a, assign_b, assign_a)
            )
            teacher_o = odd_assign.get("teacher_id")
            teacher_e = even_assign.get("teacher_id")
            placed = False
            origin_days = {item.weekday for item in saved_legs}

            def pair_may_use_day(weekday: int) -> bool:
                if weekday not in free_evening_days.get(class_id, set()):
                    return True
                if len(origin_days) != 1:
                    return False
                return can_take_class_self_study(class_id, weekday, next(iter(origin_days)))

            def commit_pair(weekday: int, period: int) -> None:
                nonlocal placed
                taking_study = weekday in free_evening_days.get(class_id, set())
                clear_activity(class_id, weekday, period)
                working.append(ScheduleItem(
                    assignment_id=int(odd_assign.get("id") or 0),
                    class_id=class_id,
                    subject_id=odd_subject,
                    teacher_id=int(teacher_o) if teacher_o is not None else None,
                    weekday=weekday,
                    period=period,
                    room=odd_assign.get("room"),
                    week_parity=WeekParity.odd,
                ))
                working.append(ScheduleItem(
                    assignment_id=int(even_assign.get("id") or 0),
                    class_id=class_id,
                    subject_id=even_subject,
                    teacher_id=int(teacher_e) if teacher_e is not None else None,
                    weekday=weekday,
                    period=period,
                    room=even_assign.get("room"),
                    week_parity=WeekParity.even,
                ))
                if taking_study and origin_days:
                    origin = next(iter(origin_days))
                    transfer_class_self_study(class_id, weekday, origin)
                    fill_leftover_activity(class_id, origin, period, WeekParity.odd)
                    fill_leftover_activity(class_id, origin, period, WeekParity.even)
                    fill_leftover_activity(class_id, origin, period, WeekParity.all)
                placed = True

            def pair_ok_on_required_head(weekday: int, period: int) -> bool:
                """班主任保留位：拼格时班主任可以是单周科或双周科教师。"""
                head_id = slot_required_head(class_id, weekday, period)
                if head_id is None:
                    return True
                return (
                    (teacher_o is not None and int(teacher_o) == head_id)
                    or (teacher_e is not None and int(teacher_e) == head_id)
                )

            for weekday, period in evening_slots():
                if not pair_may_use_day(weekday):
                    continue
                if not pair_ok_on_required_head(weekday, period):
                    continue
                if teacher_o is not None and (weekday, period) in teacher_forbidden_slots.get(int(teacher_o), set()):
                    continue
                if teacher_e is not None and (weekday, period) in teacher_forbidden_slots.get(int(teacher_e), set()):
                    continue
                if teacher_busy(int(teacher_o) if teacher_o is not None else None, weekday, period, WeekParity.odd):
                    continue
                if teacher_busy(int(teacher_e) if teacher_e is not None else None, weekday, period, WeekParity.even):
                    continue
                if not evening_link_ok(int(teacher_o) if teacher_o is not None else None, weekday):
                    continue
                if not evening_link_ok(int(teacher_e) if teacher_e is not None else None, weekday):
                    continue
                if class_busy(class_id, weekday, period, WeekParity.odd, allow_activity=True):
                    continue
                if class_busy(class_id, weekday, period, WeekParity.even, allow_activity=True):
                    continue
                commit_pair(weekday, period)
                break
            if not placed:
                # 先试算整组落点；没有合法落点就不动，避免拆东墙补西墙。
                for weekday, period in evening_slots():
                    if not pair_may_use_day(weekday):
                        continue
                    if not pair_ok_on_required_head(weekday, period):
                        continue
                    if teacher_o is not None and (weekday, period) in teacher_forbidden_slots.get(int(teacher_o), set()):
                        continue
                    if teacher_e is not None and (weekday, period) in teacher_forbidden_slots.get(int(teacher_e), set()):
                        continue
                    if teacher_e is not None and teacher_busy(int(teacher_e), weekday, period, WeekParity.even):
                        continue
                    if not evening_link_ok(int(teacher_o) if teacher_o is not None else None, weekday):
                        continue
                    if not evening_link_ok(int(teacher_e) if teacher_e is not None else None, weekday):
                        continue
                    if teacher_o is None:
                        continue
                    if class_busy(class_id, weekday, period, WeekParity.odd, allow_activity=True):
                        continue
                    if class_busy(class_id, weekday, period, WeekParity.even, allow_activity=True):
                        continue
                    blockers = [
                        item for item in working
                        if item.teacher_id == int(teacher_o)
                        and item.weekday == weekday
                        and item.period == period
                        and parity_conflicts(item.week_parity, WeekParity.odd)
                    ]
                    if not blockers:
                        continue
                    plans: list[tuple[list[ScheduleItem], tuple[str, int, int, list[ScheduleItem]]]] = []
                    feasible = True
                    for blocker_class in sorted({item.class_id for item in blockers}):
                        group = [
                            item for item in working
                            if item.class_id == blocker_class
                            and item.weekday == weekday
                            and item.period == period
                            and item.teacher_id is not None
                        ]
                        plan = find_relocate_plan(group)
                        if plan is None:
                            feasible = False
                            break
                        plans.append((group, plan))
                    if not feasible:
                        continue
                    before = list(working)
                    before_pins = {key: set(days) for key, days in free_evening_days.items()}
                    for group, plan in plans:
                        apply_relocate_plan(group, plan)
                    if teacher_busy(int(teacher_o), weekday, period, WeekParity.odd):
                        working[:] = before
                        free_evening_days.clear()
                        free_evening_days.update(before_pins)
                        continue
                    commit_pair(weekday, period)
                    break
            if not placed:
                working.extend(saved_legs)

    def plan_need(row: Mapping[str, Any], parity: WeekParity) -> int:
        return plan_evening_count_for_parity(row, parity)

    def have_leg(class_id: int, subject_id: int, parity: WeekParity) -> int:
        return sum(
            1 for item in working
            if item.class_id == class_id
            and item.subject_id == subject_id
            and item.period >= first_evening_period
            and (item.week_parity is parity or item.week_parity is WeekParity.all)
        )

    def try_place_leg(
        assignment: Mapping[str, Any],
        *,
        weekday: int,
        period: int,
        parity: WeekParity,
        ignore: set[int] | None = None,
    ) -> bool:
        class_id = int(assignment["class_id"])
        subject_id = int(assignment["subject_id"])
        teacher_id = assignment.get("teacher_id")
        if weekday in free_evening_days.get(class_id, set()):
            return False
        if teacher_banned(int(teacher_id) if teacher_id is not None else None, weekday, period):
            return False
        if not evening_link_ok(int(teacher_id) if teacher_id is not None else None, weekday):
            return False
        # 偏好星期在候选日排序中优先，这里不硬拒，避免补课失败留下空晚。
        if teacher_busy(
            int(teacher_id) if teacher_id is not None else None,
            weekday,
            period,
            parity,
            ignore=ignore,
        ):
            return False
        if class_busy(class_id, weekday, period, parity, allow_activity=True):
            return False
        head_id = required_teacher_by_slot.get((weekday, period), {}).get(class_id)
        if head_id is not None and (teacher_id is None or int(teacher_id) != int(head_id)):
            return False
        clear_activity(class_id, weekday, period)
        working.append(ScheduleItem(
            assignment_id=int(assignment.get("id") or 0),
            class_id=class_id,
            subject_id=subject_id,
            teacher_id=int(teacher_id) if teacher_id is not None else None,
            weekday=weekday,
            period=period,
            room=assignment.get("room"),
            week_parity=parity,
        ))
        return True

    def strip_unpaired_half_legs(
        class_id: int,
        odd_sid: int,
        even_sid: int,
        odd_parity: WeekParity,
        even_parity: WeekParity,
    ) -> None:
        """去掉未同日落成的对课半截，避免钉死错误日子。"""
        odd_slots = {
            (item.weekday, item.period)
            for item in working
            if item.class_id == class_id and item.subject_id == odd_sid
            and item.period >= first_evening_period and item.week_parity is odd_parity
        }
        even_slots = {
            (item.weekday, item.period)
            for item in working
            if item.class_id == class_id and item.subject_id == even_sid
            and item.period >= first_evening_period and item.week_parity is even_parity
        }
        shared = odd_slots & even_slots
        if odd_slots <= shared and even_slots <= shared:
            return
        working[:] = [
            item for item in working
            if not (
                item.class_id == class_id
                and item.period >= first_evening_period
                and (
                    (item.subject_id == odd_sid and item.week_parity is odd_parity
                     and (item.weekday, item.period) not in shared)
                    or (item.subject_id == even_sid and item.week_parity is even_parity
                        and (item.weekday, item.period) not in shared)
                )
            )
        ]

    def try_displace_class_block(class_id: int, weekday: int, period: int) -> bool:
        """把占着目标晚课位的整组（整周课或完整对课）挪走，腾出位置。"""
        group = [
            item for item in items_at(class_id, weekday, period)
            if item.teacher_id is not None
            and (activity_subject_id is None or item.subject_id != activity_subject_id)
        ]
        if not group:
            clear_activity(class_id, weekday, period)
            return True
        # 班主任保留位上的班主任课（整周同科或单双拼格）不能被挤走。
        if group_pins_required_head(group):
            return False
        # 硬偏好教师已在偏好日上的课，不能被挤走。
        if group_pinned_by_pref(group):
            return False
        if not group_is_complete_block(group):
            # 半截对课钉死课位会挡住强制对课（如物|史）：拆掉半截，留给后续重排。
            if group and all(int(item.subject_id) in half_pair_subjects for item in group):
                for item in list(group):
                    if item in working:
                        working.remove(item)
                clear_activity(class_id, weekday, period)
                return True
            return False
        plan = find_relocate_plan(group)
        if plan is None:
            return False
        apply_relocate_plan(group, plan)
        return True

    # --- 按数据库课时方案补齐晚课缺额（先贴对课缺腿，再补整周晚课） ---
    for class_id in _class_ids_for_pairs:
        for subject_a, subject_b in iter_evening_pairs(class_id):
            assign_a = next((row for row in assignment_rows if int(row["class_id"]) == class_id and int(row["subject_id"]) == subject_a), None)
            assign_b = next((row for row in assignment_rows if int(row["class_id"]) == class_id and int(row["subject_id"]) == subject_b), None)
            if assign_a is None or assign_b is None:
                continue
            orientations = []
            if plan_need(assign_a, WeekParity.odd) > 0 and plan_need(assign_b, WeekParity.even) > 0:
                orientations.append((assign_a, assign_b, WeekParity.odd, WeekParity.even))
            if plan_need(assign_a, WeekParity.even) > 0 and plan_need(assign_b, WeekParity.odd) > 0:
                orientations.append((assign_b, assign_a, WeekParity.odd, WeekParity.even))
            for odd_assign, even_assign, odd_parity, even_parity in orientations:
                odd_sid, even_sid = int(odd_assign["subject_id"]), int(even_assign["subject_id"])
                strip_unpaired_half_legs(class_id, odd_sid, even_sid, odd_parity, even_parity)
                while have_leg(class_id, odd_sid, odd_parity) < plan_need(odd_assign, odd_parity) or (
                    have_leg(class_id, even_sid, even_parity) < plan_need(even_assign, even_parity)
                ):
                    odd_slots = {
                        (item.weekday, item.period)
                        for item in working
                        if item.class_id == class_id and item.subject_id == odd_sid
                        and item.period >= first_evening_period
                        and item.week_parity is odd_parity
                    }
                    even_slots = {
                        (item.weekday, item.period)
                        for item in working
                        if item.class_id == class_id and item.subject_id == even_sid
                        and item.period >= first_evening_period
                        and item.week_parity is even_parity
                    }
                    progressed = False
                    if odd_slots and have_leg(class_id, even_sid, even_parity) < plan_need(even_assign, even_parity):
                        for weekday, period in sorted(odd_slots):
                            if try_place_leg(even_assign, weekday=weekday, period=period, parity=even_parity):
                                progressed = True
                                break
                    if even_slots and have_leg(class_id, odd_sid, odd_parity) < plan_need(odd_assign, odd_parity):
                        for weekday, period in sorted(even_slots):
                            if try_place_leg(odd_assign, weekday=weekday, period=period, parity=odd_parity):
                                progressed = True
                                break
                    if (
                        have_leg(class_id, odd_sid, odd_parity) < plan_need(odd_assign, odd_parity)
                        and have_leg(class_id, even_sid, even_parity) < plan_need(even_assign, even_parity)
                    ):
                        pair_slots = sorted(
                            evening_slots(),
                            key=lambda slot: (
                                0 if teacher_pref_day_ok(odd_assign.get("teacher_id"), slot[0]) else 1,
                                0 if teacher_pref_day_ok(even_assign.get("teacher_id"), slot[0]) else 1,
                                slot[0],
                                slot[1],
                            ),
                        )
                        for weekday, period in pair_slots:
                            if weekday in free_evening_days.get(class_id, set()):
                                continue
                            if class_busy(class_id, weekday, period, odd_parity, allow_activity=True) or class_busy(
                                class_id, weekday, period, even_parity, allow_activity=True
                            ):
                                # 被整周语数英等占住时，先整组挪走再落对课。
                                if not try_displace_class_block(class_id, weekday, period):
                                    continue
                            if class_busy(class_id, weekday, period, odd_parity, allow_activity=True):
                                continue
                            if class_busy(class_id, weekday, period, even_parity, allow_activity=True):
                                continue
                            # 教师在别班同晚占位时，先整组挪开对方班级，再落本班对课。
                            teacher_o = odd_assign.get("teacher_id")
                            teacher_e = even_assign.get("teacher_id")
                            blocker_plans: list[
                                tuple[list[ScheduleItem], tuple[str, int, int, list[ScheduleItem]]]
                            ] = []
                            feasible_blockers = True
                            for tid, parity in (
                                (teacher_o, odd_parity),
                                (teacher_e, even_parity),
                            ):
                                if tid is None:
                                    continue
                                blockers = [
                                    item for item in working
                                    if item.teacher_id == int(tid)
                                    and item.weekday == weekday
                                    and item.period == period
                                    and parity_conflicts(item.week_parity, parity)
                                ]
                                for blocker_class in sorted({item.class_id for item in blockers}):
                                    if int(blocker_class) == int(class_id):
                                        continue
                                    group = [
                                        item for item in working
                                        if item.class_id == blocker_class
                                        and item.weekday == weekday
                                        and item.period == period
                                        and item.teacher_id is not None
                                        and (
                                            activity_subject_id is None
                                            or item.subject_id != activity_subject_id
                                        )
                                    ]
                                    plan = find_relocate_plan(group)
                                    if plan is None:
                                        feasible_blockers = False
                                        break
                                    blocker_plans.append((group, plan))
                                if not feasible_blockers:
                                    break
                            if not feasible_blockers:
                                continue
                            before = list(working)
                            before_pins = {key: set(days) for key, days in free_evening_days.items()}
                            for group, plan in blocker_plans:
                                apply_relocate_plan(group, plan)
                            if not try_place_leg(odd_assign, weekday=weekday, period=period, parity=odd_parity):
                                working[:] = before
                                free_evening_days.clear()
                                free_evening_days.update(before_pins)
                                continue
                            if try_place_leg(even_assign, weekday=weekday, period=period, parity=even_parity):
                                progressed = True
                                break
                            # 单腿失败则整段回滚，避免拆东墙后留下半截。
                            working[:] = before
                            free_evening_days.clear()
                            free_evening_days.update(before_pins)
                    if not progressed:
                        break

    for assignment in assignment_rows:
        class_id = int(assignment["class_id"])
        subject_id = int(assignment["subject_id"])
        odd_need = plan_need(assignment, WeekParity.odd)
        even_need = plan_need(assignment, WeekParity.even)
        if odd_need <= 0 or even_need <= 0:
            continue
        while (
            have_leg(class_id, subject_id, WeekParity.odd) < odd_need
            or have_leg(class_id, subject_id, WeekParity.even) < even_need
        ):
            placed_full = False
            for weekday, period in evening_slots():
                if weekday in free_evening_days.get(class_id, set()):
                    continue
                teacher_id = assignment.get("teacher_id")
                if teacher_banned(int(teacher_id) if teacher_id is not None else None, weekday, period):
                    continue
                if not evening_link_ok(int(teacher_id) if teacher_id is not None else None, weekday):
                    continue
                if teacher_busy(
                    int(teacher_id) if teacher_id is not None else None, weekday, period, WeekParity.odd
                ) or teacher_busy(
                    int(teacher_id) if teacher_id is not None else None, weekday, period, WeekParity.even
                ):
                    continue
                if class_busy(class_id, weekday, period, WeekParity.odd, allow_activity=True):
                    continue
                if class_busy(class_id, weekday, period, WeekParity.even, allow_activity=True):
                    continue
                head_id = required_teacher_by_slot.get((weekday, period), {}).get(class_id)
                if head_id is not None and (teacher_id is None or int(teacher_id) != int(head_id)):
                    continue
                clear_activity(class_id, weekday, period)
                working.append(ScheduleItem(
                    assignment_id=int(assignment.get("id") or 0),
                    class_id=class_id,
                    subject_id=subject_id,
                    teacher_id=int(teacher_id) if teacher_id is not None else None,
                    weekday=weekday,
                    period=period,
                    room=assignment.get("room"),
                    week_parity=WeekParity.all,
                ))
                placed_full = True
                break
            if not placed_full:
                break

    # --- Evening↔daytime link: 整组挪晚课（对课单双腿一起走，避免拆对） ---
    for link in teacher_evening_daytime_links:
        teacher_id = int(link["teacher_id"])
        evening_start = int(link.get("evening_start_period") or first_evening_period)
        required_period = int(link["required_daytime_period"])
        evening_items = [
            item for item in working
            if item.teacher_id == teacher_id and item.period >= evening_start
        ]
        for eve in list(evening_items):
            if eve not in working:
                continue
            if _daytime_link_satisfied(
                [*anchor, *working],
                teacher_id=teacher_id,
                weekday=eve.weekday,
                evening_start=evening_start,
                required_period=required_period,
            ):
                continue
            group = [
                item for item in items_at(eve.class_id, eve.weekday, eve.period)
                if item.teacher_id is not None
                and (activity_subject_id is None or item.subject_id != activity_subject_id)
            ]
            if not group:
                group = [eve]
            elif eve.subject_id in half_pair_subjects and not group_is_complete_block(group):
                # 半截对课不单腿挪，留给对课补齐逻辑处理。
                continue
            candidate_days = sorted({
                item.weekday for item in [*anchor, *working]
                if item.teacher_id == teacher_id and item.period < evening_start
            })
            for weekday in candidate_days:
                if weekday == eve.weekday:
                    continue
                if not _daytime_link_satisfied(
                    [*anchor, *working],
                    teacher_id=teacher_id,
                    weekday=weekday,
                    evening_start=evening_start,
                    required_period=required_period,
                ):
                    continue
                period = eve.period
                if weekday in free_evening_days.get(eve.class_id, set()):
                    continue
                skip = {id(item) for item in group}
                if any(
                    teacher_busy(item.teacher_id, weekday, period, item.week_parity, ignore=skip)
                    or class_busy(item.class_id, weekday, period, item.week_parity, allow_activity=True)
                    or teacher_banned(item.teacher_id, weekday, period)
                    or not evening_link_ok(item.teacher_id, weekday)
                    for item in group
                ):
                    continue
                if not try_displace_class_block(eve.class_id, weekday, period) and any(
                    class_busy(eve.class_id, weekday, period, item.week_parity, allow_activity=True)
                    for item in group
                ):
                    continue
                origin_day, origin_period = eve.weekday, eve.period
                clear_activity(eve.class_id, weekday, period)
                for item in list(group):
                    if item in working:
                        working.remove(item)
                        working.append(replace(item, weekday=weekday))
                fill_leftover_activity(eve.class_id, origin_day, origin_period, WeekParity.odd)
                fill_leftover_activity(eve.class_id, origin_day, origin_period, WeekParity.even)
                fill_leftover_activity(eve.class_id, origin_day, origin_period, WeekParity.all)
                break

    # --- Teacher forbidden evening slots: 挪位，不把学科改成自习 ---
    for teacher_id, forbidden in teacher_forbidden_slots.items():
        evening_forbidden = {
            (weekday, period)
            for weekday, period in forbidden
            if period >= first_evening_period
        }
        if not evening_forbidden:
            continue
        allowed_days = sorted({
            weekday
            for weekday in range(1, 8)
            if (weekday, first_evening_period) not in evening_forbidden
        })
        for eve in list(
            item for item in working
            if item.teacher_id == int(teacher_id)
            and item.period >= first_evening_period
            and (item.weekday, item.period) in evening_forbidden
        ):
            moved = False
            for weekday in allowed_days:
                period = eve.period
                if teacher_busy(int(teacher_id), weekday, period, eve.week_parity):
                    continue
                if class_busy(eve.class_id, weekday, period, eve.week_parity, allow_activity=True):
                    continue
                if weekday in free_evening_days.get(eve.class_id, set()):
                    continue
                if (weekday, period) in evening_forbidden:
                    continue
                clear_activity(eve.class_id, weekday, period)
                working.remove(eve)
                fill_leftover_activity(eve.class_id, eve.weekday, eve.period, eve.week_parity)
                working.append(replace(eve, weekday=weekday))
                moved = True
                break
            if moved:
                continue
            for other in list(working):
                if (
                    other is eve
                    or other.teacher_id is None
                    or other.period < first_evening_period
                    or other.period != eve.period
                    or other.weekday not in allowed_days
                    or other.weekday in free_evening_days.get(eve.class_id, set())
                    or eve.weekday in free_evening_days.get(other.class_id, set())
                    or teacher_banned(other.teacher_id, eve.weekday, eve.period)
                    or teacher_banned(eve.teacher_id, other.weekday, other.period)
                ):
                    continue
                working.remove(eve)
                working.remove(other)
                can_swap = (
                    not teacher_busy(int(eve.teacher_id), other.weekday, other.period, eve.week_parity)
                    and not teacher_busy(int(other.teacher_id), eve.weekday, eve.period, other.week_parity)
                    and not class_busy(eve.class_id, other.weekday, other.period, eve.week_parity, allow_activity=True)
                    and not class_busy(other.class_id, eve.weekday, eve.period, other.week_parity, allow_activity=True)
                )
                if not can_swap:
                    working.append(eve)
                    working.append(other)
                    continue
                clear_activity(eve.class_id, other.weekday, other.period)
                clear_activity(other.class_id, eve.weekday, eve.period)
                working.append(replace(eve, weekday=other.weekday))
                working.append(replace(other, weekday=eve.weekday))
                moved = True
                break

    # --- 班主任保留位：必须是班主任任教学科（整周同科，或单双周拼格另一科） ---
    for (weekday, period), class_heads in required_teacher_by_slot.items():
        for class_id, head_id in class_heads.items():
            head_id = int(head_id)
            here = items_at(class_id, weekday, period)
            if any(item.teacher_id == head_id for item in here):
                continue
            head_assigns = [
                row for row in assignment_rows
                if int(row["class_id"]) == class_id
                and row.get("teacher_id") is not None
                and int(row["teacher_id"]) == head_id
                and (plan_need(row, WeekParity.odd) > 0 or plan_need(row, WeekParity.even) > 0)
            ]
            if not head_assigns:
                continue
            head_assigns.sort(
                key=lambda row: (
                    0 if plan_need(row, WeekParity.odd) > 0 and plan_need(row, WeekParity.even) > 0 else 1,
                    int(row["subject_id"]),
                )
            )
            occupants = [
                item for item in here
                if item.teacher_id is not None
                and (activity_subject_id is None or item.subject_id != activity_subject_id)
            ]
            if occupants and not try_displace_class_block(class_id, weekday, period):
                for item in list(occupants):
                    if item in working and item.teacher_id != head_id:
                        working.remove(item)
            clear_activity(class_id, weekday, period)
            placed_head = False
            for assignment in head_assigns:
                sid = int(assignment["subject_id"])
                odd_need = plan_need(assignment, WeekParity.odd)
                even_need = plan_need(assignment, WeekParity.even)
                # 已排在别处的班主任晚课：整组挪到保留位，不重复占课时。
                existing = [
                    item for item in working
                    if item.class_id == class_id
                    and item.subject_id == sid
                    and item.teacher_id == head_id
                    and item.period >= first_evening_period
                ]
                if existing and odd_need > 0 and even_need > 0:
                    if teacher_banned(head_id, weekday, period) or not evening_link_ok(head_id, weekday):
                        continue
                    if teacher_busy(head_id, weekday, period, WeekParity.odd, ignore={id(i) for i in existing}) or teacher_busy(
                        head_id, weekday, period, WeekParity.even, ignore={id(i) for i in existing}
                    ):
                        continue
                    origin = (existing[0].weekday, existing[0].period)
                    for item in list(existing):
                        working.remove(item)
                        working.append(replace(item, weekday=weekday, period=period))
                    fill_leftover_activity(class_id, origin[0], origin[1], WeekParity.odd)
                    fill_leftover_activity(class_id, origin[0], origin[1], WeekParity.even)
                    fill_leftover_activity(class_id, origin[0], origin[1], WeekParity.all)
                    placed_head = True
                    break
                if odd_need > 0 and even_need > 0:
                    if have_leg(class_id, sid, WeekParity.odd) >= odd_need:
                        continue
                    if teacher_banned(head_id, weekday, period):
                        continue
                    if teacher_busy(head_id, weekday, period, WeekParity.odd) or teacher_busy(
                        head_id, weekday, period, WeekParity.even
                    ):
                        continue
                    if not evening_link_ok(head_id, weekday):
                        continue
                    working.append(ScheduleItem(
                        assignment_id=int(assignment.get("id") or 0),
                        class_id=class_id,
                        subject_id=sid,
                        teacher_id=head_id,
                        weekday=weekday,
                        period=period,
                        room=assignment.get("room"),
                        week_parity=WeekParity.all,
                    ))
                    placed_head = True
                    break
                # 0.5：班主任一腿 + 另一科拼格（单双周不同课，如单物双历）
                head_parity = WeekParity.odd if odd_need > 0 else WeekParity.even
                other_parity = WeekParity.even if head_parity is WeekParity.odd else WeekParity.odd
                if have_leg(class_id, sid, head_parity) >= max(odd_need, even_need):
                    # 已有半腿：尽量连同搭档挪到保留位。
                    head_leg = next(
                        (
                            item for item in working
                            if item.class_id == class_id and item.subject_id == sid
                            and item.period >= first_evening_period and item.week_parity is head_parity
                        ),
                        None,
                    )
                    if head_leg is None:
                        continue
                    partner_leg = next(
                        (
                            item for item in working
                            if item.class_id == class_id
                            and item.weekday == head_leg.weekday
                            and item.period == head_leg.period
                            and item.week_parity is other_parity
                            and item.teacher_id is not None
                        ),
                        None,
                    )
                    group = [head_leg] + ([partner_leg] if partner_leg else [])
                    if teacher_banned(head_id, weekday, period) or not evening_link_ok(head_id, weekday):
                        continue
                    skip = {id(i) for i in group}
                    if any(
                        teacher_busy(i.teacher_id, weekday, period, i.week_parity, ignore=skip)
                        for i in group
                    ):
                        continue
                    origin_day, origin_period = head_leg.weekday, head_leg.period
                    clear_activity(class_id, weekday, period)
                    for item in group:
                        working.remove(item)
                        working.append(replace(item, weekday=weekday, period=period))
                    fill_leftover_activity(class_id, origin_day, origin_period, WeekParity.odd)
                    fill_leftover_activity(class_id, origin_day, origin_period, WeekParity.even)
                    placed_head = True
                    break
                if not try_place_leg(assignment, weekday=weekday, period=period, parity=head_parity):
                    continue
                partner_row = next(
                    (
                        row for row in assignment_rows
                        if int(row["class_id"]) == class_id
                        and int(row["subject_id"]) != sid
                        and plan_need(row, other_parity) > 0
                        and plan_need(row, head_parity) <= 0
                        and have_leg(class_id, int(row["subject_id"]), other_parity) < plan_need(row, other_parity)
                    ),
                    None,
                )
                if partner_row is not None and not try_place_leg(
                    partner_row, weekday=weekday, period=period, parity=other_parity
                ):
                    working[:] = [
                        item for item in working
                        if not (
                            item.class_id == class_id
                            and item.subject_id == sid
                            and item.weekday == weekday
                            and item.period == period
                            and item.week_parity is head_parity
                        )
                    ]
                    continue
                placed_head = True
                break
            if not placed_head and activity_subject_id is not None:
                clear_activity(class_id, weekday, period)
                working.append(ScheduleItem(
                    assignment_id=0,
                    class_id=class_id,
                    subject_id=activity_subject_id,
                    teacher_id=head_id,
                    weekday=weekday,
                    period=period,
                    room=None,
                    week_parity=WeekParity.all,
                ))

    # --- 班级晚课自习日：候选日中恰好保留 choose_count 天无学科教师课 ---
    def day_has_subject_teacher(class_id: int, weekday: int) -> bool:
        return any(
            item.class_id == class_id
            and item.weekday == weekday
            and item.period >= first_evening_period
            and item.teacher_id is not None
            and (activity_subject_id is None or item.subject_id != activity_subject_id)
            for item in working
        )

    def clear_day_to_self_study(class_id: int, weekday: int) -> None:
        for item in list(working):
            if (
                item.class_id != class_id
                or item.weekday != weekday
                or item.period < first_evening_period
                or item.teacher_id is None
                or (activity_subject_id is not None and item.subject_id == activity_subject_id)
            ):
                continue
            group = [
                row for row in working
                if row.class_id == class_id
                and row.weekday == weekday
                and row.period == item.period
                and row.teacher_id is not None
                and (activity_subject_id is None or row.subject_id != activity_subject_id)
            ]
            plan = find_relocate_plan(group) if group_is_complete_block(group) else None
            if plan is not None:
                apply_relocate_plan(group, plan)
                continue
            for row in group:
                working.remove(row)
            fill_leftover_activity(class_id, weekday, item.period, WeekParity.odd)
            fill_leftover_activity(class_id, weekday, item.period, WeekParity.even)
            fill_leftover_activity(class_id, weekday, item.period, WeekParity.all)

    enforce_classes = set(study_candidates) | set(self_study_choose) | set(free_evening_days)
    for class_id in sorted(enforce_classes):
        candidates = sorted(class_study_candidates(class_id) or free_evening_days.get(class_id, set()))
        if not candidates:
            continue
        choose = int(self_study_choose.get(class_id) or len(free_evening_days.get(class_id, set())) or 1)
        free_days = [day for day in candidates if not day_has_subject_teacher(class_id, day)]
        if len(free_days) == choose:
            free_evening_days[class_id] = set(free_days)
            continue
        if len(free_days) > choose:
            # 自习过多：保留靠后的 choose 天，其余不动（由课时补齐逻辑占满）。
            keep = set(sorted(free_days)[-choose:])
            free_evening_days[class_id] = keep
            continue
        preferred = list(free_evening_days.get(class_id, set())) + sorted(candidates, reverse=True)
        seen_days: set[int] = set()
        for day in preferred:
            if day in seen_days or day not in candidates:
                continue
            seen_days.add(day)
            if not day_has_subject_teacher(class_id, day):
                continue
            clear_day_to_self_study(class_id, day)
            free_days = [d for d in candidates if not day_has_subject_teacher(class_id, d)]
            if len(free_days) >= choose:
                break
        free_evening_days[class_id] = set(
            sorted(d for d in candidates if not day_has_subject_teacher(class_id, d))[-choose:]
        )

    # --- R15：多班教师晚课日压成连续段（固定钉位不挪）---
    multi_class_days: dict[int, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    for item in working:
        if (
            item.teacher_id is None
            or item.period < first_evening_period
            or (activity_subject_id is not None and item.subject_id == activity_subject_id)
        ):
            continue
        multi_class_days[int(item.teacher_id)][int(item.class_id)].add(int(item.weekday))
    for teacher_id, class_days in multi_class_days.items():
        active = {day for days in class_days.values() for day in days}
        if len([cid for cid, days in class_days.items() if days]) < 2:
            continue
        ordered = sorted(active)
        if len(ordered) < 2 or all(
            ordered[i + 1] - ordered[i] <= 1 for i in range(len(ordered) - 1)
        ):
            continue
        lo, hi = ordered[0], ordered[-1]
        holes = [day for day in range(lo, hi + 1) if day not in active]
        outliers = [
            day for day in ordered
            if day != lo and day != hi and (day - 1 not in active or day + 1 not in active)
        ]
        # 优先把「段外/断档侧」的整组挪进段内空档或贴边日。
        move_from_days = [day for day in reversed(ordered) if day == hi or day == lo] + outliers
        for from_day in move_from_days:
            offenders = [
                item for item in working
                if item.teacher_id == teacher_id
                and item.weekday == from_day
                and item.period >= first_evening_period
                and (activity_subject_id is None or item.subject_id != activity_subject_id)
            ]
            if not offenders:
                continue
            eve = offenders[0]
            group = [
                item for item in items_at(eve.class_id, eve.weekday, eve.period)
                if item.teacher_id is not None
                and (activity_subject_id is None or item.subject_id != activity_subject_id)
            ] or [eve]
            if group_pins_required_head(group):
                continue
            targets = list(holes) + [
                day for day in (lo - 1, hi + 1)
                if 1 <= day <= 6 and day not in active
            ]
            moved_here = False
            for weekday in targets:
                if weekday in free_evening_days.get(eve.class_id, set()):
                    continue
                period = eve.period
                if not group_can_sit(group, weekday, period):
                    continue
                if not try_displace_class_block(eve.class_id, weekday, period) and any(
                    class_busy(eve.class_id, weekday, period, item.week_parity, allow_activity=True)
                    for item in group
                ):
                    continue
                move_group(group, weekday, period)
                active.discard(from_day)
                active.add(weekday)
                holes = [day for day in range(min(active), max(active) + 1) if day not in active]
                moved_here = True
                break
            if moved_here and all(
                sorted(active)[i + 1] - sorted(active)[i] <= 1
                for i in range(len(active) - 1)
            ):
                break

    # --- 偏好星期（软）：偏好外的晚课尽量整组挪回偏好日；挪不动则保留，不掏空晚课 ---
    for teacher_id, allowed in preferred_days.items():
        offenders = [
            item for item in working
            if item.teacher_id == teacher_id
            and item.period >= first_evening_period
            and item.weekday not in allowed
            and (activity_subject_id is None or item.subject_id != activity_subject_id)
        ]
        for eve in list(offenders):
            if eve not in working:
                continue
            group = [
                item for item in items_at(eve.class_id, eve.weekday, eve.period)
                if item.teacher_id is not None
                and (activity_subject_id is None or item.subject_id != activity_subject_id)
            ]
            if not group:
                group = [eve]
            for weekday in sorted(allowed):
                if weekday == eve.weekday:
                    continue
                if weekday in free_evening_days.get(eve.class_id, set()):
                    continue
                period = eve.period
                skip = {id(item) for item in group}
                if any(
                    teacher_busy(item.teacher_id, weekday, period, item.week_parity, ignore=skip)
                    or class_busy(item.class_id, weekday, period, item.week_parity, allow_activity=True)
                    or teacher_banned(item.teacher_id, weekday, period)
                    or not evening_link_ok(item.teacher_id, weekday)
                    for item in group
                ):
                    continue
                if not try_displace_class_block(eve.class_id, weekday, period) and any(
                    class_busy(eve.class_id, weekday, period, item.week_parity, allow_activity=True)
                    for item in group
                ):
                    continue
                origin_day, origin_period = eve.weekday, eve.period
                clear_activity(eve.class_id, weekday, period)
                for item in list(group):
                    if item in working:
                        working.remove(item)
                        working.append(replace(item, weekday=weekday))
                fill_leftover_activity(eve.class_id, origin_day, origin_period, WeekParity.odd)
                fill_leftover_activity(eve.class_id, origin_day, origin_period, WeekParity.even)
                fill_leftover_activity(eve.class_id, origin_day, origin_period, WeekParity.all)
                break

    return working


def _resolve_evening_half_pairs(
    assignment_rows: list[dict[str, Any]],
    *,
    class_id: int,
    evening_count,
    pair_consumed: Mapping[tuple[int, WeekParity], int],
    declared_pairs: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Return (odd_subject_id, even_subject_id) pairs that still need a shared evening slot.

    规则声明的对课（如物|史）优先锁定；其余单侧 0.5（化/政/生/地等）按班级种子打乱后任意互配。
    """

    def remaining(subject_id: int, parity: WeekParity) -> int:
        assignment = next(
            (
                row for row in assignment_rows
                if int(row["class_id"]) == class_id and int(row["subject_id"]) == subject_id
            ),
            None,
        )
        if assignment is None:
            return 0
        return max(0, evening_count(assignment, parity) - int(pair_consumed[(subject_id, parity)]))

    pairs: list[tuple[int, int]] = []
    used_odd: set[int] = set()
    used_even: set[int] = set()

    for pair in _evening_half_pair_catalog(declared_pairs):
        for odd_subject, even_subject in (pair, (pair[1], pair[0])):
            if odd_subject in used_odd or even_subject in used_even:
                continue
            if remaining(odd_subject, WeekParity.odd) > 0 and remaining(even_subject, WeekParity.even) > 0:
                pairs.append((odd_subject, even_subject))
                used_odd.add(odd_subject)
                used_even.add(even_subject)
                break

    odd_left: list[int] = []
    even_left: list[int] = []
    for row in assignment_rows:
        if int(row["class_id"]) != class_id:
            continue
        subject_id = int(row["subject_id"])
        odd_rem = remaining(subject_id, WeekParity.odd)
        even_rem = remaining(subject_id, WeekParity.even)
        # 单双周都有剩余的是整周晚课，不走 0.5 对课。
        if odd_rem > 0 and even_rem > 0:
            continue
        if odd_rem > 0 and subject_id not in used_odd:
            odd_left.extend([subject_id] * odd_rem)
        if even_rem > 0 and subject_id not in used_even:
            even_left.extend([subject_id] * even_rem)

    # 非强制对课：按班级打乱后互配，避免永远固定成 化|政、生|地。
    rng = random.Random(class_id)
    rng.shuffle(odd_left)
    rng.shuffle(even_left)
    for odd_subject, even_subject in zip(odd_left, even_left):
        pairs.append((odd_subject, even_subject))

    return pairs


def build_evening_study_items(
    assignments: Iterable[dict[str, Any]],
    *,
    class_ids: Iterable[int],
    first_evening_period: int,
    evening_daily_periods_odd: list[int],
    evening_daily_periods_even: list[int],
    activity_subject_id: int | None = None,
    allowed_subject_ids: set[int] | None = None,
    allowed_subject_ids_odd: set[int] | None = None,
    allowed_subject_ids_even: set[int] | None = None,
    allowed_subject_ids_by_class_odd: dict[int, set[int]] | None = None,
    allowed_subject_ids_by_class_even: dict[int, set[int]] | None = None,
    required_teacher_by_slot: Mapping[tuple[int, int], Mapping[int, int]] | None = None,
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    parity_subject_pairs: list[tuple[int, int]] | None = None,
    free_evening_days: Mapping[int, set[int]] | None = None,
    anchor_items: Iterable[ScheduleItem] | None = None,
    teacher_evening_daytime_links: Iterable[Mapping[str, Any]] | None = None,
    teacher_preferred_evening_weekdays: Mapping[int, set[int]] | None = None,
    teacher_required_evening_weekdays: Mapping[int, set[int]] | None = None,
    r15_exclude_subject_ids: set[int] | None = None,
    r15_exclude_teacher_ids: set[int] | None = None,
    r15_enabled: bool = False,
    max_time_seconds: float = 60.0,
    num_search_workers: int = 8,
) -> list[ScheduleItem]:
    """晚课正式入口：与 API 相同，走 CP-SAT。

    仅当调用方仍传入旧的 allowed_subject_ids 学科池时，才走兼容分支。
    """
    assignment_rows = [dict(assignment) for assignment in assignments]
    preferred_days = {
        int(teacher_id): {int(day) for day in days}
        for teacher_id, days in (teacher_preferred_evening_weekdays or {}).items()
        if days
    }

    # Compatibility for callers that explicitly supplied the old subject-pool
    # arguments. New generation never uses this branch; it uses course-hour
    # evening counts and keeps the related teacher on the item.
    if any(value is not None for value in (
        allowed_subject_ids, allowed_subject_ids_odd, allowed_subject_ids_even,
        allowed_subject_ids_by_class_odd, allowed_subject_ids_by_class_even,
    )):
        legacy_subject_ids = allowed_subject_ids or set()
        pools = {
            WeekParity.odd: allowed_subject_ids_odd if allowed_subject_ids_odd is not None else legacy_subject_ids,
            WeekParity.even: allowed_subject_ids_even if allowed_subject_ids_even is not None else legacy_subject_ids,
        }
        class_pools = {
            WeekParity.odd: allowed_subject_ids_by_class_odd,
            WeekParity.even: allowed_subject_ids_by_class_even,
        }
        legacy_items: list[ScheduleItem] = []
        for class_id in sorted(set(class_ids)):
            for parity, daily_periods in (
                (WeekParity.odd, evening_daily_periods_odd),
                (WeekParity.even, evening_daily_periods_even),
            ):
                subject_pool = class_pools[parity].get(class_id, pools[parity]) if class_pools[parity] is not None else pools[parity]
                candidates = [
                    assignment for assignment in assignment_rows
                    if int(assignment["class_id"]) == class_id and int(assignment["subject_id"]) in subject_pool
                ]
                candidates.sort(key=lambda item: (int(item["subject_id"]), int(item.get("id") or 0)))
                if not candidates:
                    continue
                cursor = 0
                for weekday, count in enumerate(daily_periods, start=1):
                    for offset in range(count):
                        assignment = candidates[cursor % len(candidates)]
                        legacy_items.append(ScheduleItem(
                            assignment_id=int(assignment.get("id") or 0),
                            class_id=class_id,
                            subject_id=int(assignment["subject_id"]),
                            teacher_id=None,
                            weekday=weekday,
                            period=first_evening_period + offset,
                            room=assignment.get("room"),
                            week_parity=parity,
                        ))
                        cursor += 1
        return legacy_items

    from app.services.scheduling.evening_cpsat import generate_evening_schedule

    result = generate_evening_schedule(
        assignment_rows,
        class_ids=class_ids,
        first_evening_period=first_evening_period,
        evening_daily_periods_odd=evening_daily_periods_odd,
        evening_daily_periods_even=evening_daily_periods_even,
        activity_subject_id=None,
        required_teacher_by_slot=required_teacher_by_slot,
        teacher_forbidden_slots=teacher_forbidden_slots,
        class_slot_allowed_subjects=class_slot_allowed_subjects,
        parity_subject_pairs=parity_subject_pairs,
        free_evening_days=free_evening_days,
        anchor_items=anchor_items,
        teacher_evening_daytime_links=teacher_evening_daytime_links,
        teacher_preferred_evening_weekdays=teacher_preferred_evening_weekdays,
        teacher_required_evening_weekdays=teacher_required_evening_weekdays,
        r15_exclude_subject_ids=r15_exclude_subject_ids,
        r15_exclude_teacher_ids=r15_exclude_teacher_ids,
        r15_enabled=r15_enabled,
        max_time_seconds=max_time_seconds,
        num_search_workers=num_search_workers,
    )
    if result.status not in ("OPTIMAL", "FEASIBLE"):
        raise ValueError(f"晚课 CP-SAT 无解或超时：{result.status}")
    return list(result.items)

    items: list[ScheduleItem] = []
    occupied_teacher_slots: set[tuple[int, int, int, WeekParity]] = set()
    # R15：教师已占用的晚课日，落位时优先填洞/向两端延伸，形成「一班一天连续铺开」。
    teacher_evening_days: dict[int, set[int]] = defaultdict(set)
    required_teachers = required_teacher_by_slot or {}
    class_allowed = class_slot_allowed_subjects or {}
    free_days = free_evening_days or {}
    anchor_rows = list(anchor_items or ())
    link_by_teacher = {
        int(link["teacher_id"]): link
        for link in (teacher_evening_daytime_links or [])
    }
    class_id_set = {int(class_id) for class_id in class_ids}

    def _assignment_has_evening(row: Mapping[str, Any]) -> bool:
        return (
            max(0, int(row.get("evening_periods_odd") or 0)) > 0
            or max(0, int(row.get("evening_periods_even") or 0)) > 0
        )

    # 带晚课班数越多的教师约束越紧：其所在班级越先排（规则多的先排）。
    evening_classes_by_teacher: dict[int, set[int]] = defaultdict(set)
    for row in assignment_rows:
        if row.get("teacher_id") is None or not _assignment_has_evening(row):
            continue
        cid = int(row["class_id"])
        if cid in class_id_set:
            evening_classes_by_teacher[int(row["teacher_id"])].add(cid)
    class_pack_pressure = {
        cid: max(
            (
                len(evening_classes_by_teacher[int(row["teacher_id"])])
                for row in assignment_rows
                if int(row["class_id"]) == cid
                and row.get("teacher_id") is not None
                and _assignment_has_evening(row)
            ),
            default=0,
        )
        for cid in class_id_set
    }

    def slot_forbidden_for(class_id: int, subject_id: int, weekday: int, period: int) -> bool:
        allowed = class_allowed.get(class_id, {}).get((weekday, period))
        return allowed is not None and subject_id not in allowed

    def day_reserved_for(class_id: int, weekday: int) -> bool:
        # 自习保留日：不给该班排教师带领的晚课（activity 自习除外，由调用方区分）。
        return weekday in free_days.get(class_id, set())

    def teacher_day_pack_rank(teacher_id: int | None, weekday: int) -> tuple[int, int]:
        """晚课日打包分：越小越好。先填段内空档，再向两端延伸。"""
        if teacher_id is None:
            return (0, int(weekday))
        days = teacher_evening_days.get(int(teacher_id), set())
        day = int(weekday)
        if not days:
            return (0, day)
        if day in days:
            return (3, day)
        lo, hi = min(days), max(days)
        if lo <= day <= hi:
            return (0, day)
        if day == lo - 1 or day == hi + 1:
            return (1, day)
        return (2 + min(abs(day - lo), abs(day - hi)), day)

    def note_teacher_evening_day(teacher_id: int | None, weekday: int) -> None:
        if teacher_id is None:
            return
        teacher_evening_days.setdefault(int(teacher_id), set()).add(int(weekday))

    def teacher_daytime_link_ok(teacher_id: int | None, weekday: int) -> bool:
        if teacher_id is None:
            return True
        link = link_by_teacher.get(int(teacher_id))
        if link is None:
            return True
        evening_start = int(link.get("evening_start_period") or first_evening_period)
        required_period = int(link["required_daytime_period"])
        return any(
            item.teacher_id == int(teacher_id)
            and item.weekday == weekday
            and item.period < evening_start
            and item.period == required_period
            for item in anchor_rows
        )

    def teacher_preferred_day_ok(teacher_id: int | None, weekday: int) -> bool:
        if teacher_id is None:
            return True
        allowed = preferred_days.get(int(teacher_id))
        return allowed is None or int(weekday) in allowed

    def evening_count(assignment: dict[str, Any], parity: WeekParity) -> int:
        return plan_evening_count_for_parity(assignment, parity)

    for class_id in sorted(
        class_id_set,
        key=lambda cid: (-class_pack_pressure.get(cid, 0), cid),
    ):
        slots_by_parity: dict[WeekParity, list[tuple[int, int]]] = {}
        reserved_by_parity: dict[WeekParity, set[tuple[int, int]]] = {}
        for parity, daily_periods in (
            (WeekParity.odd, evening_daily_periods_odd),
            (WeekParity.even, evening_daily_periods_even),
        ):
            slots = [
                (weekday, first_evening_period + offset)
                for weekday, count in enumerate(daily_periods, start=1)
                for offset in range(count)
            ]
            slots_by_parity[parity] = slots
            reserved_by_parity[parity] = {
                slot for slot in slots
                if class_id in required_teachers.get(slot, {})
            }

        # 同一任教关系同时配置单周和双周晚课时，表示“每周一节晚课”，
        # 应合并为一个独立的每周课位；单侧 0.5 禁止单腿乱落（强制对课优先，其余任意互配）。
        used_class_slots: set[tuple[int, int]] = set()
        parity_subject_ids = _half_evening_subject_ids(
            assignment_rows, class_id=class_id, evening_count_fn=evening_count
        ) | _evening_half_pair_subject_ids(parity_subject_pairs)
        consolidated_subjects: set[int] = set()
        pair_positions: dict[WeekParity, set[int]] = {WeekParity.odd: set(), WeekParity.even: set()}
        pair_consumed: dict[tuple[int, WeekParity], int] = defaultdict(int)

        def assignment_for(subject_id: int) -> dict[str, Any] | None:
            return next(
                (
                    row for row in assignment_rows
                    if int(row["class_id"]) == class_id and int(row["subject_id"]) == subject_id
                ),
                None,
            )

        def remaining_evening(assignment: Mapping[str, Any], parity: WeekParity) -> int:
            subject_id = int(assignment["subject_id"])
            return evening_count(assignment, parity) - pair_consumed[(subject_id, parity)]

        def place_evening_leg(
            assignment: Mapping[str, Any],
            *,
            weekday: int,
            period: int,
            parity: WeekParity,
        ) -> bool:
            subject_id = int(assignment["subject_id"])
            teacher_id = assignment.get("teacher_id")
            if remaining_evening(assignment, parity) <= 0:
                return False
            if slot_forbidden_for(class_id, subject_id, weekday, period):
                return False
            if teacher_id is not None and (weekday, period) in (teacher_forbidden_slots or {}).get(int(teacher_id), set()):
                return False
            # 晚课偏好星期只做排序优先，不在此硬拒，避免掏空班级晚课。
            if not teacher_daytime_link_ok(
                int(teacher_id) if teacher_id is not None else None, weekday
            ):
                return False
            teacher_slot = (
                (int(teacher_id), weekday, period, parity)
                if teacher_id is not None else None
            )
            if teacher_slot is not None and teacher_slot in occupied_teacher_slots:
                return False
            items.append(ScheduleItem(
                assignment_id=int(assignment.get("id") or 0),
                class_id=class_id,
                subject_id=subject_id,
                teacher_id=int(teacher_id) if teacher_id is not None else None,
                weekday=weekday,
                period=period,
                room=assignment.get("room"),
                week_parity=parity,
            ))
            note_teacher_evening_day(teacher_id, weekday)
            if teacher_slot is not None:
                occupied_teacher_slots.add(teacher_slot)
            pair_consumed[(subject_id, parity)] += 1
            return True

        def undo_evening_leg(
            assignment: Mapping[str, Any],
            *,
            weekday: int,
            period: int,
            parity: WeekParity,
        ) -> None:
            subject_id = int(assignment["subject_id"])
            teacher_id = assignment.get("teacher_id")
            for idx in range(len(items) - 1, -1, -1):
                item = items[idx]
                if (
                    item.class_id == class_id
                    and item.subject_id == subject_id
                    and item.weekday == weekday
                    and item.period == period
                    and item.week_parity is parity
                ):
                    items.pop(idx)
                    break
            if pair_consumed[(subject_id, parity)] > 0:
                pair_consumed[(subject_id, parity)] -= 1
            if teacher_id is not None:
                occupied_teacher_slots.discard((int(teacher_id), weekday, period, parity))

        def partner_for_half(subject_id: int, head_parity: WeekParity) -> tuple[dict[str, Any], WeekParity] | None:
            """找另一侧 0.5：规则强制搭档优先，否则任意剩余单侧学科。

            不得抢占「已规则绑定给其它学科」的对课腿（例如班主任化学位不能先占历史，
            否则物|史强制对课永远拼不满）。
            """
            other = WeekParity.even if head_parity is WeekParity.odd else WeekParity.odd
            declared = _evening_half_pair_catalog(parity_subject_pairs)
            for pair in declared:
                if subject_id not in pair:
                    continue
                partner_id = int(pair[0] if int(pair[1]) == subject_id else pair[1])
                partner = assignment_for(partner_id)
                if partner is not None and remaining_evening(partner, other) > 0:
                    return partner, other

            def locked_to_other_declared(candidate_id: int) -> bool:
                for left, right in declared:
                    if candidate_id not in (left, right) or subject_id in (left, right):
                        continue
                    true_partner = left if candidate_id == right else right
                    partner = assignment_for(true_partner)
                    # 真搭档在本侧仍有晚课额度 → 该候选腿已被规则预留
                    if partner is not None and remaining_evening(partner, head_parity) > 0:
                        return True
                return False

            candidates = [
                row for row in assignment_rows
                if int(row["class_id"]) == class_id
                and int(row["subject_id"]) != subject_id
                and remaining_evening(row, other) > 0
                and remaining_evening(row, head_parity) <= 0
                and not locked_to_other_declared(int(row["subject_id"]))
            ]
            if not candidates:
                return None
            rng = random.Random((class_id << 10) ^ subject_id ^ (1 if head_parity is WeekParity.odd else 2))
            rng.shuffle(candidates)
            return candidates[0], other

        # 班主任保留位与该班学科晚课是同一角色：
        # - 每周 1 节（单双周都有）→ 整格 week_parity=all 落保留位
        # - 每班仅 0.5 节 → 落单腿，并与对课规则另一科 0.5 拼满同一课位
        for weekday, period in sorted(reserved_by_parity[WeekParity.odd] | reserved_by_parity[WeekParity.even]):
            teacher_id = required_teachers.get((weekday, period), {}).get(class_id)
            if not teacher_id:
                continue
            if (weekday, period) in used_class_slots:
                continue
            head_candidates = [
                assignment for assignment in assignment_rows
                if int(assignment["class_id"]) == class_id
                and assignment.get("teacher_id") is not None
                and int(assignment["teacher_id"]) == int(teacher_id)
                and (
                    remaining_evening(assignment, WeekParity.odd) > 0
                    or remaining_evening(assignment, WeekParity.even) > 0
                )
            ]
            head_candidates.sort(
                key=lambda item: (
                    0 if (
                        remaining_evening(item, WeekParity.odd) > 0
                        and remaining_evening(item, WeekParity.even) > 0
                    ) else 1,
                    0 if int(item["subject_id"]) in parity_subject_ids else 1,
                    int(item["subject_id"]),
                    int(item.get("id") or 0),
                )
            )
            placed_head = False
            for assignment in head_candidates:
                subject_id = int(assignment["subject_id"])
                odd_left = remaining_evening(assignment, WeekParity.odd)
                even_left = remaining_evening(assignment, WeekParity.even)
                if odd_left <= 0 and even_left <= 0:
                    continue
                if slot_forbidden_for(class_id, subject_id, weekday, period):
                    continue
                if (weekday, period) in (teacher_forbidden_slots or {}).get(int(teacher_id), set()):
                    continue

                # 整周晚课：班主任位直接显示学科，占用全部额度。
                if odd_left > 0 and even_left > 0:
                    teacher_slots = {
                        (int(teacher_id), weekday, period, leg)
                        for leg in (WeekParity.odd, WeekParity.even)
                    }
                    if teacher_slots & occupied_teacher_slots:
                        continue
                    items.append(ScheduleItem(
                        assignment_id=int(assignment.get("id") or 0),
                        class_id=class_id,
                        subject_id=subject_id,
                        teacher_id=int(teacher_id),
                        weekday=weekday,
                        period=period,
                        room=assignment.get("room"),
                        week_parity=WeekParity.all,
                    ))
                    used_class_slots.add((weekday, period))
                    occupied_teacher_slots.update(teacher_slots)
                    note_teacher_evening_day(teacher_id, weekday)
                    pair_consumed[(subject_id, WeekParity.odd)] += 1
                    pair_consumed[(subject_id, WeekParity.even)] += 1
                    consolidated_subjects.add(subject_id)
                    placed_head = True
                    break

                # 0.5 晚课：必须与对课另一科拼同一课位；拼不上则撤回，禁止自习顶对课。
                head_parity = WeekParity.odd if odd_left > 0 else WeekParity.even
                if not place_evening_leg(assignment, weekday=weekday, period=period, parity=head_parity):
                    continue
                partner = partner_for_half(subject_id, head_parity)
                if partner is not None:
                    partner_assignment, partner_parity = partner
                    if not place_evening_leg(
                        partner_assignment,
                        weekday=weekday,
                        period=period,
                        parity=partner_parity,
                    ):
                        undo_evening_leg(
                            assignment, weekday=weekday, period=period, parity=head_parity
                        )
                        continue
                elif subject_id in parity_subject_ids:
                    undo_evening_leg(
                        assignment, weekday=weekday, period=period, parity=head_parity
                    )
                    continue
                elif activity_subject_id is not None:
                    other = WeekParity.even if head_parity is WeekParity.odd else WeekParity.odd
                    items.append(ScheduleItem(
                        assignment_id=0,
                        class_id=class_id,
                        subject_id=activity_subject_id,
                        teacher_id=None,
                        weekday=weekday,
                        period=period,
                        room=None,
                        week_parity=other,
                    ))
                used_class_slots.add((weekday, period))
                if remaining_evening(assignment, WeekParity.odd) <= 0 and remaining_evening(assignment, WeekParity.even) <= 0:
                    consolidated_subjects.add(subject_id)
                placed_head = True
                break
            if placed_head:
                continue
            if activity_subject_id is None:
                continue
            # 班主任本班没有可落的学科晚课额度时，仍保留活动课坐班位。
            items.append(ScheduleItem(
                assignment_id=0,
                class_id=class_id,
                subject_id=activity_subject_id,
                teacher_id=int(teacher_id),
                weekday=weekday,
                period=period,
                room=None,
                week_parity=WeekParity.all,
            ))
            used_class_slots.add((weekday, period))
            for leg in (WeekParity.odd, WeekParity.even):
                occupied_teacher_slots.add((int(teacher_id), weekday, period, leg))

        # 单双周对课先落：0.5 必须先占位，避免语数英整周晚课占掉联动教师唯一合法日。
        # 规则强制对课（物|史）优先；其余 0.5（化/政/生/地等）任意互配。
        half_pairs = _resolve_evening_half_pairs(
            assignment_rows,
            class_id=class_id,
            evening_count=evening_count,
            pair_consumed=pair_consumed,
            declared_pairs=parity_subject_pairs or [],
        )
        # 有晚课↔白天联动约束的教师先配对，避免唯一合法日被宽松对课占掉。
        def _pair_link_pressure(pair: tuple[int, int]) -> int:
            pressure = 0
            for subject_id in pair:
                assignment = assignment_for(subject_id)
                if assignment is None:
                    continue
                teacher_id = assignment.get("teacher_id")
                if teacher_id is not None and int(teacher_id) in link_by_teacher:
                    pressure += 1
            return -pressure

        half_pairs.sort(key=_pair_link_pressure)
        for odd_subject, even_subject in half_pairs:
            odd_assign = assignment_for(odd_subject)
            even_assign = assignment_for(even_subject)
            if odd_assign is None or even_assign is None:
                continue
            pair_count = min(
                remaining_evening(odd_assign, WeekParity.odd),
                remaining_evening(even_assign, WeekParity.even),
            )
            if pair_count <= 0:
                continue
            slots_o = slots_by_parity[WeekParity.odd]
            slots_e = set(slots_by_parity[WeekParity.even])
            teacher_o = odd_assign.get("teacher_id")
            teacher_e = even_assign.get("teacher_id")
            forbid_o = (teacher_forbidden_slots or {}).get(int(teacher_o), set()) if teacher_o is not None else set()
            forbid_e = (teacher_forbidden_slots or {}).get(int(teacher_e), set()) if teacher_e is not None else set()
            # 按「同一课位」扫，不用两侧列表下标对齐（避免单双周 profile 不一致时拼错日）。
            common_pair_slots = [slot for slot in slots_o if slot in slots_e]

            def _pair_slot_priority(slot: tuple[int, int]) -> tuple:
                hits = (1 if slot in forbid_o else 0) + (1 if slot in forbid_e else 0)
                link_miss = 0
                if not teacher_daytime_link_ok(
                    int(teacher_o) if teacher_o is not None else None, slot[0]
                ):
                    link_miss += 1
                if not teacher_daytime_link_ok(
                    int(teacher_e) if teacher_e is not None else None, slot[0]
                ):
                    link_miss += 1
                pref_miss = 0
                if not teacher_preferred_day_ok(
                    int(teacher_o) if teacher_o is not None else None, slot[0]
                ):
                    pref_miss += 1
                if not teacher_preferred_day_ok(
                    int(teacher_e) if teacher_e is not None else None, slot[0]
                ):
                    pref_miss += 1
                pack_o = teacher_day_pack_rank(
                    int(teacher_o) if teacher_o is not None else None, slot[0]
                )
                pack_e = teacher_day_pack_rank(
                    int(teacher_e) if teacher_e is not None else None, slot[0]
                )
                return (link_miss, pref_miss, pack_o, pack_e, hits, slot[0])

            placed = 0
            for slot in sorted(common_pair_slots, key=_pair_slot_priority):
                if placed >= pair_count:
                    break
                weekday, period = slot
                if (
                    slot in reserved_by_parity[WeekParity.odd]
                    or slot in reserved_by_parity[WeekParity.even]
                    or slot in used_class_slots
                    or day_reserved_for(class_id, weekday)
                ):
                    continue
                if (
                    slot_forbidden_for(class_id, odd_subject, weekday, period)
                    or slot_forbidden_for(class_id, even_subject, weekday, period)
                ):
                    continue
                if slot in forbid_o or slot in forbid_e:
                    continue
                if not teacher_daytime_link_ok(
                    int(teacher_o) if teacher_o is not None else None, weekday
                ) or not teacher_daytime_link_ok(
                    int(teacher_e) if teacher_e is not None else None, weekday
                ):
                    continue
                occ_o = (int(teacher_o), weekday, period, WeekParity.odd) if teacher_o is not None else None
                occ_e = (int(teacher_e), weekday, period, WeekParity.even) if teacher_e is not None else None
                if occ_o is not None and occ_o in occupied_teacher_slots:
                    continue
                if occ_e is not None and occ_e in occupied_teacher_slots:
                    continue
                items.append(ScheduleItem(
                    assignment_id=int(odd_assign.get("id") or 0), class_id=class_id,
                    subject_id=odd_subject, teacher_id=int(teacher_o) if teacher_o is not None else None,
                    weekday=weekday, period=period, room=odd_assign.get("room"),
                    week_parity=WeekParity.odd,
                ))
                items.append(ScheduleItem(
                    assignment_id=int(even_assign.get("id") or 0), class_id=class_id,
                    subject_id=even_subject, teacher_id=int(teacher_e) if teacher_e is not None else None,
                    weekday=weekday, period=period, room=even_assign.get("room"),
                    week_parity=WeekParity.even,
                ))
                note_teacher_evening_day(teacher_o, weekday)
                note_teacher_evening_day(teacher_e, weekday)
                if occ_o is not None:
                    occupied_teacher_slots.add(occ_o)
                if occ_e is not None:
                    occupied_teacher_slots.add(occ_e)
                used_class_slots.add(slot)
                pair_consumed[(odd_subject, WeekParity.odd)] += 1
                pair_consumed[(even_subject, WeekParity.even)] += 1
                placed += 1

        # 整周晚课（语数英等）后落，填对课后的剩余课位。
        common_slots = [
            slot for slot in slots_by_parity[WeekParity.odd]
            if slot in set(slots_by_parity[WeekParity.even])
        ]
        full_evening_assignments = [
            assignment for assignment in assignment_rows
            if int(assignment["class_id"]) == class_id
            and int(assignment["subject_id"]) not in parity_subject_ids
            and int(assignment["subject_id"]) not in consolidated_subjects
            and evening_count(assignment, WeekParity.odd) - pair_consumed[(int(assignment["subject_id"]), WeekParity.odd)] > 0
            and evening_count(assignment, WeekParity.even) - pair_consumed[(int(assignment["subject_id"]), WeekParity.even)] > 0
        ]
        # 多班晚课教师优先落位，便于后续班级往其连续日段上靠。
        full_evening_assignments.sort(
            key=lambda item: (
                -len(evening_classes_by_teacher.get(int(item["teacher_id"]), set()))
                if item.get("teacher_id") is not None
                else 0,
                int(item["subject_id"]),
                int(item.get("id") or 0),
            )
        )
        for assignment in full_evening_assignments:
            subject_id = int(assignment["subject_id"])
            teacher_id = assignment.get("teacher_id")
            forbid = (teacher_forbidden_slots or {}).get(int(teacher_id), set()) if teacher_id is not None else set()
            selected_slot = None
            for weekday, period in sorted(
                common_slots,
                key=lambda slot: (
                    0 if teacher_preferred_day_ok(
                        int(teacher_id) if teacher_id is not None else None, slot[0]
                    ) else 1,
                    teacher_day_pack_rank(
                        int(teacher_id) if teacher_id is not None else None, slot[0]
                    ),
                    slot in forbid,
                    slot[0],
                    slot[1],
                ),
            ):
                if (weekday, period) in used_class_slots:
                    continue
                if (
                    (weekday, period) in reserved_by_parity[WeekParity.odd]
                    or (weekday, period) in reserved_by_parity[WeekParity.even]
                    or day_reserved_for(class_id, weekday)
                    or slot_forbidden_for(class_id, subject_id, weekday, period)
                ):
                    continue
                if teacher_id is not None and (weekday, period) in (teacher_forbidden_slots or {}).get(int(teacher_id), set()):
                    continue
                if not teacher_daytime_link_ok(
                    int(teacher_id) if teacher_id is not None else None, weekday
                ):
                    continue
                teacher_slots = {
                    (int(teacher_id), weekday, period, parity)
                    for parity in (WeekParity.odd, WeekParity.even)
                } if teacher_id is not None else set()
                if teacher_slots & occupied_teacher_slots:
                    continue
                selected_slot = (weekday, period)
                break
            if selected_slot is None:
                continue
            weekday, period = selected_slot
            used_class_slots.add(selected_slot)
            if teacher_id is not None:
                occupied_teacher_slots.update({
                    (int(teacher_id), weekday, period, parity)
                    for parity in (WeekParity.odd, WeekParity.even)
                })
            items.append(ScheduleItem(
                assignment_id=int(assignment.get("id") or 0), class_id=class_id,
                subject_id=subject_id, teacher_id=int(teacher_id) if teacher_id is not None else None,
                weekday=weekday, period=period, room=assignment.get("room"),
                week_parity=WeekParity.all,
            ))
            note_teacher_evening_day(teacher_id, weekday)
            pair_consumed[(subject_id, WeekParity.odd)] += 1
            pair_consumed[(subject_id, WeekParity.even)] += 1
            consolidated_subjects.add(subject_id)

        # 同科单双周腿同日对齐：每周固定同一天，保证班级进度一致（客户规则13/17）
        odd_day_by_cs: dict[tuple[int, int], int] = {}
        slot_index = 0
        for parity, daily_periods in (
            (WeekParity.odd, evening_daily_periods_odd),
            (WeekParity.even, evening_daily_periods_even),
        ):
            slots = slots_by_parity[parity]
            reserved_slots = reserved_by_parity[parity]
            course_slots: list[dict[str, Any]] = []
            for assignment in assignment_rows:
                if int(assignment["class_id"]) != class_id:
                    continue
                if int(assignment["subject_id"]) in consolidated_subjects:
                    continue
                sid = int(assignment["subject_id"])
                # 本班另一侧仍有 0.5 额度时禁止单腿；孤独 0.5 仍可落位。
                if sid in parity_subject_ids:
                    other_parity = WeekParity.even if parity is WeekParity.odd else WeekParity.odd
                    has_partner_quota = any(
                        int(row["class_id"]) == class_id
                        and int(row["subject_id"]) != sid
                        and remaining_evening(row, other_parity) > 0
                        and remaining_evening(row, parity) <= 0
                        for row in assignment_rows
                    )
                    if has_partner_quota:
                        continue
                remaining = evening_count(assignment, parity) - pair_consumed[(sid, parity)]
                course_slots.extend([assignment] * max(0, remaining))
            course_slots.sort(key=lambda item: (int(item["subject_id"]), int(item.get("id") or 0)))

            slot_index = 0
            for assignment in course_slots:
                teacher_id = assignment.get("teacher_id")
                cs_key = (class_id, int(assignment["subject_id"]))
                preferred_day = odd_day_by_cs.get(cs_key) if parity == WeekParity.even else None
                selected_slot = None
                forbid = (teacher_forbidden_slots or {}).get(int(teacher_id), set()) if teacher_id is not None else set()
                safe_positions = [i for i, slot in enumerate(slots) if slot not in forbid]
                # 扫描顺序：对课同日 > 教师偏好日 > R15 连续打包日 > 非禁排日。
                pack_positions = sorted(
                    safe_positions,
                    key=lambda i: teacher_day_pack_rank(
                        int(teacher_id) if teacher_id is not None else None, slots[i][0]
                    ),
                )
                pref_positions = [
                    i for i in pack_positions
                    if teacher_preferred_day_ok(
                        int(teacher_id) if teacher_id is not None else None, slots[i][0]
                    )
                ]
                scan_order: tuple = (iter(pref_positions), iter(pack_positions), iter(safe_positions))
                if preferred_day is not None:
                    same_day_positions = [i for i in safe_positions if slots[i][0] == preferred_day]
                    scan_order = (iter(same_day_positions),) + scan_order
                scan_order = scan_order + (range(slot_index, len(slots)), range(0, slot_index))
                for scan in scan_order:
                    for candidate_index in scan:
                        weekday, period = slots[candidate_index]
                        if (weekday, period) in reserved_slots or (weekday, period) in used_class_slots:
                            continue
                        if candidate_index in pair_positions[parity]:
                            continue
                        if day_reserved_for(class_id, weekday):
                            continue
                        if teacher_id is not None and (weekday, period) in (teacher_forbidden_slots or {}).get(int(teacher_id), set()):
                            continue
                        if slot_forbidden_for(class_id, int(assignment["subject_id"]), weekday, period):
                            continue
                        if not teacher_daytime_link_ok(
                            int(teacher_id) if teacher_id is not None else None, weekday
                        ):
                            continue
                        teacher_slot = (int(teacher_id), weekday, period, parity) if teacher_id is not None else None
                        if teacher_slot is None or teacher_slot not in occupied_teacher_slots:
                            selected_slot = (candidate_index, weekday, period)
                            break
                    if selected_slot is not None:
                        break
                if selected_slot is None:
                    continue
                slot_index, weekday, period = selected_slot
                used_class_slots.add((weekday, period))
                occupied_teacher_slots.add((int(teacher_id), weekday, period, parity)) if teacher_id is not None else None
                if parity == WeekParity.odd:
                    odd_day_by_cs[cs_key] = weekday
                items.append(ScheduleItem(
                    assignment_id=int(assignment.get("id") or 0),
                    class_id=class_id,
                    subject_id=int(assignment["subject_id"]),
                    teacher_id=int(teacher_id) if teacher_id is not None else None,
                    weekday=weekday,
                    period=period,
                    room=assignment.get("room"),
                    week_parity=parity,
                ))
                note_teacher_evening_day(teacher_id, weekday)
                slot_index += 1

            if activity_subject_id is None:
                continue
            unmet = 0
            for assignment in assignment_rows:
                if int(assignment["class_id"]) != class_id:
                    continue
                need = evening_count(assignment, parity)
                if need <= 0:
                    continue
                sid = int(assignment["subject_id"])
                have = sum(
                    1 for item in items
                    if item.class_id == class_id
                    and item.subject_id == sid
                    and item.period >= first_evening_period
                    and (item.week_parity is parity or item.week_parity is WeekParity.all)
                )
                unmet += max(0, need - have)
            if unmet > 0:
                # 课时还没排完：空位留给学科，不用自习顶课时。
                continue
            scheduled_slots = {(item.weekday, item.period, item.week_parity) for item in items if item.class_id == class_id}
            for weekday, period in slots:
                if (
                    (weekday, period, parity) in scheduled_slots
                    or (weekday, period, WeekParity.all) in scheduled_slots
                ):
                    continue
                # 班主任保留位（全周记录）不再按单双周补自习
                if (weekday, period) in reserved_by_parity[WeekParity.odd] | reserved_by_parity[WeekParity.even]:
                    continue
                if slot_forbidden_for(class_id, activity_subject_id, weekday, period):
                    continue
                items.append(ScheduleItem(
                    assignment_id=0,
                    class_id=class_id,
                    subject_id=activity_subject_id,
                    teacher_id=None,
                    weekday=weekday,
                    period=period,
                    room=None,
                    week_parity=parity,
                ))

    return items


def generate_schedule(
    assignments: Iterable[dict[str, Any]],
    *,
    days: int = 5,
    periods_per_day: int = 8,
    forbidden_slots: set[tuple[int, int]] | None = None,
    max_class_lessons_per_day: int | None = None,
    max_teacher_lessons_per_day: int | None = None,
    max_class_lessons_on_saturday: int | None = None,
    max_teacher_lessons_on_saturday: int | None = None,
    max_same_subject_per_day: int | None = None,
    strategy_codes: list[str] | None = None,
    random_seed: int | None = None,
    avoid_consecutive_teacher_lessons: bool = False,
    teacher_daily_limits: dict[int, int] | None = None,
    max_teacher_weekly_periods: int | None = None,
    slot_patterns: Iterable[Mapping[str, Any]] | None = None,
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    teacher_class_forbidden_slots: Mapping[tuple[int, int], set[tuple[int, int]]] | None = None,
    subject_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    consecutive_requirements: Mapping[str, Any] | None = None,
    locked_items: Iterable[Mapping[str, Any]] | None = None,
) -> ScheduleResult:
    """用带受控随机破同分的贪心算法生成课表，并保证教师和班级无硬冲突。"""
    if not 1 <= days <= 7 or not 1 <= periods_per_day <= 12:
        raise ValueError("教学日或每日节次数量不合法")
    forbidden = forbidden_slots or set()
    teacher_forbidden = teacher_forbidden_slots or {}
    teacher_class_forbidden = teacher_class_forbidden_slots or {}
    subject_forbidden = subject_forbidden_slots or {}
    class_allowed = class_slot_allowed_subjects or {}
    strategy = build_schedule_strategy(strategy_codes)
    if "resource_tight" in strategy.codes:
        # 这是显式选择的放宽模式，不改变“教师同一时段不可重复授课”这一硬约束。
        # 仅提高日容量并允许同科一天多节，避免师资紧张时被日上限提前卡死。
        max_class_lessons_per_day = max(
            max_class_lessons_per_day or 0, periods_per_day,
        )
        max_teacher_lessons_per_day = max(
            max_teacher_lessons_per_day or 0, periods_per_day,
        )
    rng = random.Random(0 if random_seed is None else random_seed)

    normalized = sorted(
        filter_zero_hour_assignments(assignments),
        key=lambda item: (-int(item.get("weekly_periods", 0)), int(item["class_id"]), int(item["id"])),
    )
    locked = _locked_schedule_items(
        locked_items,
        normalized,
        days=days,
        periods_per_day=periods_per_day,
        forbidden_slots=forbidden,
    )
    locked_by_assignment: dict[int, list[ScheduleItem]] = defaultdict(list)
    for item in locked:
        locked_by_assignment[item.assignment_id].append(item)
    executable_patterns = _normalize_slot_patterns(slot_patterns)
    pattern_by_key: dict[tuple[int, int], Mapping[str, Any]] = {}
    pattern_required: dict[tuple[int, int], int] = defaultdict(int)
    pattern_assignment_ids: set[int] = set()
    for assignment in normalized:
        class_id = int(assignment["class_id"])
        subject_id = int(assignment["subject_id"])
        matches = [
            pattern for pattern in executable_patterns
            if _pattern_applies_to_assignment(
                pattern, class_id=class_id, subject_id=subject_id,
            )
        ]
        if len(matches) != 1:
            continue
        key = (class_id, subject_id)
        pattern_by_key[key] = matches[0]
        pattern_required[key] += sum(
            int(group_weekly)
            for _, group_weekly in _assignment_placement_groups(assignment, days=days)
        )

    # A pattern is active only when it describes exactly the configured weekly
    # volume. This prevents a two-slot PE pattern from accidentally constraining
    # a subject configured for three or six lessons.
    active_patterns: dict[tuple[int, int], Mapping[str, Any]] = {}
    pattern_states: dict[tuple[int, int], dict[str, Any]] = {}
    for key, pattern in pattern_by_key.items():
        alternatives = pattern.get("alternatives") or []
        totals = {
            sum(int(group.get("count", 0)) for group in alternative)
            for alternative in alternatives
            if isinstance(alternative, list)
        }
        if len(totals) == 1 and next(iter(totals), 0) == pattern_required[key]:
            active_patterns[key] = pattern
    for assignment in normalized:
        key = (int(assignment["class_id"]), int(assignment["subject_id"]))
        if key in active_patterns:
            pattern_assignment_ids.add(int(assignment["id"]))
    # 受课位组合限制的学科（如体育只允许周二/周四）课位稀缺，必须先排，
    # 否则普通学科会把稀缺课位抢光，受限学科将无课位可放。
    normalized.sort(key=lambda item: (
        0 if (int(item["class_id"]), int(item["subject_id"])) in active_patterns else 1,
        -int(item.get("weekly_periods", 0)),
        int(item["class_id"]),
        int(item["id"]),
    ))

    items: list[ScheduleItem] = list(locked)
    occupied_classes: set[tuple[int, int, int]] = {
        (item.class_id, item.weekday, item.period) for item in locked
    }
    occupied_teachers: set[tuple[int, int, int]] = {
        (item.teacher_id, item.weekday, item.period)
        for item in locked if item.teacher_id is not None
    }
    class_day_loads: dict[tuple[int, int], int] = defaultdict(int)
    teacher_day_loads: dict[tuple[int, int], int] = defaultdict(int)
    teacher_week_loads: dict[int, int] = defaultdict(int)
    class_subject_day_loads: dict[tuple[int, int, int], int] = defaultdict(int)
    class_subject_period_days: dict[tuple[int, int, int], set[int]] = defaultdict(set)
    class_day_periods: dict[tuple[int, int], set[int]] = defaultdict(set)
    teacher_day_periods: dict[tuple[int, int], set[int]] = defaultdict(set)
    teacher_period_week_loads: dict[tuple[int, int], int] = defaultdict(int)
    for item in locked:
        class_day_loads[(item.class_id, item.weekday)] += 1
        class_subject_day_loads[(item.class_id, item.subject_id, item.weekday)] += 1
        class_subject_period_days[(item.class_id, item.subject_id, item.period)].add(item.weekday)
        class_day_periods[(item.class_id, item.weekday)].add(item.period)
        if item.teacher_id is not None:
            teacher_day_loads[(item.teacher_id, item.weekday)] += 1
            teacher_week_loads[item.teacher_id] += 1
            teacher_day_periods[(item.teacher_id, item.weekday)].add(item.period)
    unplaced: list[dict[str, Any]] = []

    for phase in (1, 2):
        for assignment, class_id, subject_id, teacher_id, allowed_weekdays, group_weekly in _phase_groups(normalized, phase, days=days):
            locked_for_group = sum(
                item.weekday in allowed_weekdays
                for item in locked_by_assignment.get(int(assignment["id"]), [])
            )
            required = max(0, int(group_weekly) - locked_for_group)
            placed = 0
            for _ in range(required):
                pattern_key = (class_id, subject_id)
                pattern = active_patterns.get(pattern_key)
                pattern_state = pattern_states.setdefault(pattern_key, {}) if pattern else None
                if pattern and "alternative_index" not in pattern_state:
                    # Pick the alternative with the largest currently available
                    # capacity. A tie is resolved by the configured order, so
                    # generation remains deterministic with the same seed.
                    alternative_scores: list[tuple[int, int]] = []
                    for alternative_index, alternative in enumerate(pattern["alternatives"]):
                        capacity = 0
                        for group in alternative:
                            available = 0
                            for candidate_day in group["weekdays"]:
                                if candidate_day not in allowed_weekdays:
                                    continue
                                for candidate_period in group["periods"]:
                                    if (candidate_day, candidate_period) in forbidden:
                                        continue
                                    if teacher_id is not None:
                                        if (candidate_day, candidate_period) in teacher_forbidden.get(teacher_id, set()):
                                            continue
                                        if (candidate_day, candidate_period) in teacher_class_forbidden.get((teacher_id, class_id), set()):
                                            continue
                                    if (class_id, candidate_day, candidate_period) in occupied_classes:
                                        continue
                                    if teacher_id is not None and (
                                        teacher_id, candidate_day, candidate_period
                                    ) in occupied_teachers:
                                        continue
                                    available += 1
                            capacity += min(available, int(group["count"]))
                        alternative_scores.append((capacity, alternative_index))
                    pattern_state["alternative_index"] = max(
                        alternative_scores,
                        key=lambda value: (value[0], -value[1]),
                    )[1] if alternative_scores else 0
                    pattern_state["group_loads"] = defaultdict(int)
                candidates: list[tuple[tuple[int, ...], int, int, int | None]] = []
                for weekday in allowed_weekdays:
                    for period in range(1, periods_per_day + 1):
                        if (weekday, period) in forbidden:
                            continue
                        if teacher_id is not None:
                            if (weekday, period) in teacher_forbidden.get(teacher_id, set()):
                                continue
                            if (weekday, period) in teacher_class_forbidden.get((teacher_id, class_id), set()):
                                continue
                        if (weekday, period) in subject_forbidden.get(subject_id, set()):
                            continue
                        allowed_at_slot = class_allowed.get(class_id, {}).get((weekday, period))
                        if allowed_at_slot is not None and subject_id not in allowed_at_slot:
                            continue
                        matching_group: int | None = None
                        if pattern and pattern_state is not None:
                            alternative = pattern["alternatives"][pattern_state["alternative_index"]]
                            for group_index, group in enumerate(alternative):
                                if (
                                    pattern_state["group_loads"][group_index] < int(group["count"])
                                    and _pattern_group_matches(group, weekday, period)
                                ):
                                    matching_group = group_index
                                    break
                            if matching_group is None:
                                continue
                        class_slot = (class_id, weekday, period)
                        teacher_slot = (teacher_id, weekday, period) if teacher_id is not None else None
                        if class_slot in occupied_classes or (teacher_slot and teacher_slot in occupied_teachers):
                            continue
                        if avoid_consecutive_teacher_lessons and teacher_id is not None and any(
                            item.teacher_id == teacher_id
                            and item.weekday == weekday
                            and abs(item.period - period) == 1
                            for item in items
                        ):
                            continue
                        same_subject_today = class_subject_day_loads.get((class_id, subject_id, weekday), 0)
                        same_period_days = class_subject_period_days.get((class_id, subject_id, period), set())
                        adjacent_day_same_period_count = sum(
                            adjacent_day in same_period_days
                            for adjacent_day in (weekday - 1, weekday + 1)
                        )
                        class_day_load = class_day_loads.get((class_id, weekday), 0)
                        teacher_day_load = teacher_day_loads.get((teacher_id, weekday), 0) if teacher_id is not None else 0
                        class_daily_limit = (
                            max_class_lessons_on_saturday
                            if weekday == 6 and max_class_lessons_on_saturday is not None
                            else max_class_lessons_per_day
                        )
                        if class_daily_limit is not None and class_day_load >= class_daily_limit:
                            continue
                        teacher_daily_limit = (
                            teacher_daily_limits.get(teacher_id, max_teacher_lessons_per_day)
                            if teacher_daily_limits is not None and teacher_id is not None
                            else max_teacher_lessons_per_day
                        )
                        if weekday == 6 and max_teacher_lessons_on_saturday is not None:
                            teacher_daily_limit = max_teacher_lessons_on_saturday
                        if teacher_daily_limit is not None and teacher_day_load >= teacher_daily_limit:
                            continue
                        if (
                            max_teacher_weekly_periods is not None
                            and teacher_id is not None
                            and teacher_week_loads.get(teacher_id, 0) >= max_teacher_weekly_periods
                        ):
                            continue
                        class_periods = class_day_periods.get((class_id, weekday), set())
                        projected_class_periods = class_periods | {period}
                        class_gap_penalty = (
                            max(projected_class_periods) - min(projected_class_periods) + 1
                            - len(projected_class_periods)
                        )
                        teacher_periods = teacher_day_periods.get((teacher_id, weekday), set()) if teacher_id is not None else set()
                        projected_teacher_periods = teacher_periods | {period}
                        teacher_gap_penalty = (
                            max(projected_teacher_periods) - min(projected_teacher_periods) + 1
                            - len(projected_teacher_periods)
                        )
                        teacher_adjacent_count = sum(
                            adjacent in teacher_periods
                            for adjacent in (period - 1, period + 1)
                        )
                        teacher_slot_week_load = (
                            teacher_period_week_loads.get((teacher_id, period), 0)
                            if teacher_id is not None else 0
                        )
                        score = strategy.score(CandidateContext(
                            same_subject_today=same_subject_today,
                            adjacent_day_same_period_count=adjacent_day_same_period_count,
                            same_subject_same_period_days=len(same_period_days),
                            class_day_load=class_day_load,
                            teacher_day_load=teacher_day_load,
                            period=period,
                            class_gap_penalty=class_gap_penalty,
                            teacher_gap_penalty=teacher_gap_penalty,
                            teacher_adjacent_count=teacher_adjacent_count,
                            teacher_slot_week_load=teacher_slot_week_load,
                            random_tiebreak=rng.randrange(1_000_000),
                        ))
                        candidates.append((score, weekday, period, matching_group))

                if not candidates:
                    break
                _, weekday, period, matching_group = min(candidates, key=lambda candidate: candidate[0])
                item = ScheduleItem(
                    assignment_id=int(assignment["id"]),
                    class_id=class_id,
                    subject_id=subject_id,
                    teacher_id=teacher_id,
                    weekday=weekday,
                    period=period,
                    room=assignment.get("room"),
                )
                items.append(item)
                if pattern and pattern_state is not None and matching_group is not None:
                    pattern_state["group_loads"][matching_group] += 1
                occupied_classes.add((item.class_id, weekday, period))
                class_day_key = (item.class_id, weekday)
                class_subject_day_key = (item.class_id, item.subject_id, weekday)
                class_day_loads[class_day_key] = class_day_loads.get(class_day_key, 0) + 1
                class_subject_day_loads[class_subject_day_key] = class_subject_day_loads.get(class_subject_day_key, 0) + 1
                class_subject_period_days.setdefault((item.class_id, item.subject_id, period), set()).add(weekday)
                class_day_periods.setdefault(class_day_key, set()).add(period)
                if item.teacher_id is not None:
                    occupied_teachers.add((item.teacher_id, weekday, period))
                    teacher_day_key = (item.teacher_id, weekday)
                    teacher_day_loads[teacher_day_key] = teacher_day_loads.get(teacher_day_key, 0) + 1
                    teacher_day_periods.setdefault(teacher_day_key, set()).add(period)
                    teacher_week_loads[item.teacher_id] = teacher_week_loads.get(item.teacher_id, 0) + 1
                    teacher_period_week_loads[(item.teacher_id, period)] += 1
                placed += 1

            if placed < required:
                unplaced.append({
                    "assignment_id": int(assignment["id"]),
                    "count": required - placed,
                    "allowed_weekdays": allowed_weekdays,
                })

    # 阶段收口：工作日阶段修工作日连堂，周六阶段修周六连堂，互不越界。
    if consecutive_requirements:
        for phase in (1, 2):
            scoped = {"subjects": [], "teachers": []}
            for kind in ("subjects", "teachers"):
                for entry in consecutive_requirements.get(kind) or []:
                    if (6 in (entry.get("weekdays") or [])) == (phase == 2):
                        scoped[kind].append(entry)
            if scoped["subjects"] or scoped["teachers"]:
                items = repair_consecutive_blocks(
                    items,
                    subject_blocks=scoped["subjects"],
                    teacher_blocks=scoped["teachers"],
                    max_moves=1500,
                    days=days,
                    periods_per_day=periods_per_day,
                    forbidden_slots=forbidden,
                    max_class_lessons_per_day=max_class_lessons_per_day,
                    max_teacher_lessons_per_day=max_teacher_lessons_per_day,
                    max_teacher_lessons_on_saturday=max_teacher_lessons_on_saturday,
                    max_same_subject_per_day=max_same_subject_per_day,
                    teacher_daily_limits=teacher_daily_limits,
                    teacher_forbidden_slots=teacher_forbidden,
                    subject_forbidden_slots=subject_forbidden,
                    class_slot_allowed_subjects=class_allowed,
                )

    if unplaced:
        items, unplaced = _repair_unplaced_lessons(
            items,
            unplaced,
            {int(item["id"]): item for item in normalized},
            days=days,
            periods_per_day=periods_per_day,
            forbidden_slots=forbidden,
            max_class_lessons_per_day=max_class_lessons_per_day,
            max_teacher_lessons_per_day=max_teacher_lessons_per_day,
            max_same_subject_per_day=max_same_subject_per_day,
            avoid_consecutive_teacher_lessons=avoid_consecutive_teacher_lessons,
            teacher_forbidden_slots=teacher_forbidden,
            subject_forbidden_slots=subject_forbidden,
            class_slot_allowed_subjects=class_allowed,
            protected_assignment_ids=pattern_assignment_ids,
        )
    # “避免教师连上”是软约束：课表不能留下空白时，允许最后的修复阶段局部让步。
    if unplaced and avoid_consecutive_teacher_lessons:
        items, unplaced = _repair_unplaced_lessons(
            items,
            unplaced,
            {int(item["id"]): item for item in normalized},
            days=days,
            periods_per_day=periods_per_day,
            forbidden_slots=forbidden,
            max_class_lessons_per_day=max_class_lessons_per_day,
            max_teacher_lessons_per_day=max_teacher_lessons_per_day,
            max_same_subject_per_day=max_same_subject_per_day,
            avoid_consecutive_teacher_lessons=False,
            teacher_forbidden_slots=teacher_forbidden,
            subject_forbidden_slots=subject_forbidden,
            class_slot_allowed_subjects=class_allowed,
            protected_assignment_ids=pattern_assignment_ids,
        )

    items = strategy.optimize(
        items,
        lambda current: repair_class_gaps(
            current,
            days=days,
            periods_per_day=periods_per_day,
            forbidden_slots=forbidden,
            max_class_lessons_per_day=max_class_lessons_per_day,
            max_teacher_lessons_per_day=max_teacher_lessons_per_day,
             max_same_subject_per_day=max_same_subject_per_day,
             avoid_consecutive_teacher_lessons=avoid_consecutive_teacher_lessons,
             teacher_forbidden_slots=teacher_forbidden,
             subject_forbidden_slots=subject_forbidden,
             class_slot_allowed_subjects=class_allowed,
             protected_assignment_ids=pattern_assignment_ids,
         ),
    )
    unplaced.extend(_place_half_week_lessons(
        items,
        normalized,
        days=days,
        periods_per_day=periods_per_day,
        forbidden_slots=forbidden,
        teacher_forbidden_slots=teacher_forbidden,
        teacher_class_forbidden_slots=teacher_class_forbidden,
        subject_forbidden_slots=subject_forbidden,
        class_slot_allowed_subjects=class_allowed,
        max_teacher_lessons_per_day=max_teacher_lessons_per_day,
        max_teacher_lessons_on_saturday=max_teacher_lessons_on_saturday,
        teacher_daily_limits=teacher_daily_limits,
    ))
    # 半节单双周课程在策略修复后追加，追加本身也可能制造首节前或中间空堂；
    # 所有策略都先做轻量前移，避免普通模板也出现班级内部空堂。
    items = compact_class_gaps(
        items,
        days=days,
        periods_per_day=periods_per_day,
        forbidden_slots=forbidden,
        max_class_lessons_per_day=max_class_lessons_per_day,
        max_teacher_lessons_per_day=max_teacher_lessons_per_day,
        max_same_subject_per_day=max_same_subject_per_day,
        teacher_forbidden_slots=teacher_forbidden,
        subject_forbidden_slots=subject_forbidden,
        class_slot_allowed_subjects=class_allowed,
        protected_assignment_ids=pattern_assignment_ids,
    )
    # 只有确实存在教师挡位时，才使用跨班换位修复这一较重的搜索。
    if "cross_class_gap_repair" in strategy.codes:
        items = repair_class_gaps(
            items,
            days=days,
            periods_per_day=periods_per_day,
            forbidden_slots=forbidden,
            max_class_lessons_per_day=max_class_lessons_per_day,
            max_teacher_lessons_per_day=max_teacher_lessons_per_day,
            max_same_subject_per_day=max_same_subject_per_day,
            avoid_consecutive_teacher_lessons=avoid_consecutive_teacher_lessons,
            teacher_forbidden_slots=teacher_forbidden,
            subject_forbidden_slots=subject_forbidden,
            class_slot_allowed_subjects=class_allowed,
            protected_assignment_ids=pattern_assignment_ids,
            max_moves=max(30, len(items) * 2),
            max_candidate_checks=max(200, len(items) * 10),
        )

    return ScheduleResult(
        items=sorted(items, key=lambda item: (item.class_id, item.weekday, item.period)),
        unplaced=unplaced,
        staffing_issues=diagnose_staffing_gaps(items),
    )


def expand_schedule(
    items: Iterable[ScheduleItem],
    week_start: date,
    *,
    term_start_monday: date | None = None,
    first_week_parity: WeekParity | str = WeekParity.odd,
) -> list[DatedScheduleItem]:
    """将周课表映射为日期课表，并按单双周过滤。

    ``term_start_monday`` 未配置时，传入周视作开学第一周，以保持旧接口的行为。
    """
    if week_start.weekday() != 0:
        raise ValueError("日期课表的开始日期必须是周一")
    anchor = term_start_monday or week_start
    if anchor.weekday() != 0:
        raise ValueError("学期锚点日期必须是周一")
    first = WeekParity(first_week_parity)
    week_offset = (week_start - anchor).days // 7
    active = first if week_offset % 2 == 0 else (
        WeekParity.even if first is WeekParity.odd else WeekParity.odd
    )
    return [
        DatedScheduleItem(**item.__dict__, lesson_date=week_start + timedelta(days=item.weekday - 1))
        for item in items
        if item.week_parity in {WeekParity.all, active}
    ]


def _reorder_tall_to_edges(students: list[dict[str, Any]], cols: int) -> None:
    """同一行内按身高排序，个子高的放两侧靠边、矮的居中，避免遮挡后排。

    就地改写 students，按行块处理（缺学生时最后一行不满）。无身高者排在行内末尾。
    """
    n = len(students)
    if n <= 1 or cols <= 1:
        return
    n_rows = (n + cols - 1) // cols
    result: list[dict[str, Any]] = []
    for r in range(n_rows):
        block = students[r * cols : (r + 1) * cols]
        block.sort(
            key=lambda s: (
                s.get("height_cm") is None,
                float(s["height_cm"]) if s.get("height_cm") is not None else 0.0,
            ),
            reverse=True,
        )
        # 边优先列序：最左、最右、次左、次右……个子最高的依次落到两侧
        walk: list[int] = []
        lo, hi = 0, len(block) - 1
        while lo <= hi:
            walk.append(lo)
            if lo != hi:
                walk.append(hi)
            lo += 1
            hi -= 1
        placed: list[dict[str, Any] | None] = [None] * len(block)
        for slot, student in zip(walk, block):
            placed[slot] = student
        result.extend(p for p in placed if p is not None)
    students[:] = result


def arrange_students(
    students: Iterable[dict[str, Any]],
    *,
    rows: int,
    cols: int,
    order: str = "roster",
    layout: str = "normal",
    pairing: str = "none",
    seed: int | None = None,
    front_student_ids: set[int] | None = None,
    separation_pairs: list[list[int]] | None = None,
    adjacency_pairs: list[list[int]] | None = None,
    rule: str | None = None,
) -> list[SeatItem]:
    """按多维规则生成班级座位映射。

    分为两种类型的规则：
      - 模板级维度（全局）：
          order  ：排序方式（roster / random / gender），决定入座顺序；
          layout ：排布方式（normal / snake），决定顺序如何填入矩阵；
          pairing：身高互补（none / height），一高一矮交替安排同桌。
      - 班级约束（按班配置）：
          front_student_ids ：优先安排在前排的学生；
          separation_pairs  ：指定若干对 需隔离对学生，彼此不得相邻；
          adjacency_pairs   ：指定若干对 想挨着的学生，尽量安排相邻。

    保留 `rule` 作为旧参数兼容历史调用（rule="snake" 等价于
    order="roster", layout="snake"）。
    """
    if not 1 <= rows <= 20 or not 1 <= cols <= 20:
        raise ValueError("座位行列数不合法")

    if rule is not None:
        legacy = rule
        if legacy == "snake":
            order, layout = "roster", "snake"
        elif legacy in {"roster", "random", "gender"}:
            order, layout = legacy, "normal"
        elif legacy == "manual":
            raise ValueError("手动排座请逐座指定，无法自动生成")
        else:
            raise ValueError("不支持的排座规则")

    if order not in {"roster", "random", "gender", "score"}:
        raise ValueError("不支持的排序方式")
    if layout not in {"normal", "snake"}:
        raise ValueError("不支持的排布方式")
    if pairing not in {"none", "height"}:
        raise ValueError("不支持的搭配方式")

    ordered = sorted((dict(student) for student in students), key=lambda item: (int(item.get("roster_order", 0)), int(item["id"])))
    if len(ordered) > rows * cols:
        raise ValueError("座位容量不足，请增加行数或列数")

    if pairing == "height":
        with_height = sorted(
            [s for s in ordered if s.get("height_cm") is not None],
            key=lambda item: float(item["height_cm"]),
        )
        without_height = [s for s in ordered if s.get("height_cm") is None]
        merged: list[dict[str, Any]] = []
        mid = len(with_height) // 2
        low, high = with_height[:mid], with_height[mid:]
        while low or high:
            if low:
                merged.append(low.pop(0))
            if high:
                merged.append(high.pop(0))
        ordered = merged + without_height
    elif order == "gender":
        male = [student for student in ordered if student.get("gender") == "male"]
        female = [student for student in ordered if student.get("gender") == "female"]
        other = [student for student in ordered if student.get("gender") not in {"male", "female"}]
        ordered = []
        take_male = len(male) >= len(female)
        while male or female:
            source = male if take_male and male else female if female else male
            ordered.append(source.pop(0))
            take_male = not take_male
        ordered.extend(other)
    elif order == "random":
        random.Random(seed).shuffle(ordered)
    elif order == "score":
        # 高分靠前；无该场考试成绩的学生排在最后
        ordered.sort(
            key=lambda item: (
                item.get("exam_score") is None,
                -(float(item["exam_score"]) if item.get("exam_score") is not None else 0.0),
            ),
        )
        # 高个靠边：仅当有身高数据时，同一行内个子高的去两侧、矮的居中
        if any(s.get("height_cm") is not None for s in ordered):
            _reorder_tall_to_edges(ordered, cols)

    front_priority = front_student_ids or set()
    if front_priority:
        ordered.sort(key=lambda student: int(student["id"]) not in front_priority)

    # 班级约束映射表
    sep_map: dict[int, set[int]] = defaultdict(set)
    for pair in separation_pairs or []:
        if len(pair) >= 2:
            a, b = int(pair[0]), int(pair[1])
            sep_map[a].add(b)
            sep_map[b].add(a)
    adj_map: dict[int, set[int]] = defaultdict(set)
    for pair in adjacency_pairs or []:
        if len(pair) >= 2:
            a, b = int(pair[0]), int(pair[1])
            adj_map[a].add(b)
            adj_map[b].add(a)

    # 计算填充位置序列（配合蛇形）
    positions: list[tuple[int, int]] = []
    for index in range(len(ordered)):
        row = index // cols + 1
        offset = index % cols
        col = cols - offset if layout == "snake" and row % 2 == 0 else offset + 1
        positions.append((row, col))

    seat_at: dict[tuple[int, int], int] = {}
    remaining = list(ordered)
    seats: list[SeatItem] = []

    for row, col in positions:
        pick = _pick_student(
            remaining,
            (row, col),
            seat_at,
            sep_map,
            adj_map,
        )
        sid = int(remaining.pop(pick)["id"])
        seat_at[(row, col)] = sid
        seats.append(SeatItem(row=row, col=col, student_id=sid))

    return seats


_NEIGHBOR_OFFSETS = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if not (dr == 0 and dc == 0)]


def _occupied_neighbors(pos: tuple[int, int], seat_at: dict[tuple[int, int], int]) -> set[int]:
    """返回当前位置 8 邻域内已占座的学生 id。"""
    sids: set[int] = set()
    for dr, dc in _NEIGHBOR_OFFSETS:
        sid = seat_at.get((pos[0] + dr, pos[1] + dc))
        if sid is not None:
            sids.add(sid)
    return sids


def _separation_ok(
    sid: int,
    pos: tuple[int, int],
    seat_at: dict[tuple[int, int], int],
    sep_map: dict[int, set[int]],
) -> bool:
    """若 sid 与 pos 邻域的已坐学生构成隔离对，则不允许落位。"""
    neighbors = _occupied_neighbors(pos, seat_at)
    if not neighbors or sid not in sep_map:
        return True
    return not (neighbors & sep_map[sid])


def _pick_student(
    remaining: list[dict[str, Any]],
    pos: tuple[int, int],
    seat_at: dict[tuple[int, int], int],
    sep_map: dict[int, set[int]],
    adj_map: dict[int, set[int]],
) -> int:
    """从剩余学生中选一个落位于 pos。

    优先：其相邻偏好伴已在本格邻域（满足“挨着坐”）；其次顺序。
    任何情况下都跳过与本格邻域构成隔离对的学生；无解时退化为顺序。
    """
    neighbors = _occupied_neighbors(pos, seat_at)
    candidates: list[int] = []
    for i, student in enumerate(remaining):
        sid = int(student["id"])
        if not _separation_ok(sid, pos, seat_at, sep_map):
            continue
        candidates.append(i)
        # 若该候选有偏好伴且在邻域，立即采用
        if adj_map.get(sid, set()) & neighbors:
            return i
    if candidates:
        return candidates[0]
    return 0


@register_exam_schedule_strategy
class SequentialExamScheduleStrategy(ExamScheduleStrategy):
    """Backward-compatible custom strategy used by ordinary school exams."""

    mode = "custom"

    def build(
        self,
        papers: list[dict[str, Any]],
        *,
        start_date: date,
        teacher_ids: list[int],
        sessions: tuple[tuple[str, str], ...],
        room: str,
        excluded_dates: set[date],
        subject_names: Mapping[int, str],
    ) -> list[ExamScheduleItem]:
        del subject_names
        if not sessions:
            raise ValueError("每天至少需要一个考试场次")
        current_date = start_date
        session_index = 0
        result: list[ExamScheduleItem] = []
        for paper_index, paper in enumerate(papers):
            while current_date.weekday() >= 5 or current_date in excluded_dates:
                current_date += timedelta(days=1)
            start_time, end_time = sessions[session_index]
            result.append(ExamScheduleItem(
                paper_id=int(paper["id"]),
                subject_id=int(paper["subject_id"]),
                grade_id=int(paper["grade_id"]),
                exam_date=current_date,
                session_index=session_index + 1,
                start_time=start_time,
                end_time=end_time,
                invigilator_id=_paper_invigilator(paper, teacher_ids, paper_index),
                room=str(paper.get("room") or room),
                paper_teacher_id=paper.get("teacher_id"),
            ))
            session_index += 1
            if session_index >= len(sessions):
                session_index = 0
                current_date += timedelta(days=1)
        return result


def generate_exam_schedule(
    papers: Iterable[dict[str, Any]],
    *,
    start_date: date,
    teacher_ids: Iterable[int] = (),
    sessions: tuple[tuple[str, str], ...] = (("09:00", "11:00"), ("14:30", "16:30")),
    room: str = "各班教室",
    excluded_dates: set[date] | None = None,
    mode: str = "custom",
    subject_names: Mapping[int, str] | None = None,
) -> list[ExamScheduleItem]:
    """Generate subject sessions through a registered exam-mode strategy."""
    return get_exam_schedule_strategy(mode).build(
        [dict(item) for item in papers],
        start_date=start_date,
        teacher_ids=[int(item) for item in teacher_ids],
        sessions=sessions,
        room=room,
        excluded_dates=excluded_dates or set(),
        subject_names=subject_names or {},
    )


def arrange_exam_candidates(
    schedules: Iterable[ExamScheduleItem],
    *,
    candidate_ids_by_paper: Mapping[int, Iterable[int]],
    rooms: Iterable[ExamRoomResource],
    teacher_ids: Iterable[int],
    unavailable_teacher_slots: Mapping[int, set[tuple[date, int]]] | None = None,
    invigilators_per_room: int = 2,
) -> ExamArrangementResult:
    """Assign every candidate to a concrete room, seat and invigilation team."""
    room_resources = [item for item in rooms if item.capacity > 0 and item.name.strip()]
    if not room_resources:
        raise ValueError("请先配置至少一个有效考场")
    if invigilators_per_room < 1:
        raise ValueError("每个考场至少需要一名监考教师")
    teachers = list(dict.fromkeys(int(item) for item in teacher_ids))
    unavailable = unavailable_teacher_slots or {}
    grouped: dict[tuple[date, int], list[ExamScheduleItem]] = {}
    for schedule in schedules:
        grouped.setdefault((schedule.exam_date, schedule.session_index), []).append(schedule)

    room_assignments: list[ExamRoomAssignment] = []
    seats: list[ExamCandidateSeat] = []
    for slot, slot_schedules in sorted(grouped.items()):
        candidates_seen: set[int] = set()
        room_cursor = 0
        teacher_cursor = 0
        for schedule in sorted(slot_schedules, key=lambda item: (item.grade_id, item.subject_id, item.paper_id)):
            candidates = list(dict.fromkeys(int(item) for item in candidate_ids_by_paper.get(schedule.paper_id, ())))
            duplicate = candidates_seen.intersection(candidates)
            if duplicate:
                raise ValueError(f"同一场次存在 {len(duplicate)} 名重复考生，请检查选科冲突")
            candidates_seen.update(candidates)
            candidate_cursor = 0
            while candidate_cursor < len(candidates):
                if room_cursor >= len(room_resources):
                    shortage = len(candidates) - candidate_cursor
                    raise ValueError(f"考场容量不足，当前场次还有 {shortage} 名考生无法安排")
                room_resource = room_resources[room_cursor]
                room_cursor += 1
                assigned = candidates[candidate_cursor:candidate_cursor + room_resource.capacity]
                candidate_cursor += len(assigned)
                available_teachers = [
                    teacher_id for teacher_id in teachers[teacher_cursor:]
                    if teacher_id != schedule.paper_teacher_id
                    and slot not in unavailable.get(teacher_id, set())
                ]
                if len(available_teachers) < invigilators_per_room:
                    raise ValueError("监考教师不足，无法覆盖当前场次的全部考场")
                invigilators = tuple(available_teachers[:invigilators_per_room])
                teacher_cursor = max(teachers.index(item) for item in invigilators) + 1
                room_assignments.append(ExamRoomAssignment(
                    paper_id=schedule.paper_id,
                    subject_id=schedule.subject_id,
                    grade_id=schedule.grade_id,
                    exam_date=schedule.exam_date,
                    session_index=schedule.session_index,
                    room_name=room_resource.name,
                    capacity=room_resource.capacity,
                    candidate_count=len(assigned),
                    invigilator_ids=invigilators,
                ))
                seats.extend(
                    ExamCandidateSeat(
                        paper_id=schedule.paper_id,
                        subject_id=schedule.subject_id,
                        grade_id=schedule.grade_id,
                        student_id=student_id,
                        exam_date=schedule.exam_date,
                        session_index=schedule.session_index,
                        start_time=schedule.start_time,
                        end_time=schedule.end_time,
                        room_name=room_resource.name,
                        seat_no=seat_no,
                    )
                    for seat_no, student_id in enumerate(assigned, start=1)
                )
    return ExamArrangementResult(rooms=room_assignments, seats=seats)


def resolve_exam_candidates(
    papers: Iterable[Mapping[str, Any]],
    *,
    student_ids_by_grade: Mapping[int, Iterable[int]],
    selected_subject_ids_by_student: Mapping[int, set[int]],
    subject_names: Mapping[int, str],
) -> dict[int, list[int]]:
    """Resolve the actual candidate roster for every paper in a 3+1+2 exam."""
    required_subjects = {"语文", "数学", "英语", "外语"}
    result: dict[int, list[int]] = {}
    for paper in papers:
        paper_id = int(paper["id"])
        subject_id = int(paper["subject_id"])
        grade_id = int(paper["grade_id"])
        grade_students = [int(item) for item in student_ids_by_grade.get(grade_id, ())]
        if subject_names.get(subject_id) in required_subjects:
            result[paper_id] = grade_students
        else:
            result[paper_id] = [
                student_id for student_id in grade_students
                if subject_id in selected_subject_ids_by_student.get(student_id, set())
            ]
    return result
