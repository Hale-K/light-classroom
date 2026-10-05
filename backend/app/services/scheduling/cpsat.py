"""CP-SAT 全局最优排课求解器（阶段1：工作日白天 + 阶段2：周六白天）。

把 generate_schedule 的贪心+局部修复替换为约束规划整体建模：
- 每条任教关系的课时拆分（白天/周六）作为精确放置约束
- 备课禁排/教师禁排/允许课位/班级限科/日上限/周上限/同科日上限全部为硬约束
- 课位组合（OR-of-AND）与连堂（连续窗口）用重化布尔表达
- 求解结果要么全局可行，要么给出 INFEASIBLE 证明（回答"是否有解"）

0.5 课时（单双周）建模为单腿放置：ho/he 变量恰好二选一；
同班同课位允许"全周课+单腿"或"单周腿+双周腿"共存，与库表唯一约束一致。

阶段3（晚自习）见 scheduling_evening_cpsat.generate_evening_schedule。
"""

from __future__ import annotations

import os
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from ortools.sat.python import cp_model

from app.models.enums import WeekParity
from app.services.scheduling.core import (
    ScheduleItem,
    _assignment_placement_groups,
    _normalize_slot_patterns,
    generate_schedule,
)
from app.services.scheduling.solver_watchdog import solve_with_stop_deadline


@dataclass
class CpSatSolveResult:
    items: list[ScheduleItem] = field(default_factory=list)
    status: str = "UNKNOWN"
    solve_seconds: float = 0.0
    unplaced: list[dict[str, Any]] = field(default_factory=list)


def solve_daytime_cpsat(
    assignments: Iterable[dict[str, Any]],
    *,
    days: int,
    periods_per_day: int,
    forbidden_slots: set[tuple[int, int]] | None = None,
    max_class_lessons_per_day: int | None = None,
    max_teacher_lessons_per_day: int | None = None,
    max_class_lessons_on_saturday: int | None = None,
    max_teacher_lessons_on_saturday: int | None = None,
    max_same_subject_per_day: int | None = None,
    max_teacher_weekly_periods: int | None = None,
    teacher_daily_limits: dict[int, int] | None = None,
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    teacher_class_forbidden_slots: Mapping[tuple[int, int], set[tuple[int, int]]] | None = None,
    subject_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    class_required_subject_slots: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    daytime_parity_pairs: Iterable[Mapping[str, Any]] | None = None,
    class_gap_free: bool = False,
    class_gap_free_weekdays: Iterable[int] | None = None,
    subject_daily_spread: bool = False,
    gap_free_groups: list[dict[str, Any]] | None = None,
    slot_teacher_cap: Mapping[str, Any] | None = None,
    slot_patterns: Iterable[Mapping[str, Any]] | None = None,
    consecutive_requirements: Mapping[str, Any] | None = None,
    teacher_period_minima: Iterable[Mapping[str, Any]] | None = None,
    max_time_seconds: float = 60.0,
    early_subject_ids: set[int] | None = None,
    early_subject_prefs: Iterable[Mapping[str, Any]] | None = None,
    gap_fill_subject_ids: set[int] | None = None,
    gap_fill_late_from_period: int = 8,
    num_search_workers: int = 1,
    random_seed: int = 42,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    polish_seconds: float = 150.0,
) -> CpSatSolveResult:
    """CP-SAT 求解白天+周六课表。返回 OPTIMAL/FEASIBLE/INFEASIBLE 与课表项。"""
    started = time.perf_counter()
    assignments = list(assignments)
    forbidden = forbidden_slots or set()
    t_forbidden = teacher_forbidden_slots or {}
    tc_forbidden = teacher_class_forbidden_slots or {}
    s_forbidden = subject_forbidden_slots or {}
    class_allowed = class_slot_allowed_subjects or {}
    class_required = class_required_subject_slots or {}
    patterns = _normalize_slot_patterns(slot_patterns)
    cons = consecutive_requirements or {"subjects": [], "teachers": []}

    model = cp_model.CpModel()
    y: dict[tuple[int, int, int], Any] = {}          # (a_index, weekday, period) -> BoolVar 全周课
    ho: dict[tuple[int, int, int], Any] = {}          # 半课 单周腿
    he: dict[tuple[int, int, int], Any] = {}          # 半课 双周腿
    meta: dict[int, dict[str, Any]] = {}              # a_index -> assignment 元数据

    def slot_allowed(a_idx: int, a: Mapping[str, Any], weekday: int, period: int) -> bool:
        if (weekday, period) in forbidden:
            return False
        teacher_id = a.get("teacher_id")
        class_id = int(a["class_id"])
        if teacher_id is not None:
            tid = int(teacher_id)
            if (weekday, period) in t_forbidden.get(tid, set()):
                return False
            if (weekday, period) in tc_forbidden.get((tid, class_id), set()):
                return False
        if (weekday, period) in s_forbidden.get(int(a["subject_id"]), set()):
            return False
        allowed = class_allowed.get(class_id, {}).get((weekday, period))
        if allowed is not None and int(a["subject_id"]) not in allowed:
            return False
        return True

    # ---------- 变量与放置计数 ----------
    class_by_slot: dict[tuple[int, int, int], list[int]] = {}   # (class, d, p) -> a_idx
    class_slot_occ: dict[tuple[int, int, int], list[Any]] = defaultdict(list)
    teacher_by_slot: dict[tuple[int, int, int], list[int]] = {}  # (teacher, d, p) -> a_idx

    for a_idx, a in enumerate(assignments):
        meta[a_idx] = {
            "assignment": a,
            "class_id": int(a["class_id"]),
            "subject_id": int(a["subject_id"]),
            "teacher_id": int(a["teacher_id"]) if a.get("teacher_id") is not None else None,
        }
        for allowed_weekdays, group_weekly in _assignment_placement_groups(a, days=days):
            int_part = int(group_weekly)
            frac = float(group_weekly) - int_part
            half = frac >= 0.49
            count_target = int_part if int_part > 0 else 0
            if not half and count_target == 0:
                continue
            # 半节课组可能带空 weekdays 元组（由 _place_half_week_lessons 处理的隔周课），
            # CP 模型中允许其落位到全周任意课位。
            group_days = allowed_weekdays or range(1, days + 1)
            slots = [
                (d, p)
                for d in group_days
                for p in range(1, periods_per_day + 1)
                if slot_allowed(a_idx, a, d, p)
            ]
            for (d, p) in slots:
                if count_target > 0:
                    y[(a_idx, d, p)] = model.NewBoolVar(f"y_{a_idx}_{d}_{p}")
                    class_by_slot.setdefault((meta[a_idx]["class_id"], d, p), []).append(a_idx)
                    class_slot_occ[(meta[a_idx]["class_id"], d, p)].append(y[(a_idx, d, p)])
                    if meta[a_idx]["teacher_id"] is not None:
                        teacher_by_slot.setdefault((meta[a_idx]["teacher_id"], d, p), []).append(a_idx)
            if count_target > 0:
                if count_target > len(slots):
                    print(f"[CPSAT-诊断] a={a_idx} 班{meta[a_idx]['class_id']} 科{meta[a_idx]['subject_id']} "
                          f"师{meta[a_idx]['teacher_id']} 需{count_target} > 可放{len(slots)} "
                          f"组{allowed_weekdays} half={half}")
                model.Add(sum(y[(a_idx, d, p)] for (d, p) in slots) == count_target)
            if half:
                # 课时方案钉了单周/双周时只建对应腿；无规定(all)则单双任选。
                raw_parity = str(a.get("week_parity") or WeekParity.all.value)
                allow_odd = raw_parity in {WeekParity.all.value, WeekParity.odd.value, "all", "odd"}
                allow_even = raw_parity in {WeekParity.all.value, WeekParity.even.value, "all", "even"}
                for (d, p) in slots:
                    if allow_odd:
                        ho[(a_idx, d, p)] = model.NewBoolVar(f"ho_{a_idx}_{d}_{p}")
                        if count_target >= 0 and (meta[a_idx]["class_id"], d, p) in class_slot_occ:
                            class_slot_occ[(meta[a_idx]["class_id"], d, p)].append(ho[(a_idx, d, p)])
                    if allow_even:
                        he[(a_idx, d, p)] = model.NewBoolVar(f"he_{a_idx}_{d}_{p}")
                        if count_target >= 0 and (meta[a_idx]["class_id"], d, p) in class_slot_occ:
                            class_slot_occ[(meta[a_idx]["class_id"], d, p)].append(he[(a_idx, d, p)])
                leg_vars = (
                    [ho[(a_idx, d, p)] for (d, p) in slots if (a_idx, d, p) in ho]
                    + [he[(a_idx, d, p)] for (d, p) in slots if (a_idx, d, p) in he]
                )
                if not leg_vars:
                    model.Add(0 == 1)
                else:
                    model.Add(sum(leg_vars) == 1)

    # ---------- 同课位冲突（按周实例：all与单腿互斥，单/双腿可并存） ----------
    DISABLE_CONFLICTS = "cpsat_disable_conflicts" in os.environ
    DISABLE_TEACHER_CONFLICTS = os.environ.get("CPSAT_DISABLE_TEACHER", "") == "1"

    def _conflict(key_by: dict[tuple[int, int, int], list[int]], owner: str) -> None:
        if DISABLE_CONFLICTS:
            return
        if owner == "teacher_id" and DISABLE_TEACHER_CONFLICTS:
            return
        if owner == "class_id" and os.environ.get("CPSAT_DISABLE_CLASS", "") == "1":
            return
        buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        # 收集全周、单周腿和双周腿。此前漏掉 he，导致两个同教师的
        # 双周半课可以落到同一课位，模型仍返回可行解。
        for (a_idx, d, p) in list(y) + list(ho) + list(he):
            entity = meta[a_idx][owner]
            if entity is None:
                continue
            buckets[(entity, d, p)].append(a_idx)
        for (entity, d, p), idxs in buckets.items():
            idxs = list(dict.fromkeys(idxs))
            all_vars = [y[(i, d, p)] for i in idxs if (i, d, p) in y]
            odd_vars = [ho[(i, d, p)] for i in idxs if (i, d, p) in ho]
            even_vars = [he[(i, d, p)] for i in idxs if (i, d, p) in he]
            if all_vars:
                model.Add(sum(all_vars) + sum(odd_vars) <= 1)
                model.Add(sum(all_vars) + sum(even_vars) <= 1)
            if len(odd_vars) > 1:
                model.Add(sum(odd_vars) <= 1)
            if len(even_vars) > 1:
                model.Add(sum(even_vars) <= 1)

    _conflict(class_by_slot, "class_id")
    _conflict(teacher_by_slot, "teacher_id")

    # 白天单双周归属：单周组只能单周、双周组只能双周；不要求同格对课
    by_cs: dict[tuple[int, int], int] = {}
    for a_idx, m in meta.items():
        by_cs[(m["class_id"], m["subject_id"])] = a_idx
    for spec in daytime_parity_pairs or []:
        odd_sids = [int(x) for x in (spec.get("odd_subjects") or ())]
        even_sids = [int(x) for x in (spec.get("even_subjects") or ())]
        if not odd_sids or not even_sids:
            subjects = spec.get("subjects") or ()
            if len(subjects) != 2:
                continue
            odd_sids, even_sids = [int(subjects[0])], [int(subjects[1])]
        pair_days = {int(d) for d in (spec.get("weekdays") or [])}
        pair_periods = {int(p) for p in (spec.get("periods") or [])}
        if not pair_days or not pair_periods:
            continue
        class_ids = {m["class_id"] for m in meta.values()}
        for cid in class_ids:
            odd_as = [by_cs[cid, sid] for sid in odd_sids if (cid, sid) in by_cs]
            even_as = [by_cs[cid, sid] for sid in even_sids if (cid, sid) in by_cs]
            for a_idx in odd_as + even_as:
                for d in pair_days:
                    for p in pair_periods:
                        if (a_idx, d, p) in y:
                            model.Add(y[(a_idx, d, p)] == 0)
            for a_idx in odd_as:
                for d in pair_days:
                    for p in pair_periods:
                        if (a_idx, d, p) in he:
                            model.Add(he[(a_idx, d, p)] == 0)
            for a_idx in even_as:
                for d in pair_days:
                    for p in pair_periods:
                        if (a_idx, d, p) in ho:
                            model.Add(ho[(a_idx, d, p)] == 0)

    # 指定班级课位必须由允许学科占用；缺少对应课时方案时模型会明确返回 INFEASIBLE。
    for class_id, required_slots in class_required.items():
        for (weekday, period), allowed_subjects in required_slots.items():
            terms = [
                var
                for slot_map in (y, ho, he)
                for (a_idx, day, lesson), var in slot_map.items()
                if day == weekday
                and lesson == period
                and meta[a_idx]["class_id"] == int(class_id)
                and meta[a_idx]["subject_id"] in allowed_subjects
            ]
            model.Add(sum(terms) >= 1)

    # ---------- 日上限（班级/教师，周六独立） ----------
    def _day_cap(kind: str, cap_weekday: int | None, cap_saturday: int | None) -> None:
        per_day: dict[tuple[Any, int], list[Any]] = defaultdict(list)
        for (a_idx, d, p), var in y.items():
            entity = meta[a_idx][kind]
            if entity is None:
                continue
            per_day[(entity, d)].append(var)
        for (entity, d), vars_ in per_day.items():
            cap = cap_saturday if d == 6 and cap_saturday is not None else cap_weekday
            if cap is not None:
                model.Add(sum(vars_) <= cap)

    _day_cap("class_id", max_class_lessons_per_day, max_class_lessons_on_saturday)

    def _teacher_day_terms(include_halves: bool):
        per_day: dict[tuple[int, int], list[Any]] = defaultdict(list)
        odd_per_day: dict[tuple[int, int], list[Any]] = defaultdict(list)
        even_per_day: dict[tuple[int, int], list[Any]] = defaultdict(list)
        for (a_idx, d, p), var in y.items():
            t = meta[a_idx]["teacher_id"]
            if t is None:
                continue
            per_day[(t, d)].append(var)
        for (a_idx, d, p), var in ho.items():
            t = meta[a_idx]["teacher_id"]
            if t is None:
                continue
            odd_per_day[(t, d)].append(var)
        for (a_idx, d, p), var in he.items():
            t = meta[a_idx]["teacher_id"]
            if t is None:
                continue
            even_per_day[(t, d)].append(var)
        return per_day, odd_per_day, even_per_day

    # 教师日上限：白天课 + 0.5腿按周实例取大；规则名单内教师取更严者
    td_limits = teacher_daily_limits or {}
    per_day, odd_per_day, even_per_day = _teacher_day_terms(include_halves=True)
    for (t, d), vars_ in per_day.items():
        cap = None
        if d == 6 and max_teacher_lessons_on_saturday is not None:
            cap = max_teacher_lessons_on_saturday
        elif max_teacher_lessons_per_day is not None:
            cap = max_teacher_lessons_per_day
        # 教师日上限规则作用域为工作日；周六由独立的周六上限覆盖（与贪心一致）。
        if t in td_limits and d != 6:
            cap = min(cap if cap is not None else 10**9, td_limits[t])
        if cap is None:
            continue
        halves = max(
            sum(1 for v in odd_per_day.get((t, d), [])),
            sum(1 for v in even_per_day.get((t, d), [])),
        )
        model.Add(sum(vars_) + halves <= cap)

    for req in teacher_period_minima or ():
        tid = int(req["teacher_id"])
        period_set = {int(p) for p in req.get("periods") or []}
        day_set = {int(d) for d in req.get("weekdays") or []} or set(range(1, days + 1))
        minimum = int(req["minimum"])
        if not period_set or minimum <= 0:
            continue
        counted: list[Any] = []
        for (a_idx, d, p), var in y.items():
            if meta[a_idx]["teacher_id"] == tid and d in day_set and p in period_set:
                counted.append(var)
        for (a_idx, d, p), var in ho.items():
            if meta[a_idx]["teacher_id"] == tid and d in day_set and p in period_set:
                counted.append(var)
        for (a_idx, d, p), var in he.items():
            if meta[a_idx]["teacher_id"] == tid and d in day_set and p in period_set:
                counted.append(var)
        if counted:
            model.Add(sum(counted) >= minimum)
        else:
            model.Add(0 == 1)

    # 同科日上限：非连堂学科每天最多 1 节；连堂学科（数学）最多 2 节。
    cons_subjects_cap = {
        int(entry["target_id"])
        for entry in (consecutive_requirements or {}).get("subjects") or []
    }
    spread_subjects: set[int] = set()
    if subject_daily_spread:
        teaching_days = min(days, 5)
        for assignment in assignments:
            weekday_periods = assignment.get("weekday_periods")
            if weekday_periods is None:
                weekday_periods = min(
                    float(assignment.get("weekly_periods") or 0),
                    teaching_days,
                )
            if float(weekday_periods or 0) > teaching_days:
                spread_subjects.add(int(assignment["subject_id"]))
    odd_day_sub: dict[tuple[int, int, int], list[Any]] = defaultdict(list)
    even_day_sub: dict[tuple[int, int, int], list[Any]] = defaultdict(list)
    for (a_idx, d, p), var in y.items():
        key = (meta[a_idx]["class_id"], meta[a_idx]["subject_id"], d)
        odd_day_sub[key].append(var)
        even_day_sub[key].append(var)
    for (a_idx, d, p), var in ho.items():
        odd_day_sub[(meta[a_idx]["class_id"], meta[a_idx]["subject_id"], d)].append(var)
    for (a_idx, d, p), var in he.items():
        even_day_sub[(meta[a_idx]["class_id"], meta[a_idx]["subject_id"], d)].append(var)
    for key, vars_ in list(odd_day_sub.items()) + list(even_day_sub.items()):
        _cid, sid, _d = key
        # 课时超过工作日数量时，均匀分布需要允许一个日期出现第 2 节，
        # 余下日期各 1 节（例如 6 节工作日课时按 4+2 分布）。
        cap = 2 if sid in cons_subjects_cap or sid in spread_subjects else 1
        if max_same_subject_per_day is not None and sid not in cons_subjects_cap:
            cap = min(cap, int(max_same_subject_per_day))
        if vars_:
            model.Add(sum(vars_) <= cap)

    # 教师周上限
    if max_teacher_weekly_periods is not None:
        per_teacher: dict[int, list[Any]] = defaultdict(list)
        for (a_idx, d, p), var in y.items():
            t = meta[a_idx]["teacher_id"]
            if t is not None:
                per_teacher[t].append(var)
        for (a_idx, d, p), var in ho.items():
            t = meta[a_idx]["teacher_id"]
            if t is not None:
                per_teacher[t].append(var)
        for (a_idx, d, p), var in he.items():
            t = meta[a_idx]["teacher_id"]
            if t is not None:
                per_teacher[t].append(var)
        for t, vars_ in per_teacher.items():
            model.Add(sum(vars_) <= max_teacher_weekly_periods)

    # ---------- 课位组合（OR-of-AND，按 班级+学科） ----------
    for pattern in patterns:
        alternatives = pattern["alternatives"]
        if len(alternatives) < 1:
            continue
        target_class_ids = sorted({
            meta[a_idx]["class_id"]
            for a_idx in meta
            if meta[a_idx]["subject_id"] in [int(i) for i in pattern["target_ids"]]
        })
        total_per_alt = {
            sum(int(g["count"]) for g in alt) for alt in alternatives
        }
        if len(total_per_alt) != 1:
            continue
        for class_id in target_class_ids:
            idxs = [
                a_idx for a_idx in meta
                if meta[a_idx]["class_id"] == class_id
                and meta[a_idx]["subject_id"] in [int(i) for i in pattern["target_ids"]]
            ]
            if not idxs:
                continue
            slot_sum = {}
            for (a_idx, d, p), var in y.items():
                if a_idx in idxs:
                    slot_sum[(d, p)] = slot_sum.get((d, p), 0) + var
            if len(alternatives) == 1:
                for group in alternatives[0]:
                    terms = [slot_sum.get((d, p), 0) for d in group["weekdays"] for p in group["periods"]]
                    model.Add(sum(terms) == int(group["count"]))
                continue
            choice = [model.NewBoolVar(f"pat_{class_id}_{i}") for i in range(len(alternatives))]
            model.Add(sum(choice) == 1)
            for i, alt in enumerate(alternatives):
                for group in alt:
                    terms = [slot_sum.get((d, p), 0) for d in group["weekdays"] for p in group["periods"]]
                    model.Add(sum(terms) == int(group["count"])).OnlyEnforceIf(choice[i])

    # ---------- 连堂（重化窗口：owner 在某天存在 ≥min_block 连续节次，至少 min_days 天） ----------
    def _blocks(kind: str, entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            min_block = int(entry["min_block"])
            min_days = int(entry["min_days"])
            scope = set(entry.get("weekdays") or range(1, days + 1))
            target_id = int(entry["target_id"])
            owner_key = "class_id" if kind == "subjects" else "teacher_id"
            by_owner: dict[Any, list[tuple[int, int, Any, int]]] = defaultdict(list)
            class_mode = str(entry.get("class_mode") or "same_class") if kind == "teachers" else "same_class"
            for slot_map in (y, ho, he):
                for (a_idx, d, p), var in slot_map.items():
                    entity = meta[a_idx][owner_key]
                    if kind == "subjects" and meta[a_idx]["subject_id"] == target_id:
                        by_owner[meta[a_idx]["class_id"]].append((d, p, var, meta[a_idx]["class_id"]))
                    elif kind == "teachers" and entity == target_id:
                        by_owner[entity].append((d, p, var, meta[a_idx]["class_id"]))
            for owner, placements in by_owner.items():
                # same_class：同一班自己的连续课；cross_class：同一教师的连续课必须覆盖至少两个班。
                # 旧规则默认 same_class，避免把普通教师连堂误解释成跨班连堂。
                vars_by_slot: dict[tuple[int, int], list[Any]] = defaultdict(list)
                vars_by_class_slot: dict[tuple[int, int, int], list[Any]] = defaultdict(list)
                for (d, p, var, class_id) in placements:
                    vars_by_slot[(d, p)].append(var)
                    vars_by_class_slot[(class_id, d, p)].append(var)
                occupied: dict[tuple[int, int], Any] = {}
                occupied_by_class: dict[tuple[int, int, int], Any] = {}
                for (class_id, d, p), vars_ in vars_by_class_slot.items():
                    o = model.NewBoolVar(f"occ_{kind}_{target_id}_{owner}_{class_id}_{d}_{p}")
                    for v in vars_:
                        model.AddImplication(v, o)
                    model.Add(o <= sum(vars_))
                    occupied_by_class[(class_id, d, p)] = o
                for (d, p), vars_ in vars_by_slot.items():
                    o = model.NewBoolVar(f"occ_{kind}_{target_id}_{owner}_{d}_{p}")
                    for v in vars_:
                        model.AddImplication(v, o)
                    model.Add(o <= sum(vars_))
                    occupied[(d, p)] = o
                day_sat = {}
                for d in sorted({d for (d, _p) in occupied} & scope):
                    windows = []
                    if kind == "teachers" and class_mode == "same_class":
                        class_ids = sorted({class_id for class_id, day, _period in occupied_by_class if day == d})
                        for class_id in class_ids:
                            class_windows = []
                            for start in range(1, periods_per_day - min_block + 2):
                                window_vars = [occupied_by_class.get((class_id, d, start + j)) for j in range(min_block)]
                                if any(v is None for v in window_vars):
                                    continue
                                w = model.NewBoolVar(f"blk_{kind}_{target_id}_{owner}_{class_id}_{d}_{start}")
                                for v in window_vars:
                                    model.AddImplication(w, v)
                                class_windows.append(w)
                            windows.extend(class_windows)
                    else:
                        for start in range(1, periods_per_day - min_block + 2):
                            window_vars = [occupied.get((d, start + j)) for j in range(min_block)]
                            if any(v is None for v in window_vars):
                                continue
                            w = model.NewBoolVar(f"blk_{kind}_{target_id}_{owner}_{d}_{start}")
                            for v in window_vars:
                                model.AddImplication(w, v)
                            if kind == "teachers" and class_mode == "cross_class":
                                class_flags = []
                                for class_id in sorted({class_id for class_id, day, _period in occupied_by_class if day == d}):
                                    flags = [occupied_by_class.get((class_id, d, start + j)) for j in range(min_block)]
                                    flags = [flag for flag in flags if flag is not None]
                                    if not flags:
                                        continue
                                    cf = model.NewBoolVar(f"blk_class_{target_id}_{owner}_{class_id}_{d}_{start}")
                                    for flag in flags:
                                        model.AddImplication(flag, cf)
                                    model.Add(cf <= sum(flags))
                                    class_flags.append(cf)
                                if len(class_flags) < 2:
                                    continue
                                model.Add(sum(class_flags) >= 2).OnlyEnforceIf(w)
                            windows.append(w)
                    if not windows:
                        continue
                    ds = model.NewBoolVar(f"dsat_{kind}_{target_id}_{owner}_{d}")
                    for w in windows:
                        model.AddImplication(w, ds)
                    model.Add(ds <= sum(windows))
                    day_sat[d] = ds
                if day_sat:
                    model.Add(sum(day_sat.values()) >= min_days)
                else:
                    model.Add(1 == 0)  # 该目标在当前网格下无任何可连堂窗口

    _blocks("subjects", cons.get("subjects") or [])
    _blocks("teachers", cons.get("teachers") or [])

    # ---------- 班级课程连续性 ----------
    # 工作日/周六：第1~7节必须都有课；第8、9节是自习，可空。
    pack_days = (
        {int(day) for day in class_gap_free_weekdays}
        if class_gap_free_weekdays is not None
        else (set(range(1, 7)) if class_gap_free else set())
    )
    if pack_days:
        occ_by_class: dict[int, dict[int, dict[int, Any]]] = defaultdict(lambda: defaultdict(dict))
        for (c, d, p), vars_ in class_slot_occ.items():
            occ = model.NewBoolVar(f"occ_{c}_{d}_{p}")
            for v in vars_:
                model.AddImplication(v, occ)
            model.Add(occ <= sum(vars_))
            occ_by_class[c][d][p] = occ
        core_last = min(7, periods_per_day)
        odd_by_cdp: dict[tuple[int, int, int], list[Any]] = defaultdict(list)
        even_by_cdp: dict[tuple[int, int, int], list[Any]] = defaultdict(list)
        for (a_idx, d, p), var in y.items():
            key = (meta[a_idx]["class_id"], d, p)
            odd_by_cdp[key].append(var)
            even_by_cdp[key].append(var)
        for (a_idx, d, p), var in ho.items():
            odd_by_cdp[(meta[a_idx]["class_id"], d, p)].append(var)
        for (a_idx, d, p), var in he.items():
            even_by_cdp[(meta[a_idx]["class_id"], d, p)].append(var)

        def _force_occupied(vars_: list[Any], name: str) -> None:
            if not vars_:
                return
            occ = model.NewBoolVar(name)
            for v in vars_:
                model.AddImplication(v, occ)
            model.Add(occ <= sum(vars_))
            model.Add(occ == 1)

        for c, day_map in occ_by_class.items():
            for d, period_occ in day_map.items():
                if d not in pack_days:
                    continue
                for p in range(1, core_last + 1):
                    if d == 6:
                        _force_occupied(odd_by_cdp.get((c, d, p), []), f"socc_{c}_{d}_{p}")
                        _force_occupied(even_by_cdp.get((c, d, p), []), f"secc_{c}_{d}_{p}")
                    elif p in period_occ:
                        model.Add(period_occ[p] == 1)

    # ---------- 教师周六无空节（连续无内空堂，可不从第1节起） ----------
    for gf in (gap_free_groups or []):
        gap_teachers = set(gf.get("teachers") or [])
        gap_days = set(gf.get("weekdays") or range(1, days + 1))
        if not gap_teachers or not gap_days:
            continue
        # 完备性：范围内每个课位都建占用变量（无可用任务的课位 occ 恒 0，
        # 这样“被禁排课位两侧有课”的内空堂也会被约束闭合，或暴露真无解）。
        # 按周实例拆分：单周占用=全周课+单周腿，双周占用=全周课+双周腿。
        # 单双周腿分散在不同节次时，并集口径会误判有空堂；按周实例各自连续才是真语义。
        parity_maps = {"o": (y, ho), "e": (y, he)}
        t_occ: dict[tuple[str, int, int, int], Any] = {}
        for parity, (base_map, leg_map) in parity_maps.items():
            t_slot_vars: dict[tuple[int, int, int], list[Any]] = defaultdict(list)
            for slot_map in (base_map, leg_map):
                for (a_idx, d, p), var in slot_map.items():
                    if d not in gap_days:
                        continue
                    t = meta[a_idx]["teacher_id"]
                    if t in gap_teachers:
                        t_slot_vars[(t, d, p)].append(var)
            # 第8、9节是自习/活动，不并入白天连续块（与 class_gap_free 的 1×7 口径一致）。
            core_last = min(7, periods_per_day)
            for t in gap_teachers:
                for d in gap_days:
                    starts = []
                    for p in range(1, core_last + 1):
                        vars_ = t_slot_vars.get((t, d, p)) or []
                        o = model.NewBoolVar(f"tocc_{parity}_{t}_{d}_{p}")
                        for v in vars_:
                            model.AddImplication(v, o)
                        model.Add(o <= sum(vars_))
                        t_occ[(parity, t, d, p)] = o
                        s = model.NewBoolVar(f"tstart_{parity}_{t}_{d}_{p}")
                        if p == 1:
                            model.Add(s == o)
                        else:
                            prev = t_occ[(parity, t, d, p - 1)]
                            model.Add(s <= o)
                            model.Add(s + prev <= 1)
                            model.Add(s >= o - prev)  # 上升沿必须记为起点（否则约束可被全0绕过）
                        starts.append(s)
                    model.Add(sum(starts) <= 1)

    # ---------- 节次封顶（如第5节每师最多3节） ----------
    if slot_teacher_cap:
        cap_weekdays = set(slot_teacher_cap.get("weekdays") or [])
        cap_periods = set(slot_teacher_cap.get("periods") or [])
        cap_value = slot_teacher_cap.get("cap")
        if cap_weekdays and cap_periods and cap_value:
            load_by_tp: dict[tuple[int, int], list[Any]] = defaultdict(list)
            odd_by_tp: dict[tuple[int, int], list[Any]] = defaultdict(list)
            even_by_tp: dict[tuple[int, int], list[Any]] = defaultdict(list)
            for (a_idx, d, p), var in y.items():
                t = meta[a_idx]["teacher_id"]
                if t is None or d not in cap_weekdays or p not in cap_periods:
                    continue
                load_by_tp[(t, p)].append(var)
            for (a_idx, d, p), var in ho.items():
                t = meta[a_idx]["teacher_id"]
                if t is None or d not in cap_weekdays or p not in cap_periods:
                    continue
                odd_by_tp[(t, p)].append(var)
            for (a_idx, d, p), var in he.items():
                t = meta[a_idx]["teacher_id"]
                if t is None or d not in cap_weekdays or p not in cap_periods:
                    continue
                even_by_tp[(t, p)].append(var)
            # 与规则校验口径一致：第5节按课位承担量计数，单双周腿也合计
            # 不能超过上限，避免模型允许而最终硬规则判定为超量。
            for key in set(load_by_tp) | set(odd_by_tp) | set(even_by_tp):
                base = sum(load_by_tp.get(key, []))
                odd = odd_by_tp.get(key, [])
                even = even_by_tp.get(key, [])
                model.Add(base + sum(odd) + sum(even) <= int(cap_value))

    # ---------- 均匀分布：同一学科每天最多1节（课时超过天数允许2节且不连排） ----------
    if subject_daily_spread:
        cs_wd: dict[tuple[int, int], float] = defaultdict(float)
        for a_idx, m in meta.items():
            a = m["assignment"]
            wd = a.get("weekday_periods")
            if wd is None:
                wd = min(float(a.get("weekly_periods") or 0), float(days))
            cs_wd[(m["class_id"], m["subject_id"])] += float(wd or 0)
        cons_subjects = {int(e["target_id"]) for e in (consecutive_requirements or {}).get("subjects") or []}
        y_by_csdp: dict[tuple[int, int, int], dict[int, list[Any]]] = defaultdict(lambda: defaultdict(list))
        for (a_idx, d, p), var in y.items():
            m = meta[a_idx]
            if d <= 5:
                y_by_csdp[(m["class_id"], m["subject_id"], d)][p].append(var)
        for (c, s, d), pmap in y_by_csdp.items():
            total_wd = cs_wd.get((c, s), 0)
            if abs(total_wd - round(total_wd)) > 0.01:
                continue
            total_wd_int = int(round(total_wd))
            teaching_days = min(days, 5)
            base, remainder = divmod(total_wd_int, teaching_days)
            all_vars = [v for ps in pmap.values() for v in ps]
            # 均分：非连堂学科每天最多 1 节；连堂（数学）才允许 base+1（最多 2）。
            day_max = 2 if s in cons_subjects or s in spread_subjects else 1
            model.Add(sum(all_vars) <= min(day_max, base + (1 if remainder else 0)))
            if total_wd_int > teaching_days:
                model.Add(sum(all_vars) >= base)
            if remainder and s not in cons_subjects and s not in spread_subjects:
                for p in range(1, periods_per_day):
                    a1 = sum(pmap.get(p, []))
                    a2 = sum(pmap.get(p + 1, []))
                    model.Add(a1 + a2 <= 1)  # 同日两节不连排

        # 对每个班级-学科精确控制“余数天”：仅对全周课的白天课时建模，
        # 单双周半课由各自周腿独立处理。
        for (c, s), total_wd in cs_wd.items():
            if abs(total_wd - round(total_wd)) > 0.01:
                continue
            total_wd_int = int(round(total_wd))
            teaching_days = min(days, 5)
            base, remainder = divmod(total_wd_int, teaching_days)
            day_max = 2 if s in cons_subjects or s in spread_subjects else 1
            if not remainder and total_wd_int <= 0:
                continue
            # 非连堂学科不允许“某天 2 节”的余数天模型。
            if s not in cons_subjects and s not in spread_subjects:
                continue
            extra_days = []
            for d in range(1, min(days, 5) + 1):
                pmap = y_by_csdp.get((c, s, d), {})
                day_vars = [v for ps in pmap.values() for v in ps]
                count = model.NewIntVar(0, max(1, day_max), f"subject_day_count_{c}_{s}_{d}")
                model.Add(count == sum(day_vars))
                model.Add(count >= base)
                model.Add(count <= min(day_max, base + (1 if remainder else 0)))
                if remainder:
                    is_extra = model.NewBoolVar(f"subject_extra_day_{c}_{s}_{d}")
                    model.Add(count == base + 1).OnlyEnforceIf(is_extra)
                    model.Add(count == base).OnlyEnforceIf(is_extra.Not())
                    extra_days.append(is_extra)
            if remainder and len(extra_days) == teaching_days:
                model.Add(sum(extra_days) == remainder)

    # ---------- 活动课（音美心）：同一班级同一天最多 1 节 ----------
    fill_ids_hard = set(gap_fill_subject_ids or ())
    if fill_ids_hard:
        act_odd: dict[tuple[int, int], list[Any]] = defaultdict(list)
        act_even: dict[tuple[int, int], list[Any]] = defaultdict(list)
        for (a_idx, d, p), var in y.items():
            if meta[a_idx]["subject_id"] in fill_ids_hard:
                key = (meta[a_idx]["class_id"], d)
                act_odd[key].append(var)
                act_even[key].append(var)
        for (a_idx, d, p), var in ho.items():
            if meta[a_idx]["subject_id"] in fill_ids_hard:
                act_odd[(meta[a_idx]["class_id"], d)].append(var)
        for (a_idx, d, p), var in he.items():
            if meta[a_idx]["subject_id"] in fill_ids_hard:
                act_even[(meta[a_idx]["class_id"], d)].append(var)
        for vars_ in list(act_odd.values()) + list(act_even.values()):
            if len(vars_) > 1:
                model.Add(sum(vars_) <= 1)

    # ---------- 软目标：主科尽量靠前；活动课优先第8、9节，只有 1～7 会空堂时才补进去 ----------
    early_ids = set(early_subject_ids or ())
    fill_ids = fill_ids_hard
    late_from = max(1, int(gap_fill_late_from_period))
    costs: list[Any] = []
    if early_ids or fill_ids:
        for slot_map in (y, ho, he):
            for (a_idx, _d, p), var in slot_map.items():
                sid = meta[a_idx]["subject_id"]
                if sid in early_ids:
                    costs.append(int(p) * var)
                elif sid in fill_ids:
                    # 第8节远优先于第9节；赵永丽等每人10班，第8节装不下时才用第9节。
                    if p >= late_from:
                        penalty = (int(p) - late_from) * 50
                    else:
                        penalty = 200 + int(p)
                    if penalty:
                        costs.append(penalty * var)
        # 换种子得到不同排法；权重远小于音美心第8节优先（50/200）。
        rng = random.Random(int(random_seed))
        for slot_map in (y, ho, he):
            for (a_idx, _d, _p), var in slot_map.items():
                if meta[a_idx]["subject_id"] in fill_ids:
                    continue
                costs.append(rng.randint(0, 4) * var)
    for pref in early_subject_prefs or ():
        subj = {int(sid) for sid in (pref.get("subject_ids") or [])}
        preferred = {int(period) for period in (pref.get("periods") or []) if int(period) >= 1}
        try:
            max_out = max(0, int(pref.get("max_outside")))
        except (TypeError, ValueError):
            max_out = 0
        if not subj or not preferred:
            continue
        by_cs: dict[tuple[int, int], list[Any]] = defaultdict(list)
        for slot_map in (y, ho, he):
            for (a_idx, _d, p), var in slot_map.items():
                if meta[a_idx]["subject_id"] not in subj:
                    continue
                if int(p) in preferred:
                    continue
                by_cs[(meta[a_idx]["class_id"], meta[a_idx]["subject_id"])].append(var)
        hard = str(pref.get("priority") or "soft") == "hard"
        for (class_id, subject_id), vars_ in by_cs.items():
            if not vars_:
                continue
            total = sum(vars_)
            if hard:
                model.Add(total <= max_out)
            else:
                slack = model.NewIntVar(0, len(vars_), f"early_out_{class_id}_{subject_id}")
                model.Add(total <= max_out + slack)
                costs.append(slack * 80)
    if costs:
        model.Minimize(sum(costs))

    # ---------- 贪心热启动 hint ----------
    # 贪心毫秒级出一个师生无冲突解，作为 CP-SAT 初始解提示，把「从零搜首个可行解」
    # 变成「验证+修复+优化」。半课单双周腿不 hint（交给求解器配对）。
    # SCHEDULING_GREEDY_HINT=0 可关闭。
    if os.environ.get("SCHEDULING_GREEDY_HINT", "1") != "0":
        try:
            greedy = generate_schedule(
                assignments,
                days=days,
                periods_per_day=periods_per_day,
                forbidden_slots=forbidden,
                max_class_lessons_per_day=max_class_lessons_per_day,
                max_teacher_lessons_per_day=max_teacher_lessons_per_day,
                max_class_lessons_on_saturday=max_class_lessons_on_saturday,
                max_teacher_lessons_on_saturday=max_teacher_lessons_on_saturday,
                max_same_subject_per_day=max_same_subject_per_day,
                max_teacher_weekly_periods=max_teacher_weekly_periods,
                teacher_daily_limits=teacher_daily_limits,
                slot_patterns=slot_patterns,
                teacher_forbidden_slots=t_forbidden,
                teacher_class_forbidden_slots=tc_forbidden,
                subject_forbidden_slots=s_forbidden,
                class_slot_allowed_subjects=class_allowed,
                random_seed=int(random_seed),
            )
            id_to_idx: dict[int, int] = {}
            for idx, a in enumerate(assignments):
                aid = a.get("id")
                if aid is not None:
                    id_to_idx[int(aid)] = idx
            hint_rows = 0
            for it in greedy.items:
                if it.week_parity != WeekParity.all:
                    continue
                var = y.get((id_to_idx.get(int(it.assignment_id), -1), int(it.weekday), int(it.period)))
                if var is not None:
                    model.AddHint(var, 1)
                    hint_rows += 1
            if on_progress is not None:
                on_progress({
                    "phase": "daytime_search",
                    "message": f"贪心热启动：已注入 {hint_rows} 个全周课位 hint",
                    "elapsed": round(time.perf_counter() - started, 1),
                    "solutions": 0,
                })
        except Exception as exc:  # 贪心任何异常都不阻塞 CP-SAT 正常求解
            print(f"[CPSAT] 贪心热启动跳过: {exc}")

    # ---------- 求解 ----------
    if on_progress is not None:
        on_progress({
            "phase": "daytime_search",
            "message": "白天课约束模型已建好，开始搜索可行解",
            "elapsed": round(time.perf_counter() - started, 1),
            "solutions": 0,
        })
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_time_seconds
    solver.parameters.num_search_workers = max(1, int(num_search_workers))
    solver.parameters.random_seed = int(random_seed)
    solver.parameters.randomize_search = True

    polish = max(0.0, float(polish_seconds))

    class _ProgressCallback(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self.solutions = 0
            self._last_emit = 0.0
            self._first_at = 0.0

        def on_solution_callback(self) -> None:
            self.solutions += 1
            now = time.perf_counter()
            if self.solutions == 1:
                self._first_at = now
            if polish and self.solutions >= 1 and now - self._first_at >= polish:
                self.StopSearch()
            if on_progress is None:
                return
            if self.solutions > 1 and now - self._last_emit < 0.8:
                return
            self._last_emit = now
            elapsed = now - started
            objective = None
            try:
                objective = int(self.ObjectiveValue())
            except Exception:
                objective = None
            on_progress({
                "phase": "daytime_search",
                "message": f"已找到第 {self.solutions} 个可行解，继续优化中",
                "elapsed": round(elapsed, 1),
                "solutions": self.solutions,
                "objective": objective,
            })

    callback = _ProgressCallback()
    status = solve_with_stop_deadline(
        solver,
        lambda: solver.Solve(model, callback),
        max_time_seconds=max_time_seconds,
    )
    status_name = solver.StatusName(status)
    seconds = time.perf_counter() - started
    if on_progress is not None:
        on_progress({
            "phase": "daytime_done",
            "message": f"白天课求解结束：{status_name}，耗时 {seconds:.1f}s，可行解 {callback.solutions} 个",
            "elapsed": round(seconds, 1),
            "solutions": callback.solutions,
            "status": status_name,
        })

    result = CpSatSolveResult(status=status_name, solve_seconds=seconds)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return result

    for (a_idx, d, p), var in y.items():
        if solver.Value(var):
            a = meta[a_idx]["assignment"]
            result.items.append(ScheduleItem(
                assignment_id=int(a.get("id") or 0), class_id=meta[a_idx]["class_id"],
                subject_id=meta[a_idx]["subject_id"], teacher_id=meta[a_idx]["teacher_id"],
                weekday=d, period=p, room=a.get("room"), week_parity=WeekParity.all,
            ))
    for (a_idx, d, p), var in ho.items():
        if solver.Value(var):
            a = meta[a_idx]["assignment"]
            result.items.append(ScheduleItem(
                assignment_id=int(a.get("id") or 0), class_id=meta[a_idx]["class_id"],
                subject_id=meta[a_idx]["subject_id"], teacher_id=meta[a_idx]["teacher_id"],
                weekday=d, period=p, room=a.get("room"), week_parity=WeekParity.odd,
            ))
    for (a_idx, d, p), var in he.items():
        if solver.Value(var):
            a = meta[a_idx]["assignment"]
            result.items.append(ScheduleItem(
                assignment_id=int(a.get("id") or 0), class_id=meta[a_idx]["class_id"],
                subject_id=meta[a_idx]["subject_id"], teacher_id=meta[a_idx]["teacher_id"],
                weekday=d, period=p, room=a.get("room"), week_parity=WeekParity.even,
            ))
    result.items.sort(key=lambda item: (item.class_id, item.weekday, item.period))
    return result
