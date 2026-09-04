"""Pure new-gaokao choice, teaching-class formation, and walk-class scheduling logic."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class SubjectChoice:
    """Mode-neutral student choice submitted to a registered strategy."""

    primary_subject_id: int | None = None
    secondary_subject_ids: tuple[int, ...] = ()
    selected_subject_ids: tuple[int, ...] = ()
    stream: str | None = None


@dataclass(frozen=True)
class SubjectChoicePolicy:
    """Configuration consumed by strategies; province rules stay out of callers."""

    primary_subject_ids: frozenset[int] | set[int] = frozenset()
    secondary_subject_ids: frozenset[int] | set[int] = frozenset()
    elective_subject_ids: frozenset[int] | set[int] = frozenset()
    elective_count: int = 3
    stream_subject_ids: Mapping[str, tuple[int, ...]] | None = None
    primary_delivery_mode: str = "administrative"


class SubjectChoiceStrategy(ABC):
    mode: str
    capabilities: frozenset[str] = frozenset()

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    @abstractmethod
    def validate(self, choice: SubjectChoice, policy: SubjectChoicePolicy) -> None:
        """Reject an invalid choice for this mode."""

    @abstractmethod
    def selected_subject_ids(
        self, choice: SubjectChoice, policy: SubjectChoicePolicy,
    ) -> tuple[int, ...]:
        """Return subjects that participate in teaching-class formation."""

    @abstractmethod
    def combination_key(self, choice: SubjectChoice, policy: SubjectChoicePolicy) -> str:
        """Return a stable grouping key for statistics."""

    def teaching_class_subject_ids(
        self, choice: SubjectChoice, policy: SubjectChoicePolicy,
    ) -> tuple[int, ...]:
        """Return only subjects delivered through temporary teaching classes."""
        return self.selected_subject_ids(choice, policy)

    def teaching_class_subject_pool(self, policy: SubjectChoicePolicy) -> frozenset[int]:
        """Return configured subjects that belong to the teaching-class scheduling track."""
        return frozenset(policy.elective_subject_ids or policy.secondary_subject_ids)


_SUBJECT_CHOICE_STRATEGIES: dict[str, SubjectChoiceStrategy] = {}


def register_subject_choice_strategy(strategy_type: type[SubjectChoiceStrategy]):
    """Class decorator used by each strategy to register its mode."""
    strategy = strategy_type()
    if strategy.mode in _SUBJECT_CHOICE_STRATEGIES:
        raise RuntimeError(f"高考模式策略重复注册: {strategy.mode}")
    _SUBJECT_CHOICE_STRATEGIES[strategy.mode] = strategy
    return strategy_type


def get_subject_choice_strategy(mode: str) -> SubjectChoiceStrategy:
    """Resolve by registry lookup; callers never branch on a policy mode."""
    try:
        return _SUBJECT_CHOICE_STRATEGIES[mode]
    except KeyError as exc:
        raise ValueError(f"不支持的高考模式: {mode}") from exc


@register_subject_choice_strategy
class ThreeOneTwoSubjectChoiceStrategy(SubjectChoiceStrategy):
    mode = "3+1+2"
    capabilities = frozenset({"subject_choice", "walk_class", "grade_conversion"})

    def validate(self, choice: SubjectChoice, policy: SubjectChoicePolicy) -> None:
        secondary = tuple(int(item) for item in choice.secondary_subject_ids)
        if choice.primary_subject_id not in policy.primary_subject_ids:
            raise ValueError("首选科目必须从配置的首选科目中选择")
        if (
            len(secondary) != 2
            or len(set(secondary)) != 2
            or not set(secondary).issubset(policy.secondary_subject_ids)
        ):
            raise ValueError("再选科目必须从配置范围中选择两门不同科目")

    def selected_subject_ids(
        self, choice: SubjectChoice, policy: SubjectChoicePolicy,
    ) -> tuple[int, ...]:
        self.validate(choice, policy)
        return (int(choice.primary_subject_id), *sorted(int(item) for item in choice.secondary_subject_ids))

    def combination_key(self, choice: SubjectChoice, policy: SubjectChoicePolicy) -> str:
        return "-".join(map(str, self.selected_subject_ids(choice, policy)))

    def teaching_class_subject_ids(
        self, choice: SubjectChoice, policy: SubjectChoicePolicy,
    ) -> tuple[int, ...]:
        self.validate(choice, policy)
        secondary = tuple(sorted(int(item) for item in choice.secondary_subject_ids))
        if policy.primary_delivery_mode == "administrative":
            return secondary
        if policy.primary_delivery_mode == "teaching_class":
            return (int(choice.primary_subject_id), *secondary)
        raise ValueError("首选科目授课方式只支持 administrative 或 teaching_class")

    def teaching_class_subject_pool(self, policy: SubjectChoicePolicy) -> frozenset[int]:
        secondary = frozenset(int(item) for item in policy.secondary_subject_ids)
        pools = {
            "administrative": secondary,
            "teaching_class": secondary | frozenset(int(item) for item in policy.primary_subject_ids),
        }
        try:
            return pools[policy.primary_delivery_mode]
        except KeyError as exc:
            raise ValueError("首选科目授课方式只支持 administrative 或 teaching_class") from exc


@register_subject_choice_strategy
class ThreePlusThreeSubjectChoiceStrategy(SubjectChoiceStrategy):
    mode = "3+3"
    capabilities = frozenset({"subject_choice", "walk_class", "grade_conversion"})

    def validate(self, choice: SubjectChoice, policy: SubjectChoicePolicy) -> None:
        selected = tuple(int(item) for item in choice.selected_subject_ids)
        if (
            len(selected) != policy.elective_count
            or len(set(selected)) != policy.elective_count
            or not set(selected).issubset(policy.elective_subject_ids)
        ):
            raise ValueError(f"选考科目必须从配置范围中选择 {policy.elective_count} 门不同科目")

    def selected_subject_ids(
        self, choice: SubjectChoice, policy: SubjectChoicePolicy,
    ) -> tuple[int, ...]:
        self.validate(choice, policy)
        return tuple(sorted(int(item) for item in choice.selected_subject_ids))

    def combination_key(self, choice: SubjectChoice, policy: SubjectChoicePolicy) -> str:
        return "-".join(map(str, self.selected_subject_ids(choice, policy)))


@register_subject_choice_strategy
class TraditionalSubjectChoiceStrategy(SubjectChoiceStrategy):
    mode = "traditional"
    capabilities = frozenset({"stream_choice", "admin_class_schedule"})

    def validate(self, choice: SubjectChoice, policy: SubjectChoicePolicy) -> None:
        streams = policy.stream_subject_ids or {}
        if choice.stream not in streams:
            raise ValueError("文理分科必须选择配置中的科类")

    def selected_subject_ids(
        self, choice: SubjectChoice, policy: SubjectChoicePolicy,
    ) -> tuple[int, ...]:
        self.validate(choice, policy)
        return tuple((policy.stream_subject_ids or {})[str(choice.stream)])

    def combination_key(self, choice: SubjectChoice, policy: SubjectChoicePolicy) -> str:
        self.validate(choice, policy)
        return str(choice.stream)


@dataclass(frozen=True)
class TeachingClassDraft:
    subject_id: int
    sequence: int
    student_ids: tuple[int, ...]


@dataclass(frozen=True)
class WalkScheduleItem:
    teaching_class_id: int
    teacher_id: int | None
    student_ids: tuple[int, ...]
    weekday: int
    period: int


@dataclass(frozen=True)
class WalkScheduleResult:
    items: list[WalkScheduleItem]
    unplaced: list[dict[str, int]]


@dataclass(frozen=True)
class SubjectSelectionPhase:
    code: str
    label: str
    description: str
    can_generate_teaching_classes: bool
    can_generate_schedule: bool


_SELECTION_PHASES = {
    (1, "1"): SubjectSelectionPhase(
        "exploration", "探索准备", "开展生涯规划和学科分析，尚不形成正式教学班。", False, False,
    ),
    (1, "2"): SubjectSelectionPhase(
        "intention", "意向与确认", "进行模拟选科、资源测算和正式确认，可预编教学班。", True, False,
    ),
}
_EFFECTIVE_SELECTION_PHASE = SubjectSelectionPhase(
    "effective", "正式实施", "确认结果已经生效，可生成教学班和走班课表。", True, True,
)


def resolve_selection_phase(grade_level: int, term: str) -> SubjectSelectionPhase:
    """Resolve the 3+1+2 workflow phase without scattering grade branches across APIs."""
    if grade_level not in {1, 2, 3} or term not in {"1", "2"}:
        raise ValueError("年级或学期不合法")
    return _SELECTION_PHASES.get((grade_level, term), _EFFECTIVE_SELECTION_PHASE)


def validate_subject_choice(
    primary_subject_id: int,
    secondary_subject_ids: Iterable[int],
    *,
    primary_pool: set[int],
    secondary_pool: set[int],
) -> None:
    """Backward-compatible facade for existing 3+1+2 callers."""
    get_subject_choice_strategy("3+1+2").validate(
        SubjectChoice(
            primary_subject_id=primary_subject_id,
            secondary_subject_ids=tuple(secondary_subject_ids),
        ),
        SubjectChoicePolicy(
            primary_subject_ids=primary_pool,
            secondary_subject_ids=secondary_pool,
        ),
    )


def form_teaching_classes(
    choices: Iterable[dict[str, Any]],
    *,
    capacity: int,
) -> list[TeachingClassDraft]:
    """Group students by selected subject after choices have been collected."""
    if not 1 <= capacity <= 100:
        raise ValueError("教学班班额必须在1至100之间")
    subject_students: dict[int, list[int]] = {}
    for choice in choices:
        student_id = int(choice["student_id"])
        for subject_id in dict.fromkeys(int(item) for item in choice["subject_ids"]):
            subject_students.setdefault(subject_id, []).append(student_id)

    groups: list[TeachingClassDraft] = []
    for subject_id in sorted(subject_students):
        student_ids = sorted(set(subject_students[subject_id]))
        for offset in range(0, len(student_ids), capacity):
            groups.append(TeachingClassDraft(
                subject_id=subject_id,
                sequence=offset // capacity + 1,
                student_ids=tuple(student_ids[offset:offset + capacity]),
            ))
    return groups


def generate_walk_schedule(
    tasks: Iterable[dict[str, Any]],
    *,
    days: int = 5,
    periods_per_day: int = 8,
    forbidden_slots: set[tuple[int, int]] | None = None,
) -> WalkScheduleResult:
    """Schedule teaching classes while preventing teacher and student conflicts."""
    if not 1 <= days <= 7 or not 1 <= periods_per_day <= 12:
        raise ValueError("教学日或每日节次数量不合法")
    forbidden = forbidden_slots or set()
    normalized = sorted(
        (dict(task) for task in tasks),
        key=lambda task: (-len(task.get("student_ids", [])), -int(task.get("weekly_periods", 0)), int(task["id"])),
    )
    items: list[WalkScheduleItem] = []
    occupied_teachers: set[tuple[int, int, int]] = set()
    occupied_students: set[tuple[int, int, int]] = set()
    occupied_classes: set[tuple[int, int, int]] = set()
    unplaced: list[dict[str, int]] = []

    for task in normalized:
        teaching_class_id = int(task["id"])
        teacher_id = int(task["teacher_id"]) if task.get("teacher_id") is not None else None
        student_ids = tuple(sorted({int(item) for item in task.get("student_ids", [])}))
        required = max(0, int(task.get("weekly_periods", 0)))
        placed = 0
        for _ in range(required):
            candidates: list[tuple[tuple[int, int, int], int, int]] = []
            for weekday in range(1, days + 1):
                for period in range(1, periods_per_day + 1):
                    if (weekday, period) in forbidden:
                        continue
                    if (teaching_class_id, weekday, period) in occupied_classes:
                        continue
                    if teacher_id is not None and (teacher_id, weekday, period) in occupied_teachers:
                        continue
                    if any((student_id, weekday, period) in occupied_students for student_id in student_ids):
                        continue
                    same_class_today = sum(
                        item.teaching_class_id == teaching_class_id and item.weekday == weekday for item in items
                    )
                    teacher_day_load = sum(
                        teacher_id is not None and item.teacher_id == teacher_id and item.weekday == weekday for item in items
                    )
                    candidates.append(((same_class_today * 100, teacher_day_load, period), weekday, period))
            if not candidates:
                break
            _, weekday, period = min(candidates, key=lambda candidate: candidate[0])
            item = WalkScheduleItem(teaching_class_id, teacher_id, student_ids, weekday, period)
            items.append(item)
            occupied_classes.add((teaching_class_id, weekday, period))
            if teacher_id is not None:
                occupied_teachers.add((teacher_id, weekday, period))
            occupied_students.update((student_id, weekday, period) for student_id in student_ids)
            placed += 1
        if placed < required:
            unplaced.append({"teaching_class_id": teaching_class_id, "count": required - placed})

    return WalkScheduleResult(
        items=sorted(items, key=lambda item: (item.weekday, item.period, item.teaching_class_id)),
        unplaced=unplaced,
    )
