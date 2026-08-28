"""排课与排座的纯算法。

算法不依赖数据库，便于用单元测试验证硬约束。API 层只负责加载数据和持久化结果。
"""
from dataclasses import dataclass, replace
from datetime import date, timedelta
import random
from typing import Any, Iterable, Mapping
from collections import defaultdict

from app.services.scheduling_strategies import CandidateContext, build_schedule_strategy


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


@dataclass(frozen=True)
class ScheduleItem:
    assignment_id: int
    class_id: int
    subject_id: int
    teacher_id: int | None
    weekday: int
    period: int
    room: str | None = None


@dataclass(frozen=True)
class DatedScheduleItem(ScheduleItem):
    lesson_date: date = date.min


@dataclass(frozen=True)
class ScheduleResult:
    items: list[ScheduleItem]
    unplaced: list[dict[str, int]]
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
    requested: int
    capacity: int
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
    requested_lessons: int
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
    max_same_subject_per_day: int | None = None,
    require_full_week: bool = False,
    max_classes_per_teacher: int | None = None,
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
    class_capacity = sum(
        min(slots, max_class_lessons_per_day) if max_class_lessons_per_day is not None else slots
        for slots in available_by_day.values()
    )
    teacher_capacity = sum(
        min(slots, max_teacher_lessons_per_day) if max_teacher_lessons_per_day is not None else slots
        for slots in available_by_day.values()
    )
    subject_capacity = sum(
        min(slots, max_same_subject_per_day) if max_same_subject_per_day is not None else slots
        for slots in available_by_day.values()
    )

    def capacity_formula(limit: int | None, capacity: int) -> str:
        active_slots = [slots for slots in available_by_day.values() if slots > 0]
        if limit is not None and active_slots and all(slots >= limit for slots in active_slots):
            return f"{len(active_slots)} 个可排教学日 × 每日最多 {limit} 节 = {capacity} 节"
        contributions = [min(slots, limit) if limit is not None else slots for slots in active_slots]
        return f"各可排教学日容量 {' + '.join(map(str, contributions)) or '0'} = {capacity} 节"

    def minimum_daily_limit(requested: int) -> int | None:
        for limit in range(1, periods_per_day + 1):
            if sum(min(slots, limit) for slots in available_by_day.values()) >= requested:
                return limit
        return None

    class_formula = capacity_formula(max_class_lessons_per_day, class_capacity)
    teacher_formula = capacity_formula(max_teacher_lessons_per_day, teacher_capacity)
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
    class_loads: dict[int, int] = {}
    teacher_loads: dict[int, int] = {}
    teacher_classes: dict[int, set[int]] = {}
    subject_loads: dict[tuple[int, int], int] = {}
    for item in rows:
        required = max(0, int(item.get("weekly_periods", 0)))
        class_id = int(item["class_id"])
        subject_id = int(item["subject_id"])
        class_loads[class_id] = class_loads.get(class_id, 0) + required
        subject_key = (class_id, subject_id)
        subject_loads[subject_key] = subject_loads.get(subject_key, 0) + required
        if item.get("teacher_id") is not None:
            teacher_id = int(item["teacher_id"])
            teacher_loads[teacher_id] = teacher_loads.get(teacher_id, 0) + required
            teacher_classes.setdefault(teacher_id, set()).add(class_id)

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
        if max_classes_per_teacher is not None and len(teacher_classes.get(teacher_id, set())) > max_classes_per_teacher:
            class_count = len(teacher_classes[teacher_id])
            issues.append(ScheduleValidationIssue(
                code="teacher_class_count_exceeded",
                message=f"教师 {teacher_id} 当前承担 {class_count} 个班，超过最多 {max_classes_per_teacher} 个班的限制",
                entity_type="teacher",
                entity_id=teacher_id,
                requested=class_count,
                capacity=max_classes_per_teacher,
                rule_code="max_classes_per_teacher",
                formula=f"{class_count} 个班 > {max_classes_per_teacher} 个班上限",
                suggestions=(ScheduleValidationSuggestion(
                    code="add_subject_teacher",
                    label=f"补充或重新分配教师，保证每名教师最多 {max_classes_per_teacher} 个班",
                    field="max_classes_per_teacher",
                    recommended_value=max_classes_per_teacher,
                    reason="当前任教关系超过单教师班级上限，继续排课会造成教师负荷失真。",
                    tradeoff="需要新增教师或将现有班级重新分配给其他同学科教师。",
                ),),
            ))
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
        requested_lessons=sum(max(0, int(item.get("weekly_periods", 0))) for item in rows),
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
    ignored_index: int | None = None,
) -> bool:
    if not 1 <= candidate.weekday <= days or not 1 <= candidate.period <= periods_per_day:
        return False
    if (candidate.weekday, candidate.period) in forbidden_slots:
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
    return not (
        max_class_lessons_per_day is not None
        and class_day_load >= max_class_lessons_per_day
        or max_teacher_lessons_per_day is not None
        and teacher_day_load >= max_teacher_lessons_per_day
        or max_same_subject_per_day is not None
        and same_subject_today >= max_same_subject_per_day
    )


def _class_gap_count(items: Iterable[ScheduleItem]) -> int:
    periods_by_class_day: dict[tuple[int, int], set[int]] = {}
    for item in items:
        periods_by_class_day.setdefault((item.class_id, item.weekday), set()).add(item.period)
    return sum(
        max(periods) - min(periods) + 1 - len(periods)
        for periods in periods_by_class_day.values()
        if periods
    )


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
    max_moves: int = 30,
    max_candidate_checks: int = 200,
) -> list[ScheduleItem]:
    """Relocate at most one teacher blocker at a time to close class-table gaps."""
    result = list(items)
    forbidden = forbidden_slots or set()
    candidate_checks = 0
    for _ in range(max_moves):
        before = _class_gap_count(result)
        if before == 0:
            break
        periods_by_class_day: dict[tuple[int, int], set[int]] = {}
        for item in result:
            periods_by_class_day.setdefault((item.class_id, item.weekday), set()).add(item.period)
        repaired = False
        for (class_id, weekday), periods in sorted(periods_by_class_day.items()):
            gaps = [period for period in range(min(periods), max(periods)) if period not in periods]
            for gap in gaps:
                source_indexes = sorted(
                    (
                        index for index, item in enumerate(result)
                        if item.class_id == class_id and item.weekday == weekday and item.period > gap
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
                        ignored_index=source_index,
                    ):
                        candidate_result = list(result)
                        candidate_result[source_index] = target
                    elif len(blockers) == 1:
                        blocker_index = blockers[0]
                        blocker = result[blocker_index]
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
                                    ignored_index=blocker_index,
                                ):
                                    continue
                                candidate_result = moved_items
                                break
                            if candidate_result is not None:
                                break
                    if candidate_result is not None and _class_gap_count(candidate_result) < before:
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


def _repair_unplaced_lessons(
    items: list[ScheduleItem],
    unplaced: list[dict[str, int]],
    assignments: dict[int, dict[str, Any]],
    *,
    days: int,
    periods_per_day: int,
    forbidden_slots: set[tuple[int, int]],
    max_class_lessons_per_day: int | None,
    max_teacher_lessons_per_day: int | None,
    max_same_subject_per_day: int | None,
    avoid_consecutive_teacher_lessons: bool = False,
) -> tuple[list[ScheduleItem], list[dict[str, int]]]:
    """通过移动一个阻塞课程，尝试修复贪心初排留下的课程。"""
    remaining: list[dict[str, int]] = []
    for entry in unplaced:
        assignment = assignments[entry["assignment_id"]]
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
            for target_day in range(1, days + 1):
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
            remaining.append({"assignment_id": entry["assignment_id"], "count": entry["count"] - repaired})
    return items, remaining


def generate_schedule(
    assignments: Iterable[dict[str, Any]],
    *,
    days: int = 5,
    periods_per_day: int = 8,
    forbidden_slots: set[tuple[int, int]] | None = None,
    max_class_lessons_per_day: int | None = None,
    max_teacher_lessons_per_day: int | None = None,
    max_same_subject_per_day: int | None = None,
    strategy_codes: list[str] | None = None,
    random_seed: int | None = None,
    avoid_consecutive_teacher_lessons: bool = False,
    teacher_daily_limits: dict[int, int] | None = None,
    max_teacher_weekly_periods: int | None = None,
) -> ScheduleResult:
    """用带受控随机破同分的贪心算法生成课表，并保证教师和班级无硬冲突。"""
    if not 1 <= days <= 7 or not 1 <= periods_per_day <= 12:
        raise ValueError("教学日或每日节次数量不合法")
    forbidden = forbidden_slots or set()
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
        max_same_subject_per_day = max(
            max_same_subject_per_day or 0, 2,
        )
    rng = random.Random(0 if random_seed is None else random_seed)

    normalized = sorted(
        (dict(item) for item in assignments),
        key=lambda item: (-int(item.get("weekly_periods", 0)), int(item["class_id"]), int(item["id"])),
    )
    items: list[ScheduleItem] = []
    occupied_classes: set[tuple[int, int, int]] = set()
    occupied_teachers: set[tuple[int, int, int]] = set()
    class_day_loads: dict[tuple[int, int], int] = {}
    teacher_day_loads: dict[tuple[int, int], int] = {}
    teacher_week_loads: dict[int, int] = {}
    class_subject_day_loads: dict[tuple[int, int, int], int] = {}
    class_subject_period_days: dict[tuple[int, int, int], set[int]] = {}
    class_day_periods: dict[tuple[int, int], set[int]] = {}
    teacher_day_periods: dict[tuple[int, int], set[int]] = {}
    unplaced: list[dict[str, int]] = []

    for assignment in normalized:
        required = max(0, int(assignment.get("weekly_periods", 0)))
        class_id = int(assignment["class_id"])
        subject_id = int(assignment["subject_id"])
        raw_teacher_id = assignment.get("teacher_id")
        teacher_id = int(raw_teacher_id) if raw_teacher_id is not None else None
        placed = 0
        for _ in range(required):
            candidates: list[tuple[tuple[int, ...], int, int]] = []
            for weekday in range(1, days + 1):
                for period in range(1, periods_per_day + 1):
                    if (weekday, period) in forbidden:
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
                    same_subject_periods_today = {
                        item.period for item in items
                        if item.class_id == class_id
                        and item.subject_id == subject_id
                        and item.weekday == weekday
                    }
                    # 高一默认启用“班级紧凑”时，同一学科允许早晚分布，
                    # 但不允许相邻节次连排；这不是限制整个班每天只能上三节。
                    if "class_compact" in strategy.codes and any(
                        abs(existing_period - period) == 1
                        for existing_period in same_subject_periods_today
                    ):
                        continue
                    adjacent_subject_loads = [
                        class_subject_day_loads.get((class_id, subject_id, adjacent_day), 0)
                        for adjacent_day in (weekday - 1, weekday + 1)
                        if 1 <= adjacent_day <= days
                    ]
                    if same_subject_today >= 2 and any(load >= 3 for load in adjacent_subject_loads):
                        continue
                    adjacent_day_same_period_count = sum(
                        adjacent_day in same_period_days
                        for adjacent_day in (weekday - 1, weekday + 1)
                    )
                    class_day_load = class_day_loads.get((class_id, weekday), 0)
                    teacher_day_load = teacher_day_loads.get((teacher_id, weekday), 0) if teacher_id is not None else 0
                    if max_class_lessons_per_day is not None and class_day_load >= max_class_lessons_per_day:
                        continue
                    teacher_daily_limit = (
                        teacher_daily_limits.get(teacher_id, max_teacher_lessons_per_day)
                        if teacher_daily_limits is not None and teacher_id is not None
                        else max_teacher_lessons_per_day
                    )
                    if teacher_daily_limit is not None and teacher_day_load >= teacher_daily_limit:
                        continue
                    if (
                        max_teacher_weekly_periods is not None
                        and teacher_id is not None
                        and teacher_week_loads.get(teacher_id, 0) >= max_teacher_weekly_periods
                    ):
                        continue
                    if max_same_subject_per_day is not None and same_subject_today >= max_same_subject_per_day:
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
                        random_tiebreak=rng.randrange(1_000_000),
                    ))
                    candidates.append((score, weekday, period))

            if not candidates:
                break
            _, weekday, period = min(candidates, key=lambda candidate: candidate[0])
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
            placed += 1

        if placed < required:
            unplaced.append({"assignment_id": int(assignment["id"]), "count": required - placed})

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
        ),
    )

    return ScheduleResult(
        items=sorted(items, key=lambda item: (item.class_id, item.weekday, item.period)),
        unplaced=unplaced,
        staffing_issues=diagnose_staffing_gaps(items),
    )


def expand_schedule(items: Iterable[ScheduleItem], week_start: date) -> list[DatedScheduleItem]:
    """将周课表映射为从指定周一开始的日期课表。"""
    if week_start.weekday() != 0:
        raise ValueError("日期课表的开始日期必须是周一")
    return [
        DatedScheduleItem(**item.__dict__, lesson_date=week_start + timedelta(days=item.weekday - 1))
        for item in items
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
