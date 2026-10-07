"""排课生成失败诊断：给出原因说明与可操作的修改建议。

CP-SAT 证明 INFEASIBLE 时通常无法指出「哪一条规则」是唯一祸首，
因此这里基于**当前启用的硬约束**做可读性诊断，并按松紧度排序建议
（禁用 / 降为软规则 / 放宽参数）。产品页直接展示，不必依赖脚本或人工推理。
"""
from __future__ import annotations

from typing import Any, Literal

from app.services.scheduling.rules import RuleDefinition, RuleGroupDocument


Action = Literal["demote_to_soft", "disable", "relax_param", "check_hours"]

PIPELINE: list[dict[str, str]] = [
    {"id": "validating", "label": "校验任教与课时"},
    {"id": "daytime_search", "label": "白天课求解"},
    {"id": "evening_search", "label": "晚自习求解"},
    {"id": "hard_rule_postcheck", "label": "硬规则验算"},
    {"id": "refreshing", "label": "写入课表"},
]


def _rule_label(rule: RuleDefinition) -> str:
    return rule.title or rule.id


def _active_hard_rules(group: RuleGroupDocument | None) -> list[RuleDefinition]:
    if group is None:
        return []
    return [
        rule
        for rule in group.rules
        if rule.enabled and rule.priority == "hard" and rule.code != "manual_review"
    ]


def _stuck_for(
    failure_kind: str, last_error: str | None
) -> tuple[str, str]:
    if failure_kind == "capacity":
        return "validating", "卡在资源校验：课时或师资容量不够。"
    if failure_kind == "cpsat_infeasible":
        return "daytime_search", "卡在白天课求解：当前硬约束互相矛盾，模型无解。"
    if failure_kind == "evening_infeasible":
        return "evening_search", "卡在晚自习：白天可排，晚课硬约束无解或超时。"
    if failure_kind == "hard_rule_postcheck":
        return "hard_rule_postcheck", "卡在保存前验算：结果违反硬规则，未写入。"
    if failure_kind == "seed_exhausted":
        if last_error and "晚" in last_error:
            return "evening_search", "卡在多轮求解：晚自习反复失败。"
        return "daytime_search", "卡在多轮求解：换种子仍无法排出可行课表。"
    return "daytime_search", "生成中断，请查看下方过程日志。"


def diagnose_generation_failure(
    *,
    failure_kind: Literal[
        "cpsat_infeasible",
        "seed_exhausted",
        "hard_rule_postcheck",
        "capacity",
        "evening_infeasible",
    ],
    message: str,
    rule_group: RuleGroupDocument | None = None,
    solver_status: str | None = None,
    last_error: str | None = None,
    seed_attempts: int | None = None,
    hard_rule_failures: list[Any] | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable diagnosis payload for API / SSE ``detail``."""
    hard_rules = _active_hard_rules(rule_group)
    reasons = _build_reasons(
        failure_kind=failure_kind,
        message=message,
        hard_rules=hard_rules,
        solver_status=solver_status,
        last_error=last_error,
        seed_attempts=seed_attempts,
        hard_rule_failures=hard_rule_failures,
    )
    suggestions = _build_suggestions(
        failure_kind=failure_kind,
        hard_rules=hard_rules,
        hard_rule_failures=hard_rule_failures,
    )
    stuck_step, stuck_label = _stuck_for(failure_kind, last_error)
    return {
        "summary": message,
        "failure_kind": failure_kind,
        "solver": solver_status,
        "rule_group_id": rule_group.id if rule_group else None,
        "pipeline": PIPELINE,
        "stuck_step": stuck_step,
        "stuck_label": stuck_label,
        "reasons": reasons,
        "suggestions": suggestions,
        "hard_rules_in_effect": [
            {
                "rule_id": rule.id,
                "code": rule.code,
                "title": _rule_label(rule),
                "weekdays": list(rule.weekdays),
                "periods": list(rule.periods),
            }
            for rule in hard_rules
        ],
    }


def apply_suggestion_to_group(
    group: RuleGroupDocument, suggestion: dict[str, Any]
) -> tuple[RuleGroupDocument, str]:
    """Apply one diagnosis suggestion to a rule group. Returns (group, note)."""
    action = str(suggestion.get("action") or "")
    rule_id = str(suggestion.get("rule_id") or "")
    if action == "check_hours":
        raise ValueError("该建议需要人工核对课时，无法自动应用")
    if action not in {"demote_to_soft", "disable", "relax_param"}:
        raise ValueError(f"不支持的操作：{action or '空'}")
    if not rule_id:
        raise ValueError("缺少规则编号")

    found = False
    next_rules: list[RuleDefinition] = []
    note = ""
    for rule in group.rules:
        if rule.id != rule_id:
            next_rules.append(rule)
            continue
        found = True
        if action == "demote_to_soft":
            next_rules.append(rule.model_copy(update={"priority": "soft"}))
            note = f"{rule.id}（{_rule_label(rule)}）已降为软目标"
        elif action == "disable":
            next_rules.append(rule.model_copy(update={"enabled": False}))
            note = f"{rule.id}（{_rule_label(rule)}）已停用"
        else:
            patch = suggestion.get("param_patch") or _relax_patch(rule)
            if not isinstance(patch, dict) or not patch:
                raise ValueError(f"{rule.id} 无法自动放宽参数")
            next_rules.append(
                rule.model_copy(update={"params": {**dict(rule.params), **patch}})
            )
            note = f"{rule.id}（{_rule_label(rule)}）已放宽参数 {patch}"
    if not found:
        raise ValueError(f"规则组中未找到 {rule_id}")
    return group.model_copy(update={"rules": next_rules}), note


def _relax_patch(rule: RuleDefinition) -> dict[str, Any] | None:
    if rule.code == "slot_teacher_balance":
        try:
            cap = int(rule.params.get("max_per_teacher") or 2)
        except (TypeError, ValueError):
            cap = 2
        return {"max_per_teacher": max(1, cap + 1)}
    if rule.code == "teacher_daily_limit":
        try:
            cap = int(rule.params.get("max_lessons_per_day") or 5)
        except (TypeError, ValueError):
            cap = 5
        return {"max_lessons_per_day": max(1, cap + 1)}
    return None


def _build_reasons(
    *,
    failure_kind: str,
    message: str,
    hard_rules: list[RuleDefinition],
    solver_status: str | None,
    last_error: str | None,
    seed_attempts: int | None,
    hard_rule_failures: list[Any] | None,
) -> list[str]:
    reasons: list[str] = []
    if failure_kind == "cpsat_infeasible":
        reasons.append(
            "白天课求解器已证明：在当前课时、任教关系和全部硬约束下不存在可行课表"
            + (f"（状态 {solver_status}）" if solver_status else "。")
        )
        reasons.append(
            "换随机种子无法突破「数学无解」；需要放宽硬约束、调整课时，或减少互相打架的禁排。"
        )
    elif failure_kind == "evening_infeasible":
        reasons.append("白天课可解，但晚自习在当前硬约束下无解或多次超时。")
        if last_error:
            reasons.append(f"最后一次失败：{last_error}")
    elif failure_kind == "seed_exhausted":
        reasons.append(
            f"已尝试 {seed_attempts or '多'} 组随机种子，白天课与晚自习仍无法同时排出。"
        )
        if last_error:
            reasons.append(f"最后一次失败：{last_error}")
        reasons.append(
            "若多次都是超时而非「无解」，可再试一轮；若反复无解，需要放宽硬约束。"
        )
    elif failure_kind == "hard_rule_postcheck":
        reasons.append("求解器排出了一版课表，但保存前硬规则校验未通过，课表未写入。")
        for item in hard_rule_failures or []:
            rid = getattr(item, "rule_id", None) or (item.get("rule_id") if isinstance(item, dict) else "?")
            title = getattr(item, "title", None) or (item.get("title") if isinstance(item, dict) else "")
            msg = getattr(item, "message", None) or (item.get("message") if isinstance(item, dict) else "")
            reasons.append(f"{rid} {_rule_label_from(title, rid)}：{msg}")
    elif failure_kind == "capacity":
        reasons.append(message or "课时容量或师资条件不足，排课条件无解。")
    else:
        reasons.append(message)

    # 点名几类特别「紧」的硬约束，帮助教务快速定位
    tight = [r for r in hard_rules if r.code in _TIGHT_CODES]
    if tight and failure_kind in {"cpsat_infeasible", "seed_exhausted", "evening_infeasible"}:
        names = "、".join(f"{r.id}（{_rule_label(r)}）" for r in tight[:6])
        more = f" 等 {len(tight)} 条" if len(tight) > 6 else ""
        reasons.append(f"当前启用的高影响硬约束包括：{names}{more}。")

    combo = _detect_known_conflicts(hard_rules)
    reasons.extend(combo)
    return reasons


def _rule_label_from(title: str, rid: str) -> str:
    return title or rid


_TIGHT_CODES = frozenset(
    {
        "class_allowed_subjects",
        "class_gap_free",
        "teacher_gap_free",
        "teacher_forbidden_slots",
        "teacher_daily_limit",
        "slot_teacher_balance",
        "subject_consecutive",
        "class_slot_pattern",
        "teacher_period_minimum",
        "teacher_evening_daytime_link",
        "teacher_multi_class_evening_adjacent",
        "subject_evening_parity_pair",
        "subject_daytime_parity_pair",
        "slot_teacher_role_required",
    }
)


def _detect_known_conflicts(hard_rules: list[RuleDefinition]) -> list[str]:
    """Heuristic patterns seen in production (e.g. 全年级 8/9 仅活动课 + 音乐老师禁周三 8/9)."""
    tips: list[str] = []
    by_code: dict[str, list[RuleDefinition]] = {}
    for rule in hard_rules:
        by_code.setdefault(rule.code, []).append(rule)

    allow_lists = by_code.get("class_allowed_subjects") or []
    broad_89 = [
        rule
        for rule in allow_lists
        if set(rule.periods) >= {8, 9}
        and len(rule.target.ids) >= 8
        and not bool(rule.params.get("forbid_all"))
    ]
    teacher_forbids = by_code.get("teacher_forbidden_slots") or []
    forbid_89 = [
        rule
        for rule in teacher_forbids
        if set(rule.periods) & {8, 9} and set(rule.weekdays)
    ]
    if broad_89 and forbid_89:
        tips.append(
            "检测到「多班第8/9节仅允许活动课」与「教师禁排第8/9节」同时启用："
            "活动课教师若也被禁部分 8/9 课位，容易把模型锁死。"
            f"相关规则：{', '.join(r.id for r in broad_89[:2] + forbid_89[:2])}。"
        )

    gap = by_code.get("class_gap_free") or []
    balance = by_code.get("slot_teacher_balance") or []
    if gap and balance:
        caps = []
        for rule in balance:
            cap = rule.params.get("max_per_teacher")
            if cap is not None:
                caps.append(f"{rule.id}≤{cap}")
        if caps:
            tips.append(
                "班级 1～7 节无空堂与节次教师封顶同时收紧时，主科只能挤在有限课位里，"
                f"封顶过低更容易无解（{', '.join(caps[:3])}）。"
            )
    return tips


def _build_suggestions(
    *,
    failure_kind: str,
    hard_rules: list[RuleDefinition],
    hard_rule_failures: list[Any] | None,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []

    if failure_kind == "hard_rule_postcheck" and hard_rule_failures:
        for item in hard_rule_failures:
            rid = getattr(item, "rule_id", None) or (
                item.get("rule_id") if isinstance(item, dict) else None
            )
            title = getattr(item, "title", None) or (
                item.get("title") if isinstance(item, dict) else ""
            )
            msg = getattr(item, "message", None) or (
                item.get("message") if isinstance(item, dict) else ""
            )
            code = getattr(item, "code", None) or (
                item.get("code") if isinstance(item, dict) else ""
            )
            if not rid:
                continue
            suggestions.append(
                {
                    "rule_id": rid,
                    "code": code or "",
                    "title": title or rid,
                    "action": "demote_to_soft",
                    "action_label": "降为软目标",
                    "reason": f"保存前校验未通过：{msg}",
                    "impact": "降为软目标后不再阻塞保存；课表仍可能违反该偏好，需人工抽查。",
                    "priority": 1,
                    "applicable": True,
                    "param_patch": None,
                }
            )

    scored: list[tuple[int, RuleDefinition, str, str, Action]] = []
    for rule in hard_rules:
        score, action, reason, impact = _score_rule(rule, failure_kind)
        if score is None:
            continue
        scored.append((score, rule, reason, impact, action))
    scored.sort(key=lambda item: (item[0], item[1].id))

    seen = {item["rule_id"] for item in suggestions}
    for score, rule, reason, impact, action in scored:
        if rule.id in seen:
            continue
        seen.add(rule.id)
        patch = _relax_patch(rule) if action == "relax_param" else None
        suggestions.append(
            {
                "rule_id": rule.id,
                "code": rule.code,
                "title": _rule_label(rule),
                "action": action,
                "action_label": {
                    "demote_to_soft": "降为软目标",
                    "disable": "停用规则",
                    "relax_param": "放宽参数",
                    "check_hours": "检查课时/任教",
                }.get(action, action),
                "reason": reason,
                "impact": impact,
                "priority": score,
                "applicable": action in {"demote_to_soft", "disable", "relax_param"},
                "param_patch": patch,
            }
        )
        if len(suggestions) >= 8:
            break

    if failure_kind in {"cpsat_infeasible", "seed_exhausted"} and not any(
        s["action"] == "check_hours" for s in suggestions
    ):
        suggestions.append(
            {
                "rule_id": "",
                "code": "",
                "title": "核对课时与任教",
                "action": "check_hours",
                "action_label": "去课时/任教检查",
                "reason": "请在课位结构中配置各教学日的可用节次，并在课时管理中配置班级课时。若课时占满已配置的可用课位，再叠加禁排或仅允许科目等硬限制，可能无法排出课表。",
                "impact": "先确认课时方案、任教是否与规则匹配，再改规则。",
                "priority": 50,
                "applicable": False,
                "param_patch": None,
            }
        )
    return suggestions


def _score_rule(
    rule: RuleDefinition, failure_kind: str
) -> tuple[int | None, Action, str, str]:
    """Lower score = higher priority suggestion."""
    code = rule.code
    periods = set(rule.periods)
    weekdays = set(rule.weekdays)

    if code == "class_allowed_subjects":
        forbid_all = bool(rule.params.get("forbid_all"))
        n_classes = len(rule.target.ids)
        if forbid_all:
            return (
                5,
                "demote_to_soft",
                f"禁止占用指定课位（{sorted(weekdays)} 的第 {sorted(periods)} 节），覆盖 {n_classes} 个班。",
                "降为软目标或缩小班级/星期范围，可立刻腾出课位。",
            )
        return (
            12,
            "demote_to_soft",
            f"课位仅允许指定科目（{n_classes} 班 · 第 {sorted(periods) or '未写节次'} 节）。",
            "放宽允许科目或改为软目标。",
        )

    if code == "teacher_forbidden_slots":
        n_slots = max(1, len(weekdays) * max(1, len(periods)))
        if periods & {8, 9}:
            return (
                4,
                "demote_to_soft",
                f"教师禁排触及第8/9节（约 {n_slots} 个课位量级），若同时又要求 8/9 只排活动课，会挤爆活动课教师。",
                "可改为只禁晚自习，或临时停用/降软。",
            )
        if len(periods) >= 3 or len(weekdays) >= 4:
            return (
                8,
                "demote_to_soft",
                f"教师大范围禁排（星期 {sorted(weekdays) or '多日'} · 节次 {sorted(periods) or '多节'}）。",
                "缩小禁排范围，或降为软目标。",
            )
        return (
            18,
            "demote_to_soft",
            "教师禁排硬约束占用可用课位。",
            "确认是否必须硬禁止；否则降软。",
        )

    if code == "slot_teacher_balance":
        cap = rule.params.get("max_per_teacher")
        return (
            6 if _positive_small(cap, 2) else 14,
            "relax_param",
            f"节次教师封顶 max_per_teacher={cap}（作用节次 {sorted(periods) or '默认'}）。",
            "可先把上限调高 1～2 节，或暂降为软目标。",
        )

    if code == "teacher_daily_limit":
        cap = rule.params.get("max_lessons_per_day")
        return (
            10,
            "relax_param",
            f"教师每日课节上限 {cap}。",
            "适当提高上限，或对部分教师单独放宽。",
        )

    if code in {"class_gap_free", "teacher_gap_free"}:
        return (
            15,
            "demote_to_soft",
            "无空节/连续授课硬约束会强制铺满白天课位。",
            "若与禁排冲突，可暂降软，生成后再人工补洞。",
        )

    if code == "subject_consecutive":
        return (
            16,
            "demote_to_soft",
            "连堂硬要求会占用成块课位，压缩其它科机动空间。",
            "可先降软或减少每周最少连堂天数。",
        )

    if code in {
        "teacher_evening_daytime_link",
        "teacher_multi_class_evening_adjacent",
        "subject_evening_parity_pair",
        "slot_teacher_role_required",
    }:
        if failure_kind in {"evening_infeasible", "seed_exhausted"}:
            return (
                7,
                "demote_to_soft",
                "晚自习相关硬约束（联动/相邻/对课/班主任钉位）可能阻止晚课落位。",
                "可临时降软后重试晚课，再人工微调。",
            )
        return (
            20,
            "demote_to_soft",
            "晚自习相关硬约束。",
            "若失败发生在晚课阶段，优先放宽此类规则。",
        )

    if code in _TIGHT_CODES:
        return (
            25,
            "demote_to_soft",
            f"硬约束 {code} 仍在收紧搜索空间。",
            "可尝试降为软目标后重试。",
        )
    return (None, "demote_to_soft", "", "")


def _positive_small(value: Any, threshold: int) -> bool:
    try:
        return 0 < int(value) <= threshold
    except (TypeError, ValueError):
        return False
