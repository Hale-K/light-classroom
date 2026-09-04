"""晚自习 CP-SAT 求解（阶段3）。

正式路径只排课时方案里的学科晚课：1 不拆、0.5 对课，不填自主学习。
R02/R19 钉位必须落该教师本班学科额度。
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Iterable, Mapping

from ortools.sat.python import cp_model

from app.models.enums import WeekParity
from app.services.scheduling.core import ScheduleItem, evening_is_flex_half
from app.services.scheduling.cpsat import CpSatSolveResult
from app.services.scheduling.solver_watchdog import solve_with_stop_deadline


def _evening_quota(row: Mapping[str, Any], parity: WeekParity) -> int:
    # 晚课单双只看 evening_periods_* / evening_parity，不跟白天 week_parity 绑死。
    field = "evening_periods_odd" if parity is WeekParity.odd else "evening_periods_even"
    return max(0, int(row.get(field) or 0))


def _evening_either_parity(row: Mapping[str, Any], odd: int, even: int) -> bool:
    """0.5 晚课无规定单双：只排 1 条半课，求解器任选单周或双周。"""
    return evening_is_flex_half(row) if (odd > 0 and even > 0) else False


def _slots_from_profile(
    daily_periods: list[int],
    first_evening_period: int,
) -> list[tuple[int, int]]:
    return [
        (weekday, first_evening_period + offset)
        for weekday, count in enumerate(daily_periods, start=1)
        for offset in range(max(0, int(count)))
    ]


def solve_evening_cpsat(
    assignments: Iterable[dict[str, Any]],
    *,
    class_ids: Iterable[int],
    first_evening_period: int,
    evening_daily_periods_odd: list[int],
    evening_daily_periods_even: list[int],
    activity_subject_id: int | None = None,
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
    r15_enabled: bool = True,
    max_time_seconds: float = 100.0,
    num_search_workers: int = 8,
    random_seed: int = 42,
    polish_seconds: float = 100.0,
) -> CpSatSolveResult:
    """用 CP-SAT 求晚课表；不含活动课填空（由 generate_evening_schedule 后处理）。"""
    started = time.perf_counter()
    assignment_rows = [dict(row) for row in assignments]
    class_id_set = {int(cid) for cid in class_ids}
    required = required_teacher_by_slot or {}
    t_forbidden = teacher_forbidden_slots or {}
    class_allowed = class_slot_allowed_subjects or {}
    free_days = {int(k): set(v) for k, v in (free_evening_days or {}).items()}
    declared_pairs = [(int(a), int(b)) for a, b in (parity_subject_pairs or [])]
    exclude_r15 = set(r15_exclude_subject_ids or ())
    skip_r15_teachers = {int(tid) for tid in (r15_exclude_teacher_ids or ())}
    preferred = {
        int(tid): {int(d) for d in days}
        for tid, days in (teacher_preferred_evening_weekdays or {}).items()
        if days
    }
    required_eve_days = {
        int(tid): {int(d) for d in days}
        for tid, days in (teacher_required_evening_weekdays or {}).items()
        if days
    }

    slots_odd = _slots_from_profile(evening_daily_periods_odd, first_evening_period)
    slots_even = _slots_from_profile(evening_daily_periods_even, first_evening_period)
    slots_common = sorted(set(slots_odd) & set(slots_even))
    if not slots_common and not slots_odd and not slots_even:
        return CpSatSolveResult(status="OPTIMAL", solve_seconds=0.0)

    # 晚课↔白天：教师在哪些天满足联动
    link_ok_days: dict[int, set[int] | None] = {}
    anchor = list(anchor_items or ())
    for link in teacher_evening_daytime_links or ():
        tid = int(link["teacher_id"])
        evening_start = int(link.get("evening_start_period") or first_evening_period)
        req_p = int(link["required_daytime_period"])
        days = {
            int(item.weekday)
            for item in anchor
            if item.teacher_id == tid
            and item.period < evening_start
            and item.period == req_p
        }
        link_ok_days[tid] = days

    # 分类：整周 / 单双任选半课 / 仅单 / 仅双
    full_idx: list[int] = []
    flex_idx: list[int] = []
    odd_idx: list[int] = []
    even_idx: list[int] = []
    meta: dict[int, dict[str, Any]] = {}
    for i, row in enumerate(assignment_rows):
        cid = int(row["class_id"])
        if cid not in class_id_set:
            continue
        o = _evening_quota(row, WeekParity.odd)
        e = _evening_quota(row, WeekParity.even)
        if o <= 0 and e <= 0:
            continue
        meta[i] = {
            "row": row,
            "class_id": cid,
            "subject_id": int(row["subject_id"]),
            "teacher_id": int(row["teacher_id"]) if row.get("teacher_id") is not None else None,
        }
        if _evening_either_parity(row, o, e):
            flex_idx.append(i)
        elif o > 0 and e > 0:
            full_idx.append(i)
        elif o > 0:
            odd_idx.append(i)
        else:
            even_idx.append(i)

    model = cp_model.CpModel()
    y: dict[tuple[int, int, int], Any] = {}   # full (a,d,p)
    ho: dict[tuple[int, int, int], Any] = {}
    he: dict[tuple[int, int, int], Any] = {}

    def slot_ok(a_idx: int, weekday: int, period: int) -> bool:
        m = meta[a_idx]
        tid = m["teacher_id"]
        sid = m["subject_id"]
        cid = m["class_id"]
        if weekday in free_days.get(cid, set()):
            return False
        if tid is not None and (weekday, period) in t_forbidden.get(tid, set()):
            return False
        allowed = class_allowed.get(cid, {}).get((weekday, period))
        if allowed is not None and sid not in allowed:
            return False
        if tid is not None and tid in link_ok_days:
            ok_days = link_ok_days[tid]
            if ok_days is not None and weekday not in ok_days:
                return False
        return True

    unplaced: list[dict[str, Any]] = []

    def _exactly_one(store: dict[tuple[int, int, int], Any], a_idx: int, label: str) -> None:
        """额度必须排满：1 节整周或 1 条半课，不能改用自主学习填。"""
        vars_ = [store[k] for k in store if k[0] == a_idx]
        if not vars_:
            m = meta[a_idx]
            unplaced.append({
                "assignment_id": m["row"].get("id"),
                "class_id": m["class_id"],
                "subject_id": m["subject_id"],
                "teacher_id": m["teacher_id"],
                "reason": f"晚课无合法课位（{label}）",
            })
            model.Add(0 == 1)
            return
        model.Add(sum(vars_) == 1)

    for a_idx in full_idx:
        for d, p in slots_common:
            if slot_ok(a_idx, d, p):
                y[(a_idx, d, p)] = model.NewBoolVar(f"ey_{a_idx}_{d}_{p}")
        _exactly_one(y, a_idx, "整周")

    for a_idx in odd_idx:
        for d, p in slots_odd:
            if slot_ok(a_idx, d, p):
                ho[(a_idx, d, p)] = model.NewBoolVar(f"eho_{a_idx}_{d}_{p}")
        _exactly_one(ho, a_idx, "单周")

    for a_idx in even_idx:
        for d, p in slots_even:
            if slot_ok(a_idx, d, p):
                he[(a_idx, d, p)] = model.NewBoolVar(f"ehe_{a_idx}_{d}_{p}")
        _exactly_one(he, a_idx, "双周")

    for a_idx in flex_idx:
        for d, p in slots_odd:
            if slot_ok(a_idx, d, p):
                ho[(a_idx, d, p)] = model.NewBoolVar(f"eho_{a_idx}_{d}_{p}")
        for d, p in slots_even:
            if slot_ok(a_idx, d, p):
                he[(a_idx, d, p)] = model.NewBoolVar(f"ehe_{a_idx}_{d}_{p}")
        vars_ = [ho[k] for k in ho if k[0] == a_idx] + [he[k] for k in he if k[0] == a_idx]
        if not vars_:
            m = meta[a_idx]
            unplaced.append({
                "assignment_id": m["row"].get("id"),
                "class_id": m["class_id"],
                "subject_id": m["subject_id"],
                "teacher_id": m["teacher_id"],
                "reason": "晚课无合法课位（单双任选）",
            })
            model.Add(0 == 1)
        else:
            model.Add(sum(vars_) == 1)

    # 声明对课：同班两科半腿必须同课位（允许单↔双方向互换；含「程序定单双」）
    by_cs: dict[tuple[int, int], int] = {}
    for a_idx, m in meta.items():
        by_cs[(m["class_id"], m["subject_id"])] = a_idx
    for left, right in declared_pairs:
        for cid in class_id_set:
            a_l = by_cs.get((cid, left))
            a_r = by_cs.get((cid, right))
            if a_l is None or a_r is None:
                continue
            for d, p in slots_common:
                lo = ho.get((a_l, d, p))
                le = he.get((a_l, d, p))
                ro = ho.get((a_r, d, p))
                re = he.get((a_r, d, p))
                # 同格异色：左单=右双，左双=右单
                if lo is not None and re is not None:
                    model.Add(lo == re)
                elif lo is not None:
                    model.Add(lo == 0)
                elif re is not None:
                    model.Add(re == 0)
                if le is not None and ro is not None:
                    model.Add(le == ro)
                elif le is not None:
                    model.Add(le == 0)
                elif ro is not None:
                    model.Add(ro == 0)

    # 班级冲突：同班同课位，全周与单腿互斥；单双可并存
    class_bucket: dict[tuple[int, int, int, str], list[Any]] = defaultdict(list)
    for (a_idx, d, p), var in y.items():
        cid = meta[a_idx]["class_id"]
        class_bucket[(cid, d, p, "o")].append(var)
        class_bucket[(cid, d, p, "e")].append(var)
    for (a_idx, d, p), var in ho.items():
        class_bucket[(meta[a_idx]["class_id"], d, p, "o")].append(var)
    for (a_idx, d, p), var in he.items():
        class_bucket[(meta[a_idx]["class_id"], d, p, "e")].append(var)
    for vars_ in class_bucket.values():
        if len(vars_) > 1:
            model.Add(sum(vars_) <= 1)

    # 额度恰好能铺满网格时，强制每班单周/双周晚课排满（通常各 6 节）
    for cid in class_id_set:
        free = free_days.get(cid, set())
        odd_slots = [(d, p) for d, p in slots_odd if d not in free]
        even_slots = [(d, p) for d, p in slots_even if d not in free]
        full_n = flex_n = odd_n = even_n = 0
        for a_idx, m in meta.items():
            if m["class_id"] != cid:
                continue
            row = m["row"]
            o = _evening_quota(row, WeekParity.odd)
            e = _evening_quota(row, WeekParity.even)
            if _evening_either_parity(row, o, e):
                flex_n += 1
            elif o > 0 and e > 0:
                full_n += 1
            elif o > 0:
                odd_n += 1
            elif e > 0:
                even_n += 1
        units = 2 * full_n + flex_n + odd_n + even_n
        if units != len(odd_slots) + len(even_slots):
            continue
        for parity, target_slots in (("o", odd_slots), ("e", even_slots)):
            for d, p in target_slots:
                vars_ = class_bucket.get((cid, d, p, parity), [])
                if vars_:
                    model.Add(sum(vars_) == 1)
                else:
                    model.Add(0 == 1)

    # 教师冲突
    teacher_bucket: dict[tuple[int, int, int, str], list[Any]] = defaultdict(list)
    for (a_idx, d, p), var in y.items():
        tid = meta[a_idx]["teacher_id"]
        if tid is None:
            continue
        teacher_bucket[(tid, d, p, "o")].append(var)
        teacher_bucket[(tid, d, p, "e")].append(var)
    for (a_idx, d, p), var in ho.items():
        tid = meta[a_idx]["teacher_id"]
        if tid is not None:
            teacher_bucket[(tid, d, p, "o")].append(var)
    for (a_idx, d, p), var in he.items():
        tid = meta[a_idx]["teacher_id"]
        if tid is not None:
            teacher_bucket[(tid, d, p, "e")].append(var)
    for vars_ in teacher_bucket.values():
        if len(vars_) > 1:
            model.Add(sum(vars_) <= 1)

    p0 = int(first_evening_period)
    for tid, days in required_eve_days.items():
        for d in sorted(days):
            odd_vars = teacher_bucket.get((tid, d, p0, "o"), [])
            even_vars = teacher_bucket.get((tid, d, p0, "e"), [])
            if odd_vars:
                model.Add(sum(odd_vars) >= 1)
            else:
                model.Add(0 == 1)
            if even_vars:
                model.Add(sum(even_vars) >= 1)
            else:
                model.Add(0 == 1)

    # R02 / R19 钉位：该班该格必须由指定教师的本班学科晚课占用，不用自主学习。
    for (d, p), class_map in required.items():
        for cid, tid in class_map.items():
            cid, tid = int(cid), int(tid)
            if (d, p) not in set(slots_common) | set(slots_odd) | set(slots_even):
                continue
            candidates = []
            for a_idx, m in meta.items():
                if m["class_id"] != cid or m["teacher_id"] != tid:
                    continue
                for store in (y, ho, he):
                    var = store.get((a_idx, d, p))
                    if var is not None:
                        candidates.append(var)
            if candidates:
                model.Add(sum(candidates) == 1)
            else:
                unplaced.append({
                    "class_id": cid,
                    "teacher_id": tid,
                    "reason": f"钉位周{d}第{p}节没有该教师的本班学科晚课额度",
                })
                model.Add(0 == 1)

    # R15：多班晚课按班级轮转（各班进度一致；排除体育/活动、星期限定教师）
    if r15_enabled:
        bucket_keys = [("o", day) for day in range(1, 7)] + [("e", day) for day in range(1, 7)]
        teacher_bucket: dict[tuple[int, str, int], list[tuple[int, Any]]] = defaultdict(list)
        for (a_idx, d, p), var in y.items():
            m = meta[a_idx]
            tid = m["teacher_id"]
            if tid is None or m["subject_id"] in exclude_r15:
                continue
            teacher_bucket[(tid, "o", d)].append((m["class_id"], var))
            teacher_bucket[(tid, "e", d)].append((m["class_id"], var))
        for (a_idx, d, p), var in ho.items():
            m = meta[a_idx]
            tid = m["teacher_id"]
            if tid is None or m["subject_id"] in exclude_r15:
                continue
            teacher_bucket[(tid, "o", d)].append((m["class_id"], var))
        for (a_idx, d, p), var in he.items():
            m = meta[a_idx]
            tid = m["teacher_id"]
            if tid is None or m["subject_id"] in exclude_r15:
                continue
            teacher_bucket[(tid, "e", d)].append((m["class_id"], var))
        teachers_classes: dict[int, set[int]] = defaultdict(set)
        for a_idx, m in meta.items():
            tid = m["teacher_id"]
            if tid is None or m["subject_id"] in exclude_r15:
                continue
            teachers_classes[tid].add(m["class_id"])
        for tid, classes in teachers_classes.items():
            if len(classes) < 2 or tid in skip_r15_teachers:
                continue
            class_list = sorted(classes)
            n = len(class_list)
            occ: list[Any] = []
            class_in_bucket: list[dict[int, Any]] = []
            for kind, day in bucket_keys:
                pairs = teacher_bucket.get((tid, kind, day), [])
                taken = model.NewBoolVar(f"r15o_{tid}_{kind}_{day}")
                all_vars = [var for _, var in pairs]
                if all_vars:
                    model.Add(sum(all_vars) <= 1)
                    model.Add(taken == sum(all_vars))
                else:
                    model.Add(taken == 0)
                occ.append(taken)
                cmap: dict[int, Any] = {}
                for cid in class_list:
                    flag = model.NewBoolVar(f"r15c_{tid}_{kind}_{day}_{cid}")
                    cvars = [var for class_id, var in pairs if class_id == cid]
                    if cvars:
                        model.Add(sum(cvars) <= 1)
                        model.Add(flag == sum(cvars))
                    else:
                        model.Add(flag == 0)
                    cmap[cid] = flag
                model.Add(sum(cmap.values()) == taken)
                class_in_bucket.append(cmap)
            total = sum(occ)
            model.Add(total >= n)
            model.AddModuloEquality(0, total, n)
            ranks = {cid: model.NewIntVar(0, n - 1, f"r15r_{tid}_{cid}") for cid in class_list}
            model.AddAllDifferent(list(ranks.values()))
            running = model.NewIntVar(0, 12, f"r15i_{tid}_0")
            model.Add(running == 0)
            for i, taken in enumerate(occ):
                before = model.NewIntVar(0, 12, f"r15b_{tid}_{i}")
                model.Add(before == running)
                for cid, flag in class_in_bucket[i].items():
                    model.AddModuloEquality(ranks[cid], before, n).OnlyEnforceIf(flag)
                nxt = model.NewIntVar(0, 12, f"r15n_{tid}_{i}")
                model.Add(nxt == running + taken)
                running = nxt

    # 目标：额度已强制排满，只惩罚偏好外星期。
    pref_penalty: list[Any] = []
    for (a_idx, d, p), var in list(y.items()) + list(ho.items()) + list(he.items()):
        tid = meta[a_idx]["teacher_id"]
        if tid is None:
            continue
        allowed = preferred.get(tid)
        if allowed and d not in allowed:
            pref_penalty.append(var)
    if pref_penalty:
        model.Minimize(sum(pref_penalty))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_time_seconds
    solver.parameters.num_search_workers = max(1, int(num_search_workers))
    solver.parameters.random_seed = int(random_seed)
    solver.parameters.randomize_search = True
    polish = max(0.0, float(polish_seconds))

    class _StopAfterPolish(cp_model.CpSolverSolutionCallback):
        def __init__(self) -> None:
            super().__init__()
            self._first_at = 0.0
            self.solutions = 0

        def on_solution_callback(self) -> None:
            self.solutions += 1
            now = time.perf_counter()
            if self.solutions == 1:
                self._first_at = now
            if polish and now - self._first_at >= polish:
                self.StopSearch()

    callback = _StopAfterPolish()
    status = solve_with_stop_deadline(
        solver,
        lambda: solver.Solve(model, callback),
        max_time_seconds=max_time_seconds,
    )
    status_name = solver.StatusName(status)
    seconds = time.perf_counter() - started
    result = CpSatSolveResult(status=status_name, solve_seconds=seconds, unplaced=list(unplaced))
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return result

    for (a_idx, d, p), var in y.items():
        if solver.Value(var):
            row = meta[a_idx]["row"]
            result.items.append(ScheduleItem(
                assignment_id=int(row.get("id") or 0),
                class_id=meta[a_idx]["class_id"],
                subject_id=meta[a_idx]["subject_id"],
                teacher_id=meta[a_idx]["teacher_id"],
                weekday=d, period=p, room=row.get("room"),
                week_parity=WeekParity.all,
            ))
    for (a_idx, d, p), var in ho.items():
        if solver.Value(var):
            row = meta[a_idx]["row"]
            result.items.append(ScheduleItem(
                assignment_id=int(row.get("id") or 0),
                class_id=meta[a_idx]["class_id"],
                subject_id=meta[a_idx]["subject_id"],
                teacher_id=meta[a_idx]["teacher_id"],
                weekday=d, period=p, room=row.get("room"),
                week_parity=WeekParity.odd,
            ))
    for (a_idx, d, p), var in he.items():
        if solver.Value(var):
            row = meta[a_idx]["row"]
            result.items.append(ScheduleItem(
                assignment_id=int(row.get("id") or 0),
                class_id=meta[a_idx]["class_id"],
                subject_id=meta[a_idx]["subject_id"],
                teacher_id=meta[a_idx]["teacher_id"],
                weekday=d, period=p, room=row.get("room"),
                week_parity=WeekParity.even,
            ))
    result.items.sort(key=lambda item: (item.class_id, item.weekday, item.period))
    return result


def fill_evening_activity_slots(
    items: list[ScheduleItem],
    *,
    class_ids: Iterable[int],
    first_evening_period: int,
    evening_daily_periods_odd: list[int],
    evening_daily_periods_even: list[int],
    activity_subject_id: int | None,
    free_evening_days: Mapping[int, set[int]] | None = None,
    required_teacher_by_slot: Mapping[tuple[int, int], Mapping[int, int]] | None = None,
) -> list[ScheduleItem]:
    """在 CP-SAT 学科/钉位落完后，把仍空的晚课格填成自主学习。"""
    if activity_subject_id is None:
        return list(items)
    working = list(items)
    free_days = {int(k): set(v) for k, v in (free_evening_days or {}).items()}
    required = required_teacher_by_slot or {}

    def occupied(cid: int, d: int, p: int, parity: WeekParity) -> bool:
        for item in working:
            if item.class_id != cid or item.weekday != d or item.period != p:
                continue
            if item.week_parity is WeekParity.all:
                return True
            if item.week_parity is parity:
                return True
        return False

    for cid in sorted({int(c) for c in class_ids}):
        for parity, daily in (
            (WeekParity.odd, evening_daily_periods_odd),
            (WeekParity.even, evening_daily_periods_even),
        ):
            for d, count in enumerate(daily, start=1):
                if d in free_days.get(cid, set()):
                    # 自习日：若完全空则补活动；若已有课则跳过
                    pass
                for offset in range(max(0, int(count))):
                    p = first_evening_period + offset
                    if occupied(cid, d, p, parity):
                        continue
                    # 钉位已由 CP-SAT 处理；此处仅填普通空位
                    if cid in required.get((d, p), {}):
                        continue
                    working.append(ScheduleItem(
                        assignment_id=0,
                        class_id=cid,
                        subject_id=int(activity_subject_id),
                        teacher_id=None,
                        weekday=d, period=p, room=None,
                        week_parity=parity,
                    ))
    working.sort(key=lambda item: (item.class_id, item.weekday, item.period))
    return working


def generate_evening_schedule(
    assignments: Iterable[dict[str, Any]],
    *,
    class_ids: Iterable[int],
    first_evening_period: int,
    evening_daily_periods_odd: list[int],
    evening_daily_periods_even: list[int],
    activity_subject_id: int | None = None,
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
    r15_enabled: bool = True,
    max_time_seconds: float = 100.0,
    num_search_workers: int = 8,
    random_seed: int = 42,
    polish_seconds: float = 100.0,
) -> CpSatSolveResult:
    """正式晚课生成：只排课时方案中的学科晚课，不填自主学习。"""
    return solve_evening_cpsat(
        assignments,
        class_ids=class_ids,
        first_evening_period=first_evening_period,
        evening_daily_periods_odd=evening_daily_periods_odd,
        evening_daily_periods_even=evening_daily_periods_even,
        activity_subject_id=activity_subject_id,
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
        random_seed=random_seed,
        polish_seconds=polish_seconds,
    )
