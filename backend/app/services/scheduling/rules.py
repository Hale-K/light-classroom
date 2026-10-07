"""结构化排课规则编译与校验。

规则的中文标题、摘要和备注只用于展示。排课算法只读取本模块定义的
``code``、稳定 ID 和类型化 ``params``，遇到未知编码或缺少参数时明确返回
``unresolved``，绝不尝试从自然语言猜测规则含义。
"""

from collections import defaultdict
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, Field, model_validator

from app.models.enums import WeekParity
from app.services.scheduling.core import ScheduleItem


RuleCode = Literal[
    "student_gap_minimize",
    "student_contiguous",
    "slot_forbidden",
    "slot_allowed",
    "slot_fixed",
    "teacher_daily_limit",
    "teacher_consecutive",
    "teacher_gap_free",
    "subject_daily_spread",
    "class_gap_free",
    "slot_teacher_balance",
    "subject_evening_parity_pair",
    "subject_daytime_parity_pair",
    "teacher_multi_class_evening_adjacent",
    "teacher_forbidden_slots",
    "teacher_preferred_weekdays",
    "subject_consecutive",
    "subject_allowed_slots",
    "class_allowed_subjects",
    "teacher_evening_daytime_link",
    "teacher_period_minimum",
    "class_slot_pattern",
    "class_evening_self_study_day",
    "slot_teacher_role_required",
    "manual_review",
    "subject_prefer_early_periods",
    "subject_gap_fill_late_periods",
]
TargetType = Literal["global", "slot", "subject", "teacher", "class"]
PeriodScope = Literal["regular", "evening", "any"]

SUPPORTED_RULE_CODES: frozenset[str] = frozenset({
    "student_gap_minimize",
    "student_contiguous",
    "slot_forbidden", "slot_allowed", "slot_fixed",
    "teacher_daily_limit", "teacher_consecutive", "teacher_gap_free",
    "class_gap_free", "subject_daily_spread",
    "slot_teacher_balance", "subject_evening_parity_pair",
    "subject_daytime_parity_pair",
    "teacher_multi_class_evening_adjacent", "teacher_forbidden_slots",
    "teacher_preferred_weekdays", "subject_consecutive", "subject_allowed_slots",
    "class_allowed_subjects", "class_slot_pattern", "class_evening_self_study_day",
    "teacher_evening_daytime_link", "teacher_period_minimum",
    "slot_teacher_role_required", "manual_review",
    "subject_prefer_early_periods", "subject_gap_fill_late_periods",
})


class RuleTarget(BaseModel):
    type: TargetType
    ids: list[int] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_ids(self):
        if any(value <= 0 for value in self.ids):
            raise ValueError("规则目标 ID 必须为正整数")
        if self.type != "global" and not self.ids:
            raise ValueError("非全局规则必须提供目标 ID")
        return self


class RuleDefinition(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=60)
    enabled: bool = True
    priority: Literal["hard", "soft"] = "soft"
    # 公共规则(general)与个性规则(individual)冲突时，个性规则优先。
    rule_scope: Literal["general", "individual"] = "general"
    # 旧规则默认保持共用；行政班预留课位不会再禁掉走班。
    schedule_scope: Literal["all", "admin", "walk"] = "all"
    target: RuleTarget
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    periods: list[int] = Field(default_factory=list, max_length=12)
    period_scope: PeriodScope = "regular"
    week_parity: Literal["all", "odd", "even"] = "all"
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_time(self):
        if any(value < 1 or value > 7 for value in self.weekdays):
            raise ValueError("规则星期必须在 1 到 7 之间")
        if any(value < 1 or value > 12 for value in self.periods):
            raise ValueError("规则节次必须在 1 到 12 之间")
        self.weekdays = sorted(set(self.weekdays))
        self.periods = sorted(set(self.periods))
        return self


class RuleGroupDocument(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(min_length=1, max_length=20)
    version: int = Field(default=1, ge=1)
    grade_id: int | None = Field(default=None, ge=1, description="关联组织年级 ID")
    rules: list[RuleDefinition] = Field(default_factory=list, max_length=500)


RULE_GROUP_CATALOG_VERSION = 2


def rules_for_schedule(
    group: RuleGroupDocument, mode: Literal["admin", "walk"],
) -> RuleGroupDocument:
    """Select execution rules without changing the semester's stored catalog."""
    return group.model_copy(update={
        "rules": [rule for rule in group.rules if rule.schedule_scope in {"all", mode}],
    })


def normalize_legacy_rule_group(group: RuleGroupDocument) -> RuleGroupDocument:
    """Patch stored rules whose semantics changed (e.g. R17-01 own-class only)."""
    rules = []
    changed = False
    for rule in group.rules:
        if (
            rule.id == "R17-01"
            and rule.code == "teacher_forbidden_slots"
            and not rule.params.get("own_head_class_only")
        ):
            rules.append(
                rule.model_copy(
                    update={
                        "params": {**dict(rule.params), "own_head_class_only": True},
                        "title": "本班第五节不排班主任",
                    }
                )
            )
            changed = True
            continue
        if rule.id == "R17-02" and rule.code == "slot_teacher_balance":
            cap = rule.params.get("max_per_teacher")
            # 仅在缺省/非法时回落默认 2；用户在工作台改的数量要保留
            if not _positive_int(cap):
                rules.append(
                    rule.model_copy(
                        update={
                            "params": {**dict(rule.params), "max_per_teacher": 2},
                            "title": "第5节教师每周最多2节",
                        }
                    )
                )
                changed = True
                continue
            expected_title = f"第5节教师每周最多{int(cap)}节"
            if rule.title != expected_title:
                rules.append(rule.model_copy(update={"title": expected_title}))
                changed = True
                continue
        rules.append(rule)
    return group.model_copy(update={"rules": rules}) if changed else group


def parse_stored_rule_groups(value: dict) -> tuple[list[RuleGroupDocument], str | None]:
    """Parse a term payload: legacy single document or multi-group catalog."""
    raw_groups = value.get("groups")
    if value.get("catalog_version") == RULE_GROUP_CATALOG_VERSION and isinstance(raw_groups, list):
        groups = [
            normalize_legacy_rule_group(RuleGroupDocument.model_validate(item))
            for item in raw_groups
            if isinstance(item, dict)
        ]
        active_id = value.get("active_id")
        return groups, str(active_id) if isinstance(active_id, str) and active_id else None
    return [normalize_legacy_rule_group(RuleGroupDocument.model_validate(value))], None


def pick_rule_group(
    groups: list[RuleGroupDocument],
    *,
    group_id: str | None = None,
    grade_id: int | None = None,
    active_id: str | None = None,
) -> RuleGroupDocument | None:
    if group_id:
        return next((item for item in groups if item.id == group_id), None)
    if grade_id is not None:
        matched = [item for item in groups if item.grade_id == grade_id]
        if matched:
            if active_id:
                return next((item for item in matched if item.id == active_id), matched[0])
            return matched[0]
    if active_id:
        found = next((item for item in groups if item.id == active_id), None)
        if found is not None:
            return found
    return groups[0] if groups else None


def dump_stored_rule_groups(
    groups: list[RuleGroupDocument],
    active_id: str | None,
) -> dict:
    """Serialize catalog; flatten the active group so legacy scripts still validate."""
    payload: dict = {
        "catalog_version": RULE_GROUP_CATALOG_VERSION,
        "active_id": active_id,
        "groups": [item.model_dump(mode="json") for item in groups],
    }
    active = pick_rule_group(groups, group_id=active_id, active_id=active_id)
    if active is None:
        return payload
    flattened = active.model_dump(mode="json")
    flattened.update(payload)
    return flattened


class CompiledRule(BaseModel):
    rule_id: str
    code: str
    title: str
    priority: Literal["hard", "soft"]
    status: Literal["ready", "unresolved"]
    reason: str | None = None


class RuleEvaluationResult(BaseModel):
    rule_id: str
    code: str
    title: str
    priority: Literal["hard", "soft"]
    status: Literal["pass", "fail", "unresolved", "not_run", "manual"]
    violation_count: int = 0
    penalty: int = 0
    metrics: dict[str, int | float | str] = Field(default_factory=dict)
    message: str


class RuleEvaluationSummary(BaseModel):
    valid: bool
    compiled: bool
    schedule_available: bool
    schedule_item_count: int
    results: list[RuleEvaluationResult]
    unresolved: list[dict[str, str]] = Field(default_factory=list)
    score: int = 0


def blocking_rule_results(summary: RuleEvaluationSummary) -> list[RuleEvaluationResult]:
    """Return every enabled hard rule that prevents using a schedule.

    Generation must not maintain a second, incomplete allow-list of rule
    codes.  A hard rule that failed, could not be compiled, or could not be
    evaluated is unsafe to ignore, regardless of its rule family.
    """
    return [
        result
        for result in summary.results
        if result.priority == "hard"
        and result.status in {"fail", "unresolved", "not_run"}
    ]


def compile_rule_group(group: RuleGroupDocument) -> list[CompiledRule]:
    """Compile UI data into an allow-listed executable rule set."""
    compiled: list[CompiledRule] = []
    for rule in group.rules:
        if not rule.enabled:
            continue
        if rule.code not in SUPPORTED_RULE_CODES:
            raise ValueError(f"未知规则编码: {rule.code}")
        reason = _missing_parameter(rule)
        compiled.append(CompiledRule(
            rule_id=rule.id,
            code=rule.code,
            title=rule.title,
            priority=rule.priority,
            status="unresolved" if reason else "ready",
            reason=reason,
        ))
    return compiled


def generation_slot_patterns(group: RuleGroupDocument) -> list[dict[str, Any]]:
    """Return hard, executable slot-pattern rules for the schedule generator.

    Display text and soft goals never enter the generator. Only a typed subject
    target with a validated OR-of-AND alternative list becomes a placement
    constraint; other rules continue through the post-generation evaluator.
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    patterns: list[dict[str, Any]] = []
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "class_slot_pattern"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "subject"
            or len(rule.target.ids) != 1
        ):
            continue
        patterns.append({
            "rule_id": rule.id,
            "target_type": rule.target.type,
            "target_ids": list(rule.target.ids),
            "alternatives": rule.params["alternatives"],
        })
    return patterns


def _own_head_class_only(rule: RuleDefinition) -> bool:
    return bool(rule.params.get("own_head_class_only"))


def generation_teacher_forbidden_slots(group: RuleGroupDocument) -> dict[int, set[tuple[int, int]]]:
    """Return hard teacher-specific unavailable slots for schedule generation.

    Accepts ``teacher_forbidden_slots`` and ``slot_forbidden`` with a teacher
    target. Rules with ``params.own_head_class_only`` are excluded; use
    ``generation_teacher_class_forbidden_slots`` instead.
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "teacher"
        ):
            continue
        if rule.code == "teacher_forbidden_slots":
            if _own_head_class_only(rule):
                continue
        elif rule.code != "slot_forbidden":
            continue
        pairs = _forbidden_slot_pairs(rule)
        if pairs:
            for teacher_id in rule.target.ids:
                result[teacher_id].update(pairs)
    return result


def generation_global_forbidden_slots(group: RuleGroupDocument) -> set[tuple[int, int]]:
    """Return hard globally unavailable ``(weekday, period)`` pairs.

    ``slot_forbidden`` with a global target means no class may place any lesson
    in those slots. Callers expand this onto every class in the generation set.
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: set[tuple[int, int]] = set()
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "slot_forbidden"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "global"
        ):
            continue
        pairs = _forbidden_slot_pairs(rule)
        if pairs:
            result.update(pairs)
    return result


def generation_teacher_class_forbidden_slots(
    group: RuleGroupDocument,
    class_head_teacher_ids: Mapping[int, int | None],
) -> dict[tuple[int, int], set[tuple[int, int]]]:
    """Ban a head teacher only in their own class at given slots (e.g. R17-01).

    Key is ``(teacher_id, class_id)`` → forbidden ``(weekday, period)`` pairs.
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)
    heads = {
        int(class_id): int(teacher_id)
        for class_id, teacher_id in class_head_teacher_ids.items()
        if teacher_id is not None
    }
    if not heads:
        return {}
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "teacher_forbidden_slots"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or not _own_head_class_only(rule)
        ):
            continue
        pairs = _forbidden_slot_pairs(rule)
        if not pairs:
            continue
        target_ids = {int(tid) for tid in rule.target.ids} if rule.target.ids else None
        for class_id, head_id in heads.items():
            if target_ids is not None and head_id not in target_ids:
                continue
            result[(head_id, class_id)].update(pairs)
    return result


def teacher_slot_is_forbidden(
    teacher_id: int | None,
    class_id: int,
    weekday: int,
    period: int,
    *,
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    teacher_class_forbidden_slots: Mapping[tuple[int, int], set[tuple[int, int]]] | None = None,
) -> bool:
    """True if teacher cannot teach this class at (weekday, period)."""
    if teacher_id is None:
        return False
    tid = int(teacher_id)
    slot = (int(weekday), int(period))
    if slot in (teacher_forbidden_slots or {}).get(tid, ()):
        return True
    if slot in (teacher_class_forbidden_slots or {}).get((tid, int(class_id)), ()):
        return True
    return False


def generation_teacher_required_evening_weekdays(
    group: RuleGroupDocument,
) -> dict[int, set[int]]:
    """Hard evening days a teacher must occupy (e.g. 黄淑梅 周一+周二).

    Read from ``teacher_forbidden_slots`` params ``require_weekdays``.
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[int, set[int]] = {}
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        days = rule.params.get("require_weekdays")
        if (
            not rule.enabled
            or rule.code != "teacher_forbidden_slots"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "teacher"
            or not _positive_int_list(days)
        ):
            continue
        required = {int(day) for day in days}
        for teacher_id in rule.target.ids:
            tid = int(teacher_id)
            result.setdefault(tid, set()).update(required)
    return result


def generation_r15_exempt_teacher_ids(group: RuleGroupDocument) -> set[int]:
    """晚课已有星期限定的教师不套 R15。

    例如屈金只能周一/周四、黄淑梅只能周一/周二、王淑华只排周二：
    连日铺开与这些限定冲突，只执行限定规则。
    只禁一天（如董舰洋周一）仍走 R15。
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    exempt: set[int] = set()
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None or compiled.status != "ready":
            continue
        if (
            not rule.enabled
            or rule.priority != "hard"
            or rule.code != "teacher_forbidden_slots"
            or rule.target.type != "teacher"
            or rule.period_scope != "evening"
        ):
            continue
        has_required = bool(_positive_int_list(rule.params.get("require_weekdays")))
        many_banned_days = bool(rule.weekdays) and len(rule.weekdays) >= 3
        if has_required or many_banned_days:
            exempt.update(int(teacher_id) for teacher_id in rule.target.ids)
    return exempt


def generation_class_slot_required_teachers(
    group: RuleGroupDocument,
) -> dict[tuple[int, int], dict[int, int]]:
    """Pin a teacher to a class at (weekday, period), e.g. 张卓 10班周一晚课.

    Reads ``teacher_preferred_weekdays`` rules that set ``params.class_id``.
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[tuple[int, int], dict[int, int]] = defaultdict(dict)
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        class_id = rule.params.get("class_id")
        if (
            not rule.enabled
            or rule.code != "teacher_preferred_weekdays"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "teacher"
            or not _positive_int(class_id)
            or not rule.target.ids
            or not rule.weekdays
        ):
            continue
        periods = _evening_rule_periods(rule) if rule.period_scope == "evening" else (list(rule.periods) or [10])
        teacher_id = int(rule.target.ids[0])
        for weekday in rule.weekdays:
            for period in periods:
                result[(int(weekday), int(period))][int(class_id)] = teacher_id
    return result


def merge_required_teachers_by_slot(
    group: RuleGroupDocument,
    class_head_teacher_ids: Mapping[int, int | None],
) -> dict[tuple[int, int], dict[int, int]]:
    """Head-teacher slots (R02) plus class-specific pins (R19)."""
    heads = {
        int(class_id): int(teacher_id)
        for class_id, teacher_id in class_head_teacher_ids.items()
        if teacher_id is not None
    }
    result: dict[tuple[int, int], dict[int, int]] = {}
    for slot in generation_required_teacher_slots(group):
        result[slot] = dict(heads)
    for slot, class_map in generation_class_slot_required_teachers(group).items():
        bucket = result.setdefault(slot, {})
        bucket.update(class_map)
    return result


def generation_required_teacher_slots(group: RuleGroupDocument) -> set[tuple[int, int]]:
    """Return hard slots that must be staffed by each class's head teacher."""
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: set[tuple[int, int]] = set()
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "slot_teacher_role_required"
            or rule.priority != "hard"
            or compiled.status != "ready"
        ):
            continue
        result.update(_slot_positions(rule))
    return result


def generation_subject_forbidden_slots(group: RuleGroupDocument) -> dict[int, set[tuple[int, int]]]:
    """Return hard subject-level unavailable slots (code ``slot_forbidden``)."""
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "slot_forbidden"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "subject"
        ):
            continue
        pairs = {(weekday, period) for weekday in rule.weekdays for period in rule.periods}
        if pairs:
            for subject_id in rule.target.ids:
                result[subject_id].update(pairs)
    return result


def generation_subject_allowed_slots(group: RuleGroupDocument) -> dict[int, set[tuple[int, int]]]:
    """Return hard subject-level allowed slots (code ``subject_allowed_slots``).

    Callers convert the returned allow-list into forbidden complements against
    the generation time universe (days x periods_per_day).
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "subject_allowed_slots"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "subject"
        ):
            continue
        pairs = {(weekday, period) for weekday in rule.weekdays for period in rule.periods}
        if pairs:
            for subject_id in rule.target.ids:
                result[subject_id].update(pairs)
    return result


def generation_class_slot_allowed_subjects(group: RuleGroupDocument) -> dict[int, dict[tuple[int, int], set[int]]]:
    """Return hard per-class slot allow-lists.

    Includes ``class_allowed_subjects`` and ``slot_forbidden`` with a class
    target (treated as forbid-all at those slots). The result maps
    class_id -> (weekday, period) -> subjects allowed there.
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[int, dict[tuple[int, int], set[int]]] = defaultdict(dict)

    def _merge_allowed(class_id: int, key: tuple[int, int], allowed_subjects: set[int], *, forbid_all: bool) -> None:
        if key not in result[class_id]:
            result[class_id][key] = set(allowed_subjects)
        elif forbid_all:
            result[class_id][key] = set()
        else:
            result[class_id][key] &= allowed_subjects

    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "class"
        ):
            continue
        if rule.code == "class_allowed_subjects":
            forbid_all = bool(rule.params.get("forbid_all"))
            allowed_subjects = set() if forbid_all else set(rule.params.get("allowed_subject_ids") or [])
            for weekday in rule.weekdays:
                for period in rule.periods:
                    for class_id in rule.target.ids:
                        _merge_allowed(int(class_id), (weekday, period), allowed_subjects, forbid_all=forbid_all)
            continue
        if rule.code != "slot_forbidden" or not rule.weekdays or not rule.periods:
            continue
        for weekday in rule.weekdays:
            for period in rule.periods:
                for class_id in rule.target.ids:
                    _merge_allowed(int(class_id), (weekday, period), set(), forbid_all=True)
    return result


def generation_early_subject_ids(group: RuleGroupDocument) -> set[int]:
    """Subject IDs that should be packed into earlier daytime periods (soft)."""
    ids: set[int] = set()
    for pref in generation_early_subject_prefs(group):
        ids.update(pref["subject_ids"])
    return ids


def generation_early_subject_prefs(group: RuleGroupDocument) -> list[dict[str, Any]]:
    """主科靠前：学科、尽量安排的节次、每个班每门课允许排在这些节次之外的数量。"""
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: list[dict[str, Any]] = []
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "subject_prefer_early_periods"
            or compiled.status != "ready"
            or rule.target.type != "subject"
        ):
            continue
        max_raw = rule.params.get("max_outside")
        try:
            max_outside = max(0, int(max_raw))
        except (TypeError, ValueError):
            max_outside = 0
        result.append({
            "subject_ids": [int(subject_id) for subject_id in rule.target.ids],
            "periods": [int(period) for period in (rule.periods or []) if int(period) >= 1],
            "max_outside": max_outside,
            "priority": rule.priority,
        })
    return result


def generation_gap_fill_late_subjects(group: RuleGroupDocument) -> tuple[set[int], int]:
    """Subjects used to fill leftover daytime slots, preferring period >= late_from."""
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    ids: set[int] = set()
    late_from: int | None = None
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "subject_gap_fill_late_periods"
            or compiled.status != "ready"
            or rule.target.type != "subject"
        ):
            continue
        ids.update(int(subject_id) for subject_id in rule.target.ids)
        value = int(rule.params.get("late_from_period") or 8)
        late_from = value if late_from is None else min(late_from, value)
    return ids, late_from or 8


def generation_class_required_subject_slots(group: RuleGroupDocument) -> dict[int, dict[tuple[int, int], set[int]]]:
    """Return hard class slots that must be occupied by one allowed subject."""
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[int, dict[tuple[int, int], set[int]]] = defaultdict(dict)
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "class_allowed_subjects"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or not rule.params.get("require_occupied_slots")
        ):
            continue
        allowed = set(int(subject_id) for subject_id in rule.params["allowed_subject_ids"])
        for class_id in rule.target.ids:
            for weekday in rule.weekdays:
                for period in rule.periods:
                    result[int(class_id)][(weekday, period)] = allowed
    return result


def generation_evening_self_study_candidates(group: RuleGroupDocument) -> dict[int, set[int]]:
    """This rule no longer skips evenings: 自习 is periods 8–9, 晚自习 stays 6+6."""
    return {}


def generation_evening_free_days(group: RuleGroupDocument) -> dict[int, set[int]]:
    """Do not reserve empty evenings. 没有晚自习不叫自习；晚自习必须排满。"""
    return {}


def _teacher_ids_for_subject_target(
    subject_ids: Iterable[int],
    *,
    teachers_by_subject: Mapping[int, Iterable[int]] | None = None,
    rows: Iterable[ScheduleItem] | None = None,
) -> set[int]:
    """任教所列学科的教师 ID（生成用任教关系，校验用已排课表）。"""
    subjects = {int(subject_id) for subject_id in subject_ids}
    result: set[int] = set()
    if teachers_by_subject:
        for subject_id in subjects:
            result.update(int(teacher_id) for teacher_id in teachers_by_subject.get(subject_id, []))
    if rows:
        for item in rows:
            if item.teacher_id is not None and int(item.subject_id) in subjects:
                result.add(int(item.teacher_id))
    return result


def generation_gap_free_groups(
    group: RuleGroupDocument,
    *,
    teachers_by_subject: Mapping[int, Iterable[int]] | None = None,
) -> list[dict[str, Any]]:
    """Hard teacher gap-free groups: [{"teachers": [ids], "weekdays": [days]}].

    每组表示“这些教师在这些星期，当天课程必须连续无空堂”。同一教师可出现在
    多个组（如周六一组、工作日一组）。

    ``target.type=subject``：展开为任教这些学科的教师（需传入 teachers_by_subject）。
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    groups: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "teacher_gap_free"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type not in {"teacher", "subject"}
        ):
            continue
        if rule.target.type == "teacher":
            ids = sorted({int(teacher_id) for teacher_id in rule.target.ids})
        else:
            ids = sorted(
                _teacher_ids_for_subject_target(
                    rule.target.ids,
                    teachers_by_subject=teachers_by_subject,
                )
            )
        if not ids:
            continue
        weekdays = list(rule.weekdays)
        key = (tuple(ids), tuple(weekdays))
        if key in seen:
            continue
        seen.add(key)
        groups.append({"teachers": ids, "weekdays": weekdays})
    return groups


def generation_class_gap_free_weekdays(group: RuleGroupDocument) -> list[int]:
    """Hard class_gap_free weekdays to pack periods 1–7 (union of matching rules)."""
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    days: set[int] = set()
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "class_gap_free"
            or rule.params.get("trailing_empty") is True
            or rule.priority != "hard"
            or compiled.status != "ready"
        ):
            continue
        if rule.weekdays:
            days.update(int(day) for day in rule.weekdays)
        else:
            days.update(range(1, 7))
    return sorted(days)


def generation_class_prefix_groups(group: RuleGroupDocument) -> list[dict[str, Any]]:
    ready = {r.rule_id for r in compile_rule_group(group) if r.status == "ready"}
    return [dict(classes=rule.target.ids, weekdays=rule.weekdays, periods=rule.periods,
                 week_parity=rule.week_parity)
            for rule in group.rules if rule.id in ready and rule.enabled
            and rule.code == "class_gap_free" and rule.priority == "hard"
            and rule.params.get("trailing_empty") is True]


def _daytime_parity_sides(rule: RuleDefinition) -> tuple[list[int], list[int]] | None:
    """Return (odd_subject_ids, even_subject_ids); partners within sides are free."""
    odd_raw = rule.params.get("odd_subject_ids")
    even_raw = rule.params.get("even_subject_ids")
    if odd_raw is not None or even_raw is not None:
        try:
            odd_ids = [int(x) for x in (odd_raw or [])]
            even_ids = [int(x) for x in (even_raw or [])]
        except (TypeError, ValueError):
            return None
    elif rule.target.type == "subject" and len(rule.target.ids) == 2:
        odd_ids = [int(rule.params.get("odd_subject_id") or rule.target.ids[0])]
        even_ids = [int(rule.params.get("even_subject_id") or rule.target.ids[1])]
    else:
        return None
    if not odd_ids or not even_ids:
        return None
    if len(set(odd_ids)) != len(odd_ids) or len(set(even_ids)) != len(even_ids):
        return None
    if set(odd_ids) & set(even_ids):
        return None
    return odd_ids, even_ids


def generation_daytime_parity_pairs(group: RuleGroupDocument) -> list[dict[str, Any]]:
    """Daytime same-slot parity groups for CP-SAT (odd side vs even side)."""
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    pairs: list[dict[str, Any]] = []
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "subject_daytime_parity_pair"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or not rule.weekdays
            or not rule.periods
        ):
            continue
        sides = _daytime_parity_sides(rule)
        if sides is None:
            continue
        odd_ids, even_ids = sides
        pairs.append({
            "odd_subjects": odd_ids,
            "even_subjects": even_ids,
            # 兼容旧两元对课
            "subjects": (odd_ids[0], even_ids[0]) if len(odd_ids) == 1 and len(even_ids) == 1 else (),
            "weekdays": list(rule.weekdays),
            "periods": list(rule.periods),
        })
    return pairs


def generation_evening_parity_pairs(group: RuleGroupDocument) -> list[tuple[int, int]]:
    """Return hard evening parity pairs (odd subject, even subject) for the builder."""
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    pairs: list[tuple[int, int]] = []
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "subject_evening_parity_pair"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "subject"
            or len(rule.target.ids) != 2
        ):
            continue
        pairs.append((int(rule.target.ids[0]), int(rule.target.ids[1])))
    return pairs


def generation_teacher_evening_daytime_links(group: RuleGroupDocument) -> list[dict[str, Any]]:
    """Return hard teacher evening↔daytime link constraints for generation/repair.

    Semantics: on any day the teacher has an evening lesson, that same day must
    also contain ``required_daytime_period``. Weekly period quotas belong in
    ``teacher_period_minimum``, not here.
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    links: list[dict[str, Any]] = []
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "teacher_evening_daytime_link"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "teacher"
        ):
            continue
        for teacher_id in rule.target.ids:
            start = rule.params.get("evening_start_period")
            links.append({
                "teacher_id": int(teacher_id),
                # 缺省时由调用方传入网格的晚自习起始节次（当前为第10节）
                "evening_start_period": int(start) if start is not None else None,
                "required_daytime_period": int(rule.params["required_daytime_period"]),
            })
    return links


def generation_slot_teacher_balance_scope(group: RuleGroupDocument) -> tuple[list[int], list[int], int | None] | None:
    """Return (weekdays, periods, max_per_teacher) of the first enabled slot_teacher_balance rule."""
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            rule.enabled
            and rule.code == "slot_teacher_balance"
            and compiled.status == "ready"
        ):
            cap = rule.params.get("max_per_teacher")
            return list(rule.weekdays), list(rule.periods), (int(cap) if _positive_int(cap) else None)
    return None


def generation_consecutive_requirements(group: RuleGroupDocument) -> dict[str, list[dict[str, Any]]]:
    """Extract hard consecutive-block requirements for the block repair pass.

    同一教师可能同时有周六连堂与工作日连堂两条规则，因此返回列表而不是
    按目标 ID 的字典，避免相互覆盖。重复的（目标, 范围, 参数）会去重。
    ``{"subjects": [{"target_id":..., "min_block":..., "min_days":..., "weekdays":[...]}],
       "teachers": [...]}``
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[str, list[dict[str, Any]]] = {"subjects": [], "teachers": []}
    seen: set[tuple] = set()
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if not rule.enabled or rule.priority != "hard" or compiled.status != "ready":
            continue
        if rule.code not in {"subject_consecutive", "teacher_consecutive"}:
            continue
        if rule.target.type not in {"subject", "teacher"}:
            continue
        kind = "subjects" if rule.code == "subject_consecutive" else "teachers"
        for target_id in rule.target.ids:
            entry = {
                "target_id": int(target_id),
                "min_block": int(rule.params["minimum_block_length"]),
                "min_days": int(rule.params["minimum_days"]),
                "weekdays": list(rule.weekdays),
            }
            if kind == "teachers":
                # 同班连堂与跨班连堂是两种不同的排课语义；旧规则默认同班。
                entry["class_mode"] = str(rule.params.get("class_mode") or "same_class")
            key = (kind, entry["target_id"], tuple(entry["weekdays"]), entry["min_block"], entry["min_days"])
            if key in seen:
                continue
            seen.add(key)
            result[kind].append(entry)
    return result


def generation_teacher_daily_limits(
    group: RuleGroupDocument,
    *,
    teachers_by_subject: Mapping[int, Iterable[int]] | None = None,
) -> dict[int, int]:
    """Return hard per-teacher daily lesson limits (code ``teacher_daily_limit``).

    ``target.type=teacher``：直接作用于所列教师。
    ``target.type=subject``：作用于任教这些学科的教师（需传入 teachers_by_subject）。
    同一教师多条规则时取最严（最小）上限。
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[int, int] = {}
    subject_teachers = {
        int(subject_id): {int(teacher_id) for teacher_id in teacher_ids}
        for subject_id, teacher_ids in (teachers_by_subject or {}).items()
    }

    def apply_limit(teacher_id: int, limit: int) -> None:
        current = result.get(teacher_id)
        result[teacher_id] = limit if current is None else min(current, limit)

    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "teacher_daily_limit"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type not in {"teacher", "subject"}
        ):
            continue
        limit = rule.params.get("max_lessons_per_day")
        if not _positive_int(limit):
            continue
        limit_i = int(limit)
        if rule.target.type == "teacher":
            for teacher_id in rule.target.ids:
                apply_limit(int(teacher_id), limit_i)
            continue
        for subject_id in rule.target.ids:
            for teacher_id in subject_teachers.get(int(subject_id), set()):
                apply_limit(teacher_id, limit_i)
    return result


def generation_teacher_period_minima(group: RuleGroupDocument) -> list[dict[str, Any]]:
    """Hard teacher_period_minimum: at least N lessons in given periods/weekdays."""
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: list[dict[str, Any]] = []
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "teacher_period_minimum"
            or rule.priority != "hard"
            or compiled.status != "ready"
            or rule.target.type != "teacher"
        ):
            continue
        periods = [int(p) for p in (rule.periods or rule.params.get("periods") or [])]
        minimum = rule.params.get("minimum_lessons")
        if not periods or not _positive_int(minimum):
            continue
        weekdays = [int(day) for day in rule.weekdays] if rule.weekdays else []
        for teacher_id in rule.target.ids:
            result.append({
                "teacher_id": int(teacher_id),
                "periods": periods,
                "weekdays": weekdays,
                "minimum": int(minimum),
            })
    return result


def _missing_parameter(rule: RuleDefinition) -> str | None:
    if rule.code == "student_contiguous":
        if (rule.priority != "hard" or rule.schedule_scope != "walk" or rule.target.type != "global"
                or rule.period_scope != "regular" or rule.week_parity != "all"
                or set(rule.params) - {"fill_self_study"}
                or ("fill_self_study" in rule.params and not isinstance(rule.params["fill_self_study"], bool))
                or sorted(rule.periods) != list(range(1, len(rule.periods) + 1)) or not rule.periods):
            return "学生课程连续仅支持全局、走班、白天每周硬约束，节次须从第1节连续选择"
        return None
    if rule.code == "student_gap_minimize":
        if (rule.priority != "soft" or rule.schedule_scope != "walk"
                or rule.target.type != "global" or rule.period_scope != "regular"
                or rule.week_parity != "all" or rule.params):
            return "学生减少空档仅支持全局、走班、白天每周软目标，可选择星期和优先节次"
        return None
    if rule.code == "manual_review":
        # manual_review 本身就是“仅人工确认、不绑定算法”的规则类型，可编译。
        return None
    if rule.code == "teacher_daily_limit":
        if not _positive_int(rule.params.get("max_lessons_per_day")):
            return "缺少 max_lessons_per_day"
        if rule.target.type not in {"teacher", "subject"}:
            return "每日课时上限只支持教师或学科目标"
    if rule.code == "teacher_multi_class_evening_adjacent":
        if not _positive_int(rule.params.get("minimum_class_count")) or int(rule.params["minimum_class_count"]) < 2:
            return "minimum_class_count 必须至少为 2"
        if rule.period_scope != "evening":
            return "该规则必须限定为晚课"
    if rule.code in {"teacher_consecutive", "subject_consecutive"}:
        if not _positive_int(rule.params.get("minimum_block_length")):
            return "缺少 minimum_block_length"
        if not _positive_int(rule.params.get("minimum_days")):
            return "缺少 minimum_days"
        expected_target = "subject" if rule.code == "subject_consecutive" else "teacher"
        if rule.target.type != expected_target:
            return (
                "学科连堂必须作用于学科"
                if rule.code == "subject_consecutive"
                else "教师连堂必须作用于教师"
            )
        if rule.code == "teacher_consecutive" and rule.params.get("class_mode", "same_class") not in {
            "same_class", "cross_class"
        }:
            return "教师连堂 class_mode 必须为 same_class 或 cross_class"
    if rule.code == "teacher_gap_free" and rule.target.type not in {"teacher", "subject"}:
        return "教师无空节规则必须作用于教师或学科"
    if rule.code == "class_gap_free" and rule.target.type not in {"class", "global"}:
        return "班级无空节规则必须作用于班级或全局"
    if rule.code == "class_gap_free" and "trailing_empty" in rule.params:
        if type(rule.params["trailing_empty"]) is not bool:
            return "trailing_empty 必须为布尔值"
        if rule.params["trailing_empty"] and (not rule.periods or rule.priority != "hard"
                                             or rule.period_scope != "regular"):
            return "末尾可空规则须选择节次，并使用白天硬约束"
    if rule.code == "subject_evening_parity_pair":
        if rule.target.type != "subject" or len(rule.target.ids) != 2:
            return "单双周对课规则必须提供两个学科目标（单周学科、双周学科）"
        if rule.period_scope != "evening":
            return "单双周对课规则必须限定为晚课"
    if rule.code == "subject_daytime_parity_pair":
        if rule.period_scope != "regular":
            return "白天单双周对课必须限定为白天课"
        if not rule.weekdays or not rule.periods:
            return "白天单双周对课必须同时提供星期和节次"
        if _daytime_parity_sides(rule) is None:
            return "白天单双周对课须配置单周学科组与双周学科组，且两组互不重叠"
    if rule.code == "class_allowed_subjects":
        allowed_ids = rule.params.get("allowed_subject_ids")
        # forbid_all / 空列表 = 该课位不排任何学科
        if rule.params.get("forbid_all") is True:
            if allowed_ids not in (None, [], ()):
                return "forbid_all 时 allowed_subject_ids 必须为空"
        elif not _positive_int_list(allowed_ids):
            return "缺少 allowed_subject_ids"
    if rule.code == "teacher_evening_daytime_link":
        if rule.target.type != "teacher":
            return "晚课联动规则必须作用于教师"
        if not _positive_int(rule.params.get("required_daytime_period")):
            return "缺少 required_daytime_period"
    if rule.code == "teacher_period_minimum":
        if rule.target.type != "teacher":
            return "教师节次下限规则必须作用于教师"
        periods = rule.periods or rule.params.get("periods")
        if not _positive_int_list(periods):
            return "缺少 periods（节次集合）"
        if not _positive_int(rule.params.get("minimum_lessons")):
            return "缺少 minimum_lessons"
    if rule.code == "class_slot_pattern":
        if rule.target.type != "subject":
            return "课位组合分布必须作用于学科"
        if len(rule.target.ids) != 1:
            return "课位组合分布每次只能作用于一个学科"
        alternatives = rule.params.get("alternatives")
        if not _valid_slot_pattern_alternatives(alternatives):
            return "缺少有效的 alternatives 课位组合"
    if rule.code == "class_evening_self_study_day":
        if rule.target.type != "class":
            return "自习日规则必须作用于班级"
        if len(rule.weekdays) < 2:
            return "自习日规则至少需要两个候选星期"
        choose_count = rule.params.get("choose_count")
        if not _positive_int(choose_count) or int(choose_count) > len(rule.weekdays):
            return "choose_count 必须在候选星期数量范围内"
    if rule.code == "teacher_forbidden_slots":
        specific_slots = rule.params.get("forbidden_slots")
        if specific_slots is not None:
            if not _valid_forbidden_slots(specific_slots):
                return "缺少有效的 forbidden_slots 课位清单"
        elif not rule.weekdays or not rule.periods:
            return "教师禁排规则必须同时提供 weekdays 和 periods，或 forbidden_slots 课位清单"
        require_days = rule.params.get("require_weekdays")
        if require_days is not None and not _positive_int_list(require_days):
            return "require_weekdays 必须是正整数星期列表"
    if rule.code == "slot_teacher_balance":
        if not rule.weekdays or not rule.periods:
            return "节次教师均衡必须同时提供 weekdays 和 periods"
        if not _positive_int(rule.params.get("max_per_teacher")):
            return "缺少 max_per_teacher"
    if rule.code == "slot_teacher_role_required":
        if rule.params.get("teacher_role") != "head_teacher":
            return "班主任课位规则必须指定 teacher_role=head_teacher"
        if rule.target.type not in {"slot", "global"}:
            return "班主任课位规则必须作用于课位或全局"
        has_weekdays_periods = bool(rule.weekdays) and bool(rule.periods)
        has_slot_ids = rule.target.type == "slot" and _valid_slot_target_ids(rule.target.ids)
        if not has_weekdays_periods and not has_slot_ids:
            return "班主任课位规则必须提供 weekdays+periods，或有效的课位目标"
    if rule.code == "subject_prefer_early_periods":
        if rule.target.type != "subject":
            return "主科靠前规则必须作用于学科"
    if rule.code == "subject_gap_fill_late_periods":
        if rule.target.type != "subject":
            return "活动课补空规则必须作用于学科"
        late_from = rule.params.get("late_from_period", 8)
        if not _positive_int(late_from):
            return "缺少 late_from_period"
    if rule.code == "subject_allowed_slots":
        if rule.target.type != "subject":
            return "学科课位限制必须作用于学科"
        if not rule.weekdays or not rule.periods:
            return "允许课位规则必须同时提供 weekdays 和 periods"
    if rule.code == "slot_allowed" and (not rule.weekdays or not rule.periods):
        return "允许课位规则必须同时提供 weekdays 和 periods"
    if rule.code == "slot_forbidden":
        if rule.target.type not in {"subject", "teacher", "class", "global"}:
            return "课位禁排只支持学科、教师、班级或全局"
        if not rule.weekdays or not rule.periods:
            return "课位禁排必须同时提供 weekdays 和 periods"
    return None


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_int_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_positive_int(item) for item in value)


def _valid_slot_pattern_alternatives(value: Any) -> bool:
    """Validate an OR-of-AND slot pattern without interpreting display text."""
    if not isinstance(value, list) or not value:
        return False
    for alternative in value:
        if not isinstance(alternative, list) or not alternative:
            return False
        total = 0
        for group in alternative:
            if not isinstance(group, dict):
                return False
            weekdays = group.get("weekdays")
            periods = group.get("periods")
            count = group.get("count")
            if (
                not isinstance(weekdays, list) or not weekdays
                or not all(isinstance(day, int) and 1 <= day <= 7 for day in weekdays)
                or not isinstance(periods, list) or not periods
                or not all(isinstance(period, int) and 1 <= period <= 12 for period in periods)
                or not _positive_int(count)
            ):
                return False
            total += count
        if total <= 0:
            return False
    totals = {
        sum(int(group["count"]) for group in alternative)
        for alternative in value
    }
    return len(totals) == 1


def _valid_forbidden_slots(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for slot in value:
        if not isinstance(slot, dict):
            return False
        weekday = slot.get("weekday")
        periods = slot.get("periods")
        if (
            not isinstance(weekday, int) or not 1 <= weekday <= 7
            or not isinstance(periods, list) or not periods
            or not all(isinstance(period, int) and 1 <= period <= 12 for period in periods)
        ):
            return False
    return True


def _valid_slot_target_ids(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, int)
        and not isinstance(item, bool)
        and 1 <= item // 100 <= 7
        and 1 <= item % 100 <= 12
        for item in value
    )


def _evening_rule_periods(rule: RuleDefinition, *, evening_start: int = 10) -> list[int]:
    """晚课规则的节次列表。

    前端曾把「第10节」解析成 periods=[1]；period_scope=evening 时若节次都小于
    晚自习起点，回落到 evening_start，避免禁排/钉人落到白天第1节。
    """
    periods = [int(period) for period in (rule.periods or [])]
    if rule.period_scope == "evening" and (
        not periods or all(period < int(evening_start) for period in periods)
    ):
        return [int(evening_start)]
    return periods


def _slot_positions(rule: RuleDefinition) -> set[tuple[int, int]]:
    """Resolve (weekday, period) pairs for a slot-targeted rule.

    Prefer explicit weekdays/periods when present so a stale slot id
    (e.g. 609 leftover from 第9节晚课) cannot override 周六第10节.
    """
    periods = _evening_rule_periods(rule) if rule.period_scope == "evening" else list(rule.periods or [])
    if rule.weekdays and periods:
        return {(int(day), int(period)) for day in rule.weekdays for period in periods}
    return {(item // 100, item % 100) for item in rule.target.ids}


def _forbidden_slot_pairs(rule: RuleDefinition) -> set[tuple[int, int]]:
    specific_slots = rule.params.get("forbidden_slots")
    if isinstance(specific_slots, list):
        return {
            (int(slot["weekday"]), int(period))
            for slot in specific_slots
            if isinstance(slot, dict)
            for period in slot.get("periods", [])
        }
    periods = _evening_rule_periods(rule) if rule.period_scope == "evening" else list(rule.periods or [])
    return {
        (weekday, period)
        for weekday in rule.weekdays
        for period in periods
    }


def evaluate_rule_group(
    group: RuleGroupDocument,
    items: Iterable[ScheduleItem],
    *,
    schedule_available: bool = True,
    evening_start_period: int | None = None,
    class_head_teacher_ids: dict[int, int | None] | None = None,
    schedule_mode: Literal["admin", "walk"] = "admin",
    shared_items: Iterable[ScheduleItem] = (),
    student_occupied_by_parity: dict | None = None,
    student_self_study_by_parity: dict | None = None,
) -> RuleEvaluationSummary:
    """Evaluate enabled rules against a generated or persisted weekly schedule."""
    group = rules_for_schedule(group, schedule_mode)
    compiled = compile_rule_group(group)
    rows = list(items)
    # 共用教师规则可计入另一种课表；专属规则只校验本次课表。
    combined_rows = rows + list(shared_items)
    by_id = {item.rule_id: item for item in compiled}
    class_slot_allowed = generation_class_slot_allowed_subjects(group)
    early_subject_ids = generation_early_subject_ids(group)
    gap_fill_ids = generation_gap_fill_late_subjects(group)[0]
    r15_exempt_teachers = generation_r15_exempt_teacher_ids(group)
    results: list[RuleEvaluationResult] = []
    unresolved: list[dict[str, str]] = []
    for rule in group.rules:
        if not rule.enabled:
            continue
        compiled_rule = by_id[rule.id]
        if compiled_rule.status == "unresolved":
            reason = compiled_rule.reason or "规则无法编译"
            unresolved.append({"rule_id": rule.id, "message": reason})
            results.append(RuleEvaluationResult(
                rule_id=rule.id, code=rule.code, title=rule.title, priority=rule.priority,
                status="unresolved", message=reason,
            ))
            continue
        if rule.code == "manual_review":
            # manual_review 只能由人工确认，无论课表是否存在都不参与阻断。
            results.append(RuleEvaluationResult(
                rule_id=rule.id, code=rule.code, title=rule.title, priority=rule.priority,
                status="manual",
                message="该规则需人工确认，不参与自动排课与自动校验",
            ))
            continue
        if not schedule_available:
            results.append(RuleEvaluationResult(
                rule_id=rule.id, code=rule.code, title=rule.title, priority=rule.priority,
                status="not_run", message="当前还没有可校验的课表",
            ))
            continue
        if rule.code in {"student_gap_minimize", "student_contiguous"}:
            if student_occupied_by_parity is None:
                results.append(RuleEvaluationResult(
                    rule_id=rule.id, code=rule.code, title=rule.title, priority=rule.priority,
                    status="not_run", message="需学生名单和公共课、走班课合并后校验",
                ))
            else:
                from app.services.scheduling.student_gaps import count_student_gaps, count_student_unfilled, count_student_prefix_gaps
                preferred = {day: rule.periods or list(range(1, 8)) for day in (rule.weekdays or range(1, 8))}
                if rule.code == "student_contiguous":
                    if rule.params.get("fill_self_study"):
                        studies = student_self_study_by_parity or {}
                        covered = {parity: {sid: set(slots) | studies.get(parity, {}).get(sid, set())
                            for sid, slots in occupied.items()} for parity, occupied in student_occupied_by_parity.items()}
                        collisions = sum(len(set(slots) & studies.get(parity, {}).get(sid, set()))
                            for parity, occupied in student_occupied_by_parity.items() for sid, slots in occupied.items())
                        missing = count_student_unfilled(covered, preferred)
                        count = sum(len(studies.get(parity, {}).get(sid, set()))
                            for parity, occupied in student_occupied_by_parity.items() for sid in occupied)
                        results.append(RuleEvaluationResult(
                            rule_id=rule.id, code=rule.code, title=rule.title, priority=rule.priority,
                            status="fail" if missing or collisions else "pass",
                            violation_count=missing + collisions, penalty=missing + collisions,
                            metrics={"student_unfilled": missing, "student_self_study": count, "self_study_conflicts": collisions},
                            message=f"空节 {missing}，自习冲突 {collisions}，自习 {count}（单双周合计）",
                        ))
                        continue
                    gaps = count_student_prefix_gaps(student_occupied_by_parity, preferred)
                    results.append(RuleEvaluationResult(
                        rule_id=rule.id, code=rule.code, title=rule.title, priority=rule.priority,
                        status="fail" if gaps else "pass", violation_count=gaps, penalty=gaps,
                        metrics={"student_prefix_gaps": gaps},
                        message=f"课程开始前及中间空节 {gaps}（单双周合计），末尾可空",
                    ))
                    continue
                gaps = count_student_gaps(student_occupied_by_parity, preferred, preferred)
                missing = count_student_unfilled(student_occupied_by_parity, preferred)
                results.append(RuleEvaluationResult(
                    rule_id=rule.id, code=rule.code, title=rule.title, priority=rule.priority,
                    status="fail" if missing else "pass", violation_count=missing, penalty=missing + gaps,
                    metrics={"student_gaps": gaps, "student_unfilled": missing},
                    message=f"优先节次空节 {missing}，其中内部空节 {gaps}（单双周合计）",
                ))
            continue
        results.append(_evaluate_ready_rule(
            rule,
            combined_rows if rule.schedule_scope == "all" else rows,
            evening_start_period=evening_start_period,
            class_head_teacher_ids=class_head_teacher_ids,
            class_slot_allowed_subjects=class_slot_allowed,
            early_subject_ids=early_subject_ids,
            gap_fill_subject_ids=gap_fill_ids,
            r15_exempt_teacher_ids=r15_exempt_teachers,
        ))

    hard_failed = any(
        result.priority == "hard" and result.status in {"fail", "unresolved", "not_run"}
        for result in results
    )
    return RuleEvaluationSummary(
        valid=not hard_failed,
        compiled=not unresolved,
        schedule_available=schedule_available,
        schedule_item_count=len(rows),
        results=results,
        unresolved=unresolved,
        score=sum(result.penalty for result in results),
    )


def _evaluate_ready_rule(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
    class_head_teacher_ids: dict[int, int | None] | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    early_subject_ids: set[int] | None = None,
    gap_fill_subject_ids: set[int] | None = None,
    r15_exempt_teacher_ids: set[int] | None = None,
) -> RuleEvaluationResult:
    if rule.code == "manual_review":
        return RuleEvaluationResult(
            rule_id=rule.id, code=rule.code, title=rule.title, priority=rule.priority,
            status="manual",
            message="该规则需人工确认，不参与自动排课与自动校验",
        )
    if rule.code == "teacher_daily_limit":
        return _teacher_daily_limit(rule, rows, evening_start_period=evening_start_period)
    if rule.code == "teacher_multi_class_evening_adjacent":
        return _teacher_multi_class_evening_adjacent(
            rule,
            rows,
            evening_start_period=evening_start_period,
            exclude_teacher_ids=r15_exempt_teacher_ids,
        )
    if rule.code in {"teacher_consecutive", "subject_consecutive"}:
        return _consecutive(rule, rows, by_subject=rule.code == "subject_consecutive")
    if rule.code == "teacher_gap_free":
        return _teacher_gap_free(rule, rows, evening_start_period=evening_start_period)
    if rule.code == "class_gap_free":
        return _class_gap_free(rule, rows, evening_start_period=evening_start_period)
    if rule.code == "subject_daily_spread":
        return _subject_daily_spread(rule, rows)
    if rule.code == "slot_teacher_balance":
        return _slot_teacher_balance(rule, rows)
    if rule.code in {"subject_evening_parity_pair", "subject_daytime_parity_pair"}:
        return _subject_parity_pair(
            rule, rows, evening_start_period=evening_start_period
        )
    if rule.code in {"slot_forbidden", "teacher_forbidden_slots", "subject_allowed_slots", "slot_allowed"}:
        return _slot_rule(
            rule,
            rows,
            evening_start_period=evening_start_period,
            class_head_teacher_ids=class_head_teacher_ids,
        )
    if rule.code == "class_allowed_subjects":
        return _class_allowed_subjects(rule, rows)
    if rule.code == "teacher_evening_daytime_link":
        return _teacher_evening_daytime_link(rule, rows, evening_start_period=evening_start_period)
    if rule.code == "teacher_period_minimum":
        return _teacher_period_minimum(rule, rows, evening_start_period=evening_start_period)
    if rule.code == "class_slot_pattern":
        return _class_slot_pattern(rule, rows)
    if rule.code == "class_evening_self_study_day":
        return _class_evening_self_study_day(
            rule,
            rows,
            early_subject_ids=early_subject_ids,
            gap_fill_subject_ids=gap_fill_subject_ids,
        )
    if rule.code == "slot_teacher_role_required":
        return _slot_teacher_role_required(rule, rows, class_head_teacher_ids=class_head_teacher_ids)
    if rule.code == "teacher_preferred_weekdays":
        return _teacher_preferred_weekdays(rule, rows, evening_start_period=evening_start_period)
    if rule.code == "subject_prefer_early_periods":
        return _subject_prefer_early_periods(rule, rows, evening_start_period=evening_start_period)
    if rule.code == "subject_gap_fill_late_periods":
        return _subject_gap_fill_late_periods(
            rule,
            rows,
            evening_start_period=evening_start_period,
            class_slot_allowed_subjects=class_slot_allowed_subjects,
        )
    return RuleEvaluationResult(
        rule_id=rule.id, code=rule.code, title=rule.title, priority=rule.priority,
        status="unresolved", message="该规则编码尚未实现执行器",
    )


def _slot_allows_subject(
    allowed_map: Mapping[int, Mapping[tuple[int, int], set[int]]],
    class_id: int,
    weekday: int,
    period: int,
    subject_id: int,
) -> bool:
    allowed = allowed_map.get(class_id, {}).get((weekday, period))
    if allowed is None:
        return True
    return subject_id in allowed


def _target_match(rule: RuleDefinition, item: ScheduleItem) -> bool:
    target = rule.target
    if target.type == "global":
        return True
    if target.type == "teacher":
        return item.teacher_id in target.ids
    if target.type == "subject":
        return item.subject_id in target.ids
    if target.type == "class":
        return item.class_id in target.ids
    return False


def _time_match(rule: RuleDefinition, item: ScheduleItem) -> bool:
    weekday_match = not rule.weekdays or item.weekday in rule.weekdays
    period_match = not rule.periods or item.period in rule.periods
    parity = WeekParity(item.week_parity)
    parity_match = rule.week_parity == "all" or parity in {WeekParity.all, WeekParity(rule.week_parity)}
    return weekday_match and period_match and parity_match


def _day_match(rule: RuleDefinition, item: ScheduleItem) -> bool:
    """星期/单双周匹配，不按 rule.periods 过滤。

    class_gap_free 检查第 1～7 节是否都有课；
    规则上的「第1～7节」若被解析成 periods=[1]，不能只统计第 1 节。
    """
    weekday_match = not rule.weekdays or item.weekday in rule.weekdays
    parity = WeekParity(item.week_parity)
    parity_match = rule.week_parity == "all" or parity in {WeekParity.all, WeekParity(rule.week_parity)}
    return weekday_match and parity_match


def _teacher_daily_limit(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
) -> RuleEvaluationResult:
    limit = int(rule.params["max_lessons_per_day"])
    # 学科目标：限制的是「任教该学科的教师」的全天总课时，不是该学科本身的课节数。
    if rule.target.type == "subject":
        teacher_ids = {
            int(item.teacher_id)
            for item in rows
            if item.teacher_id is not None and item.subject_id in set(rule.target.ids)
        }
    elif rule.target.type == "teacher":
        teacher_ids = {int(teacher_id) for teacher_id in rule.target.ids}
    else:
        return RuleEvaluationResult(
            rule_id=rule.id,
            code=rule.code,
            title=rule.title,
            priority=rule.priority,
            status="unresolved",
            message="每日课时上限只支持教师或学科目标",
        )
    odd_counts: dict[tuple[int, int], int] = defaultdict(int)
    even_counts: dict[tuple[int, int], int] = defaultdict(int)
    for item in rows:
        if item.teacher_id is None or int(item.teacher_id) not in teacher_ids:
            continue
        if rule.weekdays and item.weekday not in rule.weekdays:
            continue
        # period_scope=regular 时不计晚课：晚课负荷由晚课规则单独约束。
        if (
            rule.period_scope == "regular"
            and evening_start_period is not None
            and item.period >= int(evening_start_period)
        ):
            continue
        parity = WeekParity(item.week_parity)
        key = (int(item.teacher_id), item.weekday)
        if parity == WeekParity.odd:
            odd_counts[key] += 1
        elif parity == WeekParity.even:
            even_counts[key] += 1
        else:
            odd_counts[key] += 1
            even_counts[key] += 1
    # 0.5课时=单双周轮换：单周/双周各自计一天的真实节数，任一周超限即违规
    counts: dict[tuple[int, int], int] = {}
    for key in set(odd_counts) | set(even_counts):
        counts[key] = max(odd_counts[key], even_counts[key])
    violations = sum(count > limit for count in counts.values())
    penalty = sum(max(0, count - limit) for count in counts.values())
    return _result(rule, violations, penalty, {
        "max_lessons_per_day": limit,
        "checked_teacher_days": len(counts),
        "checked_teachers": len(teacher_ids),
    }, f"教师每日课时超过 {limit} 节的天数：{violations}")


def _teacher_evening_class_sequence(
    items: list[ScheduleItem],
    *,
    evening_start: int,
    exclude_subjects: set[int],
) -> list[int]:
    """单周周一→周六，再双周周一→周六；整周课两边都记。"""
    odd: dict[int, int] = {}
    even: dict[int, int] = {}
    for item in items:
        if item.period < evening_start or int(item.subject_id) in exclude_subjects:
            continue
        if item.week_parity != WeekParity.even:
            odd[item.weekday] = item.class_id
        if item.week_parity != WeekParity.odd:
            even[item.weekday] = item.class_id
    return [odd[day] for day in range(1, 7) if day in odd] + [even[day] for day in range(1, 7) if day in even]


def _sequence_follows_class_cycle(seq: list[int], class_ids: set[int]) -> bool:
    """各班轮转一圈再重复，进度对齐；顺序由第一次转圈决定。"""
    n = len(class_ids)
    if n < 2 or len(seq) < 2:
        return True
    if len(seq) % n != 0 or set(seq) != class_ids:
        return False
    cycle = seq[:n]
    if len(set(cycle)) != n:
        return False
    return all(cid == cycle[index % n] for index, cid in enumerate(seq))


def _teacher_multi_class_evening_adjacent(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
    exclude_teacher_ids: set[int] | None = None,
) -> RuleEvaluationResult:
    """多班教师晚课按班级轮转，让各班进度一致。

    例如带 A/B/C/D：上完 A 再上 B、再 C、再 D，然后回到 A。
    中间可以空日子。已有晚课星期限定的教师不检查本条。
    """
    minimum_class_count = int(rule.params["minimum_class_count"])
    configured_start = int(rule.params.get("evening_start_period") or evening_start_period or 9)
    exclude_subjects = {
        int(subject_id)
        for subject_id in (rule.params.get("exclude_subject_ids") or [])
        if _positive_int(subject_id)
    }
    skip_teachers = {int(teacher_id) for teacher_id in (exclude_teacher_ids or ())}
    by_teacher: dict[int, list[ScheduleItem]] = defaultdict(list)
    for item in rows:
        if not _target_match(rule, item) or item.teacher_id is None:
            continue
        if int(item.teacher_id) in skip_teachers:
            continue
        if item.period < configured_start:
            continue
        if int(item.subject_id) in exclude_subjects:
            continue
        by_teacher[int(item.teacher_id)].append(item)

    violations = 0
    checked_teachers = 0
    detail = []
    for teacher_id, items in by_teacher.items():
        class_ids = {item.class_id for item in items}
        if len(class_ids) < minimum_class_count:
            continue
        checked_teachers += 1
        seq = _teacher_evening_class_sequence(
            items, evening_start=configured_start, exclude_subjects=exclude_subjects,
        )
        if not _sequence_follows_class_cycle(seq, class_ids):
            violations += 1
            detail.append(f"师{teacher_id}{seq}")

    return _result(
        rule,
        violations,
        violations,
        {
            "minimum_class_count": minimum_class_count,
            "checked_teachers": checked_teachers,
        },
        f"已检查 {checked_teachers} 名多班教师，晚课班次轮转不合：{violations} 人"
        + (f"（{'；'.join(detail[:3])}）" if detail else ""),
    )


def _consecutive(rule: RuleDefinition, rows: list[ScheduleItem], *, by_subject: bool) -> RuleEvaluationResult:
    block_length = int(rule.params["minimum_block_length"])
    minimum_days = int(rule.params["minimum_days"])
    grouped: dict[tuple[int, int], list[ScheduleItem]] = defaultdict(list)
    for item in rows:
        if not _target_match(rule, item) or not _time_match(rule, item):
            continue
        owner = item.class_id if by_subject else (item.teacher_id or 0)
        grouped[(owner, item.weekday)].append(item)
    owners = {key[0] for key in grouped}
    class_mode = str(rule.params.get("class_mode") or "same_class") if not by_subject else "same_class"
    satisfied_days: dict[int, int] = {}
    for owner in owners:
        days_satisfied = 0
        for (candidate, weekday), day_items in grouped.items():
            if candidate != owner:
                continue
            periods = sorted({item.period for item in day_items})
            if class_mode == "same_class":
                by_class: dict[int, set[int]] = defaultdict(set)
                for item in day_items:
                    by_class[item.class_id].add(item.period)
                ok = any(_longest_block(class_periods) >= block_length for class_periods in by_class.values())
            else:
                ok = _longest_block(set(periods)) >= block_length
                if ok:
                    for start in range(min(periods), max(periods) - block_length + 2):
                        window = [item for item in day_items if start <= item.period < start + block_length]
                        if len({item.class_id for item in window}) >= 2 and len({item.period for item in window}) == block_length:
                            break
                    else:
                        ok = False
            days_satisfied += int(ok)
        satisfied_days[owner] = days_satisfied
    if not satisfied_days:
        satisfied_days = {0: 0}
    violations = sum(days < minimum_days for days in satisfied_days.values())
    return _result(rule, violations, violations, {
        "minimum_block_length": block_length,
        "minimum_days": minimum_days,
        "satisfied_days": max(satisfied_days.values(), default=0),
        "checked_targets": len(satisfied_days),
        "class_mode": class_mode,
    }, f"达到连续 {block_length} 节要求的目标数：{len(satisfied_days) - violations}/{len(satisfied_days)}")


def _longest_block(periods: set[int]) -> int:
    longest = current = 0
    for period in sorted(periods):
        current = current + 1 if period - 1 in periods else 1
        longest = max(longest, current)
    return longest


def _teacher_gap_free(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
) -> RuleEvaluationResult:
    """Check that a teacher's lessons on a day leave no interior gaps.

    Half-period lessons (odd/even week legs) occupy the same slot in their
    respective weeks, so a day's slot set is the union across parities: a slot
    that is filled in either week counts as occupied when judging gaps.

    ``target.type=subject``：先找出任教这些学科的教师，再检查这些教师当天
    **全部** 白天课（1～7 节）是否连续，而不是只看该学科自己的格子。
    """
    if rule.target.type == "subject":
        teacher_ids = _teacher_ids_for_subject_target(rule.target.ids, rows=rows)
    elif rule.target.type == "teacher":
        teacher_ids = {int(teacher_id) for teacher_id in rule.target.ids}
    else:
        return RuleEvaluationResult(
            rule_id=rule.id,
            code=rule.code,
            title=rule.title,
            priority=rule.priority,
            status="unresolved",
            message="教师无空节规则必须作用于教师或学科",
        )
    checked_days = 0
    violations = 0
    grouped: dict[tuple[int, int], set[int]] = defaultdict(set)
    for item in rows:
        if item.teacher_id is None or int(item.teacher_id) not in teacher_ids:
            continue
        if rule.weekdays and item.weekday not in rule.weekdays:
            continue
        # 第8、9节是自习/活动，不并入白天连续块；晚课同样独立。
        if item.period >= 8:
            continue
        if (
            rule.period_scope == "regular"
            and evening_start_period is not None
            and item.period >= int(evening_start_period)
        ):
            continue
        # 按周实例分组：单周腿与双周腿各自检查连续性（0.5课时分散在不同节次不算空节）
        # 全周课同时计入单周/双周实例（与 CP 占用链成员一致）
        if item.week_parity == WeekParity.all:
            grouped[(item.teacher_id, item.weekday, "o")].add(item.period)
            grouped[(item.teacher_id, item.weekday, "e")].add(item.period)
        else:
            parity = "e" if item.week_parity == WeekParity.even else "o"
            grouped[(item.teacher_id, item.weekday, parity)].add(item.period)
    for (_teacher_id, _weekday, _parity), periods in grouped.items():
        checked_days += 1
        span = max(periods) - min(periods) + 1
        if span != len(periods):
            violations += 1
    return _result(
        rule, violations, violations,
        {"checked_teacher_days": checked_days},
        f"教师当天课程存在空节的天数：{violations}/{checked_days}",
    )


def _class_gap_free(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
) -> RuleEvaluationResult:
    """班级第 1～7 节必须都有课；第 8、9 节是自习（可空，也可排活动课）。

    周六还要求单周、双周两个实例各自 1～7 节都满。第 10 节起是晚自习，不参与。
    """
    if rule.params.get("trailing_empty") is True:
        selected = sorted(rule.periods)
        occupied: dict[tuple[str, int, int], set[int]] = defaultdict(set)
        for item in rows:
            if not (_target_match(rule, item) and _day_match(rule, item)):
                continue
            for parity in ("odd", "even"):
                if rule.week_parity not in ("all", parity) or item.week_parity not in (WeekParity.all, parity):
                    continue
                occupied[(parity, item.class_id, item.weekday)].add(item.period)
        violations = sum(any(p not in slots and any(later in slots for later in selected[i + 1:])
                             for i, p in enumerate(selected)) for slots in occupied.values())
        return _result(rule, violations, violations, {"checked_class_days": len(occupied)},
                       f"行政课中间空节：{violations}")
    evening_start = int(evening_start_period or 9)
    by_cd: dict[tuple[int, int], set[int]] = defaultdict(set)
    for item in rows:
        if rule.period_scope == "regular" and item.period >= evening_start:
            continue
        if _target_match(rule, item) and _day_match(rule, item):
            by_cd[(item.class_id, item.weekday)].add(item.period)
    odd_m: dict[tuple[int, int], set[int]] = defaultdict(set)
    even_m: dict[tuple[int, int], set[int]] = defaultdict(set)
    for item in rows:
        if rule.period_scope == "regular" and item.period >= evening_start:
            continue
        if not (_target_match(rule, item) and _day_match(rule, item)):
            continue
        key = (item.class_id, item.weekday)
        if item.week_parity != WeekParity.even:
            odd_m[key].add(item.period)
        if item.week_parity != WeekParity.odd:
            even_m[key].add(item.period)

    checked = violations = 0
    for key, periods in sorted(by_cd.items()):
        checked += 1
        core = set(range(1, 8))
        if key[1] == 6:
            ok = core <= odd_m[key] and core <= even_m[key]
        else:
            ok = core <= periods
        if not ok:
            violations += 1
    return _result(rule, violations, violations,
                   {"checked_class_days": checked},
                   f"班级课程连续性不达标的天数：{violations}/{checked}")


def _subject_daily_spread(rule: RuleDefinition, rows: list[ScheduleItem]) -> RuleEvaluationResult:
    """均匀分布：同一学科同一班级每天最多 1 节。

    数据例外：学科周课时 > 教学天数（5 天）时，允许某天 2 节
    （如某学科每周 6 节），其中连堂由 subject_consecutive 规则另行要求。
    """
    by_csd: dict[tuple[int, int, int], list[ScheduleItem]] = defaultdict(list)
    weekly_by_cs: dict[tuple[int, int], float] = defaultdict(float)
    for item in rows:
        # 晚自习（第10节起）不计入白天均匀分布；第8、9节仍是白天。
        if item.period >= 10:
            continue
        if not (_target_match(rule, item) and _time_match(rule, item)):
            continue
        key = (item.class_id, item.subject_id)
        by_csd[(*key, item.weekday)].append(item)
        weekly_by_cs[key] += 1
    checked = violations = 0
    worst = []
    for (class_id, subject_id, weekday), its in sorted(by_csd.items()):
        checked += 1
        weekly = weekly_by_cs[(class_id, subject_id)]
        allowed = 2 if weekly > 5 else 1  # 数据例外：周课时>5天允许某天2节
        cnt = len(its)
        if cnt > allowed:
            violations += 1
            worst.append(f"班{class_id} 周{weekday} {cnt}节")
    return _result(
        rule, violations, violations,
        {"checked_class_days": checked},
        f"同学科单日超量：{violations}/{checked}" + (f"（{'；'.join(worst[:3])}）" if worst else ""),
    )


def _slot_teacher_balance(rule: RuleDefinition, rows: list[ScheduleItem]) -> RuleEvaluationResult:
    """第5节等指定节次：每名教师最多承担 max_per_teacher 节（硬封顶）。

    班主任本班第5节已由 R17-01 禁排，这里统计的主要是科任（及班主任在他班）承担量。
    单双周半课各计 1；不要求人数完全均分，「轮流」只是尽量摊开。
    """
    counts: dict[int, int] = defaultdict(int)
    for item in rows:
        if item.teacher_id is None:
            continue
        if not _time_match(rule, item):
            continue
        counts[item.teacher_id] += 1
    if not counts:
        return _result(rule, 0, 0, {"checked_teachers": 0}, "作用节次暂无教师课程")
    cap = rule.params.get("max_per_teacher")
    if _positive_int(cap):
        # 封顶语义：第5节每师最多承担 N 节，超出人数即违规
        over = {t: c for t, c in counts.items() if c > int(cap)}
        violations = sum(c - int(cap) for c in over.values())
        return _result(
            rule, violations, violations,
            {"checked_teachers": len(counts), "max_per_teacher": int(cap),
             "max_lessons": max(counts.values())},
            f"第{rule.periods}节超过 {cap} 节的教师：{len(over)} 人",
        )
    spread = max(counts.values()) - min(counts.values())
    return _result(
        rule, spread, spread,
        {
            "checked_teachers": len(counts),
            "max_lessons": max(counts.values()),
            "min_lessons": min(counts.values()),
        },
        f"第{rule.periods}节承担最多 {max(counts.values())} 节、最少 {min(counts.values())} 节，落差 {spread}",
    )


def _subject_parity_pair(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
) -> RuleEvaluationResult:
    """Evening: 1:1 either-way same slot. Daytime: odd/even subject groups only (no same-slot)."""
    daytime = rule.code == "subject_daytime_parity_pair"
    evening_start = int(evening_start_period) if evening_start_period else None
    slots: dict[tuple[int, int, int], set[tuple[int, int]]] = defaultdict(set)
    for item in rows:
        if item.week_parity == WeekParity.all:
            continue
        if daytime:
            if evening_start is not None and item.period >= evening_start:
                continue
            if not _time_match(rule, item):
                continue
        parity = 0 if item.week_parity == WeekParity.odd else 1
        slots[(item.class_id, parity, item.subject_id)].add((item.weekday, item.period))

    checked = 0
    violations = 0
    class_ids = sorted({item.class_id for item in rows})

    if daytime:
        sides = _daytime_parity_sides(rule)
        if sides is None:
            return _result(rule, 0, 0, {}, "白天单双周归属未配置学科组")
        odd_ids, even_ids = sides
        for class_id in class_ids:
            has_any = False
            wrong_leg = False
            for sid in odd_ids:
                if slots.get((class_id, 0, sid)) or slots.get((class_id, 1, sid)):
                    has_any = True
                if slots.get((class_id, 1, sid)):
                    wrong_leg = True
            for sid in even_ids:
                if slots.get((class_id, 0, sid)) or slots.get((class_id, 1, sid)):
                    has_any = True
                if slots.get((class_id, 0, sid)):
                    wrong_leg = True
            if not has_any:
                continue
            checked += 1
            if wrong_leg:
                violations += 1
        return _result(
            rule, violations, violations,
            {"checked_classes": checked},
            f"单双周归属合规班级：{checked - violations}/{checked}",
        )

    subject_a, subject_b = rule.target.ids[0], rule.target.ids[1]
    for class_id in class_ids:
        a_odd = slots.get((class_id, 0, subject_a), set())
        a_even = slots.get((class_id, 1, subject_a), set())
        b_odd = slots.get((class_id, 0, subject_b), set())
        b_even = slots.get((class_id, 1, subject_b), set())
        if not (a_odd or a_even or b_odd or b_even):
            continue
        checked += 1
        ok = (a_odd == b_even and bool(a_odd)) or (a_even == b_odd and bool(a_even))
        if not ok:
            violations += 1
    return _result(
        rule, violations, violations,
        {"checked_classes": checked},
        f"单双周对课对齐班级：{checked - violations}/{checked}",
    )


def _slot_rule(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
    class_head_teacher_ids: dict[int, int | None] | None = None,
) -> RuleEvaluationResult:
    matches = [item for item in rows if _target_match(rule, item)]
    if rule.code in {"slot_allowed", "subject_allowed_slots"}:
        allowed = {(day, period) for day in rule.weekdays for period in rule.periods}
        violations = sum((item.weekday, item.period) not in allowed for item in matches)
    elif rule.code == "teacher_forbidden_slots" and _own_head_class_only(rule):
        if class_head_teacher_ids is None:
            return RuleEvaluationResult(
                rule_id=rule.id,
                code=rule.code,
                title=rule.title,
                priority=rule.priority,
                status="unresolved",
                message="缺少班级与班主任关系，无法校验本班禁排",
            )
        forbidden = _forbidden_slot_pairs(rule)
        violations = 0
        for item in matches:
            if (item.weekday, item.period) not in forbidden:
                continue
            if item.teacher_id is None:
                continue
            if class_head_teacher_ids.get(item.class_id) == item.teacher_id:
                violations += 1
    elif rule.code in {"slot_forbidden", "teacher_forbidden_slots"}:
        forbidden = _forbidden_slot_pairs(rule)
        violations = sum((item.weekday, item.period) in forbidden for item in matches)
    else:
        violations = sum(_time_match(rule, item) for item in matches)
    if rule.code == "teacher_forbidden_slots" and _positive_int_list(rule.params.get("require_weekdays")):
        evening_start = int(evening_start_period or 10)
        periods = _evening_rule_periods(rule, evening_start=evening_start)
        teacher_ids = {int(teacher_id) for teacher_id in rule.target.ids}
        classes_by_day: dict[int, set[int]] = {}
        for weekday in rule.params["require_weekdays"]:
            day = int(weekday)
            odd_ok = even_ok = False
            classes: set[int] = set()
            for item in matches:
                if item.teacher_id is None or int(item.teacher_id) not in teacher_ids:
                    continue
                if item.weekday != day or item.period not in periods:
                    continue
                if item.period < evening_start and rule.period_scope == "evening":
                    continue
                classes.add(item.class_id)
                if item.week_parity != WeekParity.even:
                    odd_ok = True
                if item.week_parity != WeekParity.odd:
                    even_ok = True
            if not odd_ok:
                violations += 1
            if not even_ok:
                violations += 1
            classes_by_day[day] = classes
        occupied_days = [day for day, classes in classes_by_day.items() if classes]
        unique_classes = {class_id for classes in classes_by_day.values() for class_id in classes}
        if occupied_days and len(unique_classes) < len(occupied_days):
            violations += 1
    return _result(rule, violations, violations, {"checked_items": len(matches)}, f"发现 {violations} 个课位违反规则")


def _class_allowed_subjects(rule: RuleDefinition, rows: list[ScheduleItem]) -> RuleEvaluationResult:
    allowed = set(rule.params.get("allowed_subject_ids") or [])
    matches = [item for item in rows if _target_match(rule, item) and _time_match(rule, item)]
    violations = sum(item.subject_id not in allowed for item in matches)
    missing_slots = 0
    if rule.params.get("require_occupied_slots"):
        occupied = {(item.weekday, item.period) for item in matches if item.subject_id in allowed}
        required = {(weekday, period) for weekday in rule.weekdays for period in rule.periods}
        missing_slots = len(required - occupied)
        violations += missing_slots
    return _result(rule, violations, violations, {"checked_items": len(matches), "missing_slots": missing_slots}, f"发现 {violations} 个不允许或未排课的学科课位")


def _teacher_evening_daytime_link(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
) -> RuleEvaluationResult:
    """On an evening-teaching day, require a specific daytime period that same day.

    Weekly quotas such as "at least 2 lessons in periods 3/4/5" belong in
    ``teacher_period_minimum`` and are intentionally not checked here.
    """
    evening_start = int(rule.params.get("evening_start_period") or evening_start_period or 9)
    required_period = int(rule.params["required_daytime_period"])
    by_teacher_day: dict[tuple[int, int], list[ScheduleItem]] = defaultdict(list)
    for item in rows:
        if _target_match(rule, item) and item.teacher_id is not None:
            by_teacher_day[(item.teacher_id, item.weekday)].append(item)
    violations = 0
    checked_days = 0
    for _, day_items in by_teacher_day.items():
        if not any(item.period >= evening_start for item in day_items):
            continue
        checked_days += 1
        daytime = [item for item in day_items if item.period < evening_start]
        if not any(item.period == required_period for item in daytime):
            violations += 1
    return _result(
        rule,
        violations,
        violations,
        {"checked_evening_days": checked_days},
        f"晚课当天缺少第{required_period}节的天数：{violations}",
    )


def _teacher_period_minimum(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
) -> RuleEvaluationResult:
    """Require a teacher to place at least N daytime lessons in a period set.

    ``weekdays`` 有值时只统计这些天（R10-c 不含周六）。
    """
    evening_start = int(rule.params.get("evening_start_period") or evening_start_period or 9)
    periods = set(int(p) for p in (rule.periods or rule.params.get("periods") or []))
    minimum = int(rule.params["minimum_lessons"])
    weekdays = {int(day) for day in rule.weekdays} if rule.weekdays else None
    by_teacher: dict[int, int] = defaultdict(int)
    for item in rows:
        if not _target_match(rule, item) or item.teacher_id is None:
            continue
        if item.period >= evening_start:
            continue
        if weekdays is not None and item.weekday not in weekdays:
            continue
        if item.period in periods:
            by_teacher[int(item.teacher_id)] += 1
    # Teachers with no matching lessons still fail if they appear in the timetable at all.
    targeted = {int(tid) for tid in rule.target.ids}
    present = {
        int(item.teacher_id)
        for item in rows
        if item.teacher_id is not None and int(item.teacher_id) in targeted
    }
    violations = 0
    for teacher_id in sorted(present):
        count = by_teacher.get(teacher_id, 0)
        if count < minimum:
            violations += 1
    period_label = "、".join(str(p) for p in sorted(periods))
    return _result(
        rule,
        violations,
        violations,
        {
            "minimum_lessons": minimum,
            "period_count": len(periods),
            "checked_teachers": len(present),
        },
        f"白天第{period_label}节合计不足{minimum}节的教师数：{violations}",
    )


def _class_slot_pattern(rule: RuleDefinition, rows: list[ScheduleItem]) -> RuleEvaluationResult:
    """Check one of several exact slot combinations for every matching class.

    The rule target is normally a subject (for example 体育或实验课). Each class must
    match one complete alternative. This models "周二上午+周四下午" OR
    "周二下午+周四上午" without relying on a natural-language summary.
    """
    alternatives = rule.params["alternatives"]
    matches_by_class: dict[int, list[ScheduleItem]] = defaultdict(list)
    for item in rows:
        if _target_match(rule, item) and _time_match(rule, item):
            matches_by_class[item.class_id].append(item)

    if not matches_by_class:
        return _result(
            rule, 1, 1, {"checked_classes": 0, "matched_alternative": 0},
            "没有找到需要校验的目标班级课位",
        )

    failures = 0
    matched_alternatives: set[int] = set()
    for class_items in matches_by_class.values():
        matched = 0
        for index, alternative in enumerate(alternatives, start=1):
            expected = sum(int(group["count"]) for group in alternative)
            if len(class_items) != expected:
                continue
            if all(
                sum(
                    item.weekday in group["weekdays"]
                    and item.period in group["periods"]
                    for item in class_items
                ) == int(group["count"])
                for group in alternative
            ):
                matched = index
                break
        if matched:
            matched_alternatives.add(matched)
        else:
            failures += 1

    return _result(
        rule,
        failures,
        failures,
        {
            "checked_classes": len(matches_by_class),
            "matched_classes": len(matches_by_class) - failures,
            "matched_alternative": next(iter(matched_alternatives), 0) if len(matched_alternatives) == 1 else "multiple",
        },
        f"符合课位组合的班级：{len(matches_by_class) - failures}/{len(matches_by_class)}",
    )


def _class_evening_self_study_day(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    early_subject_ids: set[int] | None = None,
    gap_fill_subject_ids: set[int] | None = None,
) -> RuleEvaluationResult:
    """候选日中恰好 N 天第8、9节是自习（空堂或音美心）；与晚自习无关。"""
    study_periods = [period for period in (rule.periods or [8, 9]) if period in {8, 9}] or [8, 9]
    choose_count = int(rule.params["choose_count"])
    early_ids = set(early_subject_ids or ())
    fill_ids = set(gap_fill_subject_ids or ())
    failures = 0
    checked_classes = 0
    self_study_days = 0
    for class_id in rule.target.ids:
        checked_classes += 1
        class_self_study_days = 0
        for weekday in rule.weekdays:
            if _daytime_study_day(
                rows,
                class_id=class_id,
                weekday=weekday,
                study_periods=study_periods,
                early_ids=early_ids,
                fill_ids=fill_ids,
            ):
                class_self_study_days += 1
        self_study_days += class_self_study_days
        if class_self_study_days < choose_count:
            failures += 1
    return _result(
        rule,
        failures,
        failures,
        {
            "checked_classes": checked_classes,
            "choose_count": choose_count,
            "self_study_days": self_study_days,
            "study_periods": ",".join(str(period) for period in study_periods),
        },
        f"第8、9节自习日不少于{choose_count}天的班级：{checked_classes - failures}/{checked_classes}",
    )


def _daytime_study_day(
    rows: list[ScheduleItem],
    *,
    class_id: int,
    weekday: int,
    study_periods: list[int],
    early_ids: set[int],
    fill_ids: set[int],
) -> bool:
    for item in rows:
        if item.class_id != class_id or item.weekday != weekday or item.period not in study_periods:
            continue
        if fill_ids and item.subject_id in fill_ids:
            continue
        if early_ids:
            if item.subject_id in early_ids:
                return False
            continue
        if item.teacher_id is not None:
            return False
    return True


def _slot_teacher_role_required(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    class_head_teacher_ids: dict[int, int | None] | None,
) -> RuleEvaluationResult:
    """Require each scheduled class to have its head teacher at exact slots."""
    if class_head_teacher_ids is None:
        return RuleEvaluationResult(
            rule_id=rule.id,
            code=rule.code,
            title=rule.title,
            priority=rule.priority,
            status="unresolved",
            message="缺少班级与班主任关系，无法校验指定课位",
        )
    class_ids = sorted({item.class_id for item in rows})
    missing_head_teachers = [class_id for class_id in class_ids if not class_head_teacher_ids.get(class_id)]
    if missing_head_teachers:
        return RuleEvaluationResult(
            rule_id=rule.id,
            code=rule.code,
            title=rule.title,
            priority=rule.priority,
            status="unresolved",
            metrics={"missing_head_teacher_classes": len(missing_head_teachers)},
            message=f"有 {len(missing_head_teachers)} 个班级未配置班主任",
        )

    positions = _slot_positions(rule)
    violations = 0
    checked_slots = 0
    for class_id in class_ids:
        expected_teacher_id = class_head_teacher_ids[class_id]
        for weekday, period in positions:
            checked_slots += 1
            matches = [
                item for item in rows
                if item.class_id == class_id
                and item.weekday == weekday
                and item.period == period
            ]
            if not matches or not any(item.teacher_id == expected_teacher_id for item in matches):
                violations += 1
    return _result(
        rule,
        violations,
        violations,
        {"checked_class_slots": checked_slots},
        f"班主任满足指定课位：{checked_slots - violations}/{checked_slots}",
    )


def generation_teacher_preferred_evening_weekdays(group: RuleGroupDocument) -> dict[int, set[int]]:
    """Evening preferred weekdays for placement bias (hard or soft).

    Used only as a soft ordering hint when building/repairing evenings; fill
    quotas take priority over staying inside these days.

    带 ``params.class_id`` 的班别钉位（R19）不进入全局偏好日：钉位由
    ``generation_class_slot_required_teachers`` 硬保留，避免把「10班周一」
    误扩成「该教师所有晚课只能周一」。
    """
    compiled_by_id = {item.rule_id: item for item in compile_rule_group(group)}
    result: dict[int, set[int]] = {}
    for rule in group.rules:
        compiled = compiled_by_id.get(rule.id)
        if compiled is None:
            continue
        if (
            not rule.enabled
            or rule.code != "teacher_preferred_weekdays"
            or rule.priority not in ("hard", "soft")
            or compiled.status != "ready"
            or rule.target.type != "teacher"
            or rule.period_scope != "evening"
            or not rule.weekdays
            or _positive_int(rule.params.get("class_id"))
        ):
            continue
        preferred = {int(day) for day in rule.weekdays}
        for teacher_id in rule.target.ids:
            tid = int(teacher_id)
            if tid in result:
                result[tid] |= preferred
            else:
                result[tid] = set(preferred)
    return result


def _teacher_preferred_weekdays(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
) -> RuleEvaluationResult:
    preferred = set(rule.weekdays)
    evening_start = int(rule.params.get("evening_start_period") or evening_start_period or 9)
    class_id = rule.params.get("class_id")
    # 指定班级钉位（如 R19：张卓10班周一晚）：只检查该班该课位是否由目标教师上课，
    # 不把教师其它班的晚课算进「未落在偏好星期」。
    if _positive_int(class_id) and preferred and rule.target.type == "teacher":
        cid = int(class_id)
        teacher_ids = {int(teacher_id) for teacher_id in rule.target.ids}
        periods = (
            _evening_rule_periods(rule, evening_start=evening_start)
            if rule.period_scope == "evening"
            else list(rule.periods or [evening_start])
        )
        checked = violations = 0
        for weekday in sorted(preferred):
            for period in periods:
                if rule.period_scope == "evening" and int(period) < evening_start:
                    continue
                checked += 1
                here = [
                    item for item in rows
                    if item.class_id == cid
                    and item.weekday == int(weekday)
                    and item.period == int(period)
                ]
                if not any(item.teacher_id is not None and int(item.teacher_id) in teacher_ids for item in here):
                    violations += 1
        return _result(
            rule,
            violations,
            violations,
            {"checked_class_slots": checked, "class_id": cid},
            f"指定班课位满足：{checked - violations}/{checked}",
        )
    matches = []
    for item in rows:
        if not _target_match(rule, item):
            continue
        if rule.period_scope == "evening" and item.period < evening_start:
            continue
        if rule.period_scope == "regular" and evening_start_period is not None and item.period >= evening_start:
            continue
        matches.append(item)
    outside = sum(item.weekday not in preferred for item in matches)
    return _result(
        rule,
        outside,
        outside,
        {"checked_items": len(matches), "preferred_days": len(preferred)},
        f"有 {outside} 节课未落在偏好星期",
    )


def _subject_prefer_early_periods(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
) -> RuleEvaluationResult:
    evening_start = int(evening_start_period or 9)
    matches = [
        item for item in rows
        if _target_match(rule, item) and item.period < evening_start
    ]
    preferred = {int(period) for period in (rule.periods or []) if int(period) >= 1}
    try:
        max_outside = max(0, int(rule.params.get("max_outside")))
    except (TypeError, ValueError):
        max_outside = 0
    if preferred:
        by_class_subject: dict[tuple[int, int], int] = defaultdict(int)
        for item in matches:
            if item.period not in preferred:
                by_class_subject[(item.class_id, item.subject_id)] += 1
        extra = sum(max(0, count - max_outside) for count in by_class_subject.values())
        return _result(
            rule,
            extra,
            extra,
            {
                "checked_items": len(matches),
                "max_outside": max_outside,
                "preferred_periods": ",".join(str(p) for p in sorted(preferred)),
            },
            f"超出允许的「不在所选节次」：{extra} 节（每班每科最多 {max_outside} 节）",
        )
    late = sum(1 for item in matches if item.period >= 8)
    penalty = sum(item.period for item in matches)
    return _result(
        rule,
        late,
        penalty,
        {"checked_items": len(matches), "period_sum": penalty},
        f"主科排进第8、9节：{late} 节",
    )


def _subject_gap_fill_late_periods(
    rule: RuleDefinition,
    rows: list[ScheduleItem],
    *,
    evening_start_period: int | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
) -> RuleEvaluationResult:
    evening_start = int(evening_start_period or 9)
    late_from = int(rule.params.get("late_from_period") or 8)
    matches = [
        item for item in rows
        if _target_match(rule, item) and item.period < evening_start
    ]
    occupied: dict[tuple[int, int], set[int]] = defaultdict(set)
    for item in rows:
        if item.period < evening_start:
            occupied[(item.class_id, item.weekday)].add(item.period)
    allowed_map = class_slot_allowed_subjects or {}
    early = 0
    for item in matches:
        if item.period >= late_from:
            continue
        taken = occupied.get((item.class_id, item.weekday), set())
        # 第8、9节还有「该活动课能排进去」的空位时，抢前面才算违规。
        # 硬规则禁排的空课位（如 10 班周一第8、9节不排课）不算可补位。
        late_slots = list(range(late_from, evening_start))
        if any(
            period not in taken
            and _slot_allows_subject(allowed_map, item.class_id, item.weekday, period, item.subject_id)
            for period in late_slots
        ):
            early += 1
    return _result(
        rule,
        early,
        early,
        {"checked_items": len(matches), "late_from_period": late_from},
        f"有 {early} 节活动课排进第{late_from}节之前，且当天第{late_from}节及以后仍有空位",
    )


def _result(
    rule: RuleDefinition,
    violations: int,
    penalty: int,
    metrics: dict[str, int | float | str],
    message: str,
) -> RuleEvaluationResult:
    return RuleEvaluationResult(
        rule_id=rule.id, code=rule.code, title=rule.title, priority=rule.priority,
        status="fail" if violations else "pass", violation_count=violations,
        penalty=penalty if rule.priority == "soft" else 0, metrics=metrics, message=message,
    )
