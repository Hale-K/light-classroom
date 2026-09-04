"""白天软目标局部搜索：在硬约束已满足的课表上压 R23/R24。

只交换同一班级的两节白天课（节次、星期可不同），不改晚课。
每次接受交换前检查占用冲突、禁排/限科，并在提供规则组时重跑硬规则。
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from app.models.enums import WeekParity
from app.services.scheduling.core import ScheduleItem, occupancy_keys, parity_conflicts


def _daytime_subject_spread_ok(
    items: list[ScheduleItem],
    *,
    evening_start: int,
    consecutive_subject_ids: set[int] | None = None,
) -> bool:
    """非连堂学科白天每天最多 1 节；连堂学科（数学）最多 2 节。"""
    cons = consecutive_subject_ids or set()
    odd: dict[tuple[int, int, int], int] = defaultdict(int)
    even: dict[tuple[int, int, int], int] = defaultdict(int)
    for item in items:
        if item.period >= evening_start:
            continue
        key = (item.class_id, item.subject_id, item.weekday)
        if item.week_parity != WeekParity.even:
            odd[key] += 1
        if item.week_parity != WeekParity.odd:
            even[key] += 1
    for store in (odd, even):
        for (_cid, sid, _wd), count in store.items():
            if count > (2 if sid in cons else 1):
                return False
    return True


def _class_core_periods_ok(
    items: list[ScheduleItem],
    *,
    evening_start: int,
    core_last: int = 7,
    weekdays: set[int] | None = None,
) -> bool:
    """班级第 1～core_last 节不能被软优化掏空（周六单双周各自满）。"""
    days = weekdays or set(range(1, 7))
    odd: dict[tuple[int, int], set[int]] = defaultdict(set)
    even: dict[tuple[int, int], set[int]] = defaultdict(set)
    for item in items:
        if item.period >= evening_start or item.weekday not in days:
            continue
        key = (item.class_id, item.weekday)
        if item.week_parity != WeekParity.even:
            odd[key].add(item.period)
        if item.week_parity != WeekParity.odd:
            even[key].add(item.period)
    core = set(range(1, core_last + 1))
    keys = set(odd) | set(even)
    for key in keys:
        if key[1] == 6:
            if not (core <= odd.get(key, set()) and core <= even.get(key, set())):
                return False
        elif not core <= odd.get(key, set()) | even.get(key, set()):
            return False
    return True


@dataclass
class SoftSearchStats:
    items: list[ScheduleItem]
    swaps: int = 0
    score_before: int = 0
    score_after: int = 0
    r23_before: int = 0
    r23_after: int = 0
    r24_before: int = 0
    r24_after: int = 0
    seconds: float = 0.0
    attempts: int = 0
    improving: int = 0
    rejected: int = 0


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


def _period_score(
    items: list[ScheduleItem],
    *,
    early_ids: set[int],
    fill_ids: set[int],
    late_from: int,
    evening_start: int,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
) -> tuple[int, int, int]:
    occupied: dict[tuple[int, int], set[int]] = defaultdict(set)
    for item in items:
        if item.period < evening_start:
            occupied[(item.class_id, item.weekday)].add(item.period)
    r23 = 0
    r24 = 0
    period_cost = 0
    late_slots = list(range(late_from, evening_start))
    allowed_map = class_slot_allowed_subjects or {}
    for item in items:
        if item.period >= evening_start:
            continue
        if item.subject_id in early_ids:
            if item.period >= 8:
                r23 += 1
            period_cost += int(item.period)
        elif item.subject_id in fill_ids:
            if item.period < late_from:
                taken = occupied.get((item.class_id, item.weekday), set())
                if any(
                    period not in taken
                    and _slot_allows_subject(allowed_map, item.class_id, item.weekday, period, item.subject_id)
                    for period in late_slots
                ):
                    r24 += 1
                    period_cost += 200 + int(item.period)
    return r23 * 10_000 + r24 * 10_000 + period_cost, r23, r24


def _slot_mates(items: list[ScheduleItem], index: int) -> bool:
    item = items[index]
    for other_index, other in enumerate(items):
        if other_index == index:
            continue
        if (
            other.class_id == item.class_id
            and other.weekday == item.weekday
            and other.period == item.period
            and parity_conflicts(item.week_parity, other.week_parity)
        ):
            return True
    return False


def _apply_swap(items: list[ScheduleItem], left: int, right: int) -> list[ScheduleItem]:
    a = items[left]
    b = items[right]
    out = list(items)
    out[left] = replace(a, weekday=b.weekday, period=b.period)
    out[right] = replace(b, weekday=a.weekday, period=a.period)
    return out


def _apply_relocate(
    items: list[ScheduleItem],
    activity_index: int,
    empty_period: int,
    donor_index: int,
) -> list[ScheduleItem]:
    activity = items[activity_index]
    donor = items[donor_index]
    out = list(items)
    out[activity_index] = replace(activity, period=empty_period)
    out[donor_index] = replace(donor, weekday=activity.weekday, period=activity.period)
    return out


def _occupancy_conflict(items: list[ScheduleItem]) -> bool:
    class_occ: set[tuple[int, int, int, str]] = set()
    teacher_occ: set[tuple[int, int, int, str]] = set()
    for item in items:
        for key in occupancy_keys(item.class_id, item.weekday, item.period, item.week_parity):
            if key in class_occ:
                return True
            class_occ.add(key)
        if item.teacher_id is None:
            continue
        for key in occupancy_keys(item.teacher_id, item.weekday, item.period, item.week_parity):
            if key in teacher_occ:
                return True
            teacher_occ.add(key)
    return False


def _placement_allowed(
    item: ScheduleItem,
    *,
    forbidden_slots: set[tuple[int, int]],
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]],
    teacher_class_forbidden_slots: Mapping[tuple[int, int], set[tuple[int, int]]],
    subject_forbidden_slots: Mapping[int, set[tuple[int, int]]],
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]],
) -> bool:
    slot = (item.weekday, item.period)
    if slot in forbidden_slots:
        return False
    if item.teacher_id is not None:
        tid = int(item.teacher_id)
        if slot in teacher_forbidden_slots.get(tid, set()):
            return False
        if slot in teacher_class_forbidden_slots.get((tid, int(item.class_id)), set()):
            return False
    if slot in subject_forbidden_slots.get(item.subject_id, set()):
        return False
    allowed = class_slot_allowed_subjects.get(item.class_id, {}).get(slot)
    if allowed is not None and item.subject_id not in allowed:
        return False
    return True


def improve_soft_period_preferences(
    items: list[ScheduleItem],
    *,
    early_subject_ids: set[int] | None = None,
    gap_fill_subject_ids: set[int] | None = None,
    late_from_period: int = 8,
    evening_start_period: int = 10,
    forbidden_slots: set[tuple[int, int]] | None = None,
    teacher_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    teacher_class_forbidden_slots: Mapping[tuple[int, int], set[tuple[int, int]]] | None = None,
    subject_forbidden_slots: Mapping[int, set[tuple[int, int]]] | None = None,
    class_slot_allowed_subjects: Mapping[int, Mapping[tuple[int, int], set[int]]] | None = None,
    rule_group: Any | None = None,
    class_head_teacher_ids: dict[int, int | None] | None = None,
    max_time_seconds: float = 20.0,
    hard_ok: Callable[[list[ScheduleItem]], bool] | None = None,
) -> SoftSearchStats:
    """Hill-climb same-class daytime swaps to cut R23/R24 violations."""
    started = time.perf_counter()
    early_ids = set(early_subject_ids or ())
    fill_ids = set(gap_fill_subject_ids or ())
    evening_start = int(evening_start_period or 10)
    late_from = max(1, int(late_from_period or 8))
    current = list(items)
    stats = SoftSearchStats(items=current)
    if not current or (not early_ids and not fill_ids):
        stats.seconds = time.perf_counter() - started
        return stats

    forbidden = forbidden_slots or set()
    t_forbidden = teacher_forbidden_slots or {}
    tc_forbidden = teacher_class_forbidden_slots or {}
    if not tc_forbidden and rule_group is not None and class_head_teacher_ids is not None:
        from app.services.scheduling.rules import generation_teacher_class_forbidden_slots

        tc_forbidden = generation_teacher_class_forbidden_slots(rule_group, class_head_teacher_ids)
    s_forbidden = subject_forbidden_slots or {}
    class_allowed = class_slot_allowed_subjects or {}
    cons_subject_ids: set[int] = set()
    if rule_group is not None:
        from app.services.scheduling.rules import generation_consecutive_requirements

        cons_subject_ids = {
            int(entry["target_id"])
            for entry in generation_consecutive_requirements(rule_group).get("subjects") or []
        }

    baseline_core_packed = _class_core_periods_ok(current, evening_start=evening_start)

    def structural_ok(trial: list[ScheduleItem], moved: list[int]) -> bool:
        if _occupancy_conflict(trial):
            return False
        if not _daytime_subject_spread_ok(
            trial,
            evening_start=evening_start,
            consecutive_subject_ids=cons_subject_ids,
        ):
            return False
        # 仅当基线 1～7 节已铺满时，禁止软优化掏空；稀疏夹具/半成品课表仍允许对调。
        if baseline_core_packed and not _class_core_periods_ok(trial, evening_start=evening_start):
            return False
        return all(
            _placement_allowed(
                trial[index],
                forbidden_slots=forbidden,
                teacher_forbidden_slots=t_forbidden,
                teacher_class_forbidden_slots=tc_forbidden,
                subject_forbidden_slots=s_forbidden,
                class_slot_allowed_subjects=class_allowed,
            )
            for index in moved
        )

    accept = hard_ok
    if accept is None and rule_group is not None:
        from app.services.scheduling.rules import blocking_rule_results, evaluate_rule_group

        baseline_blocked = {
            result.rule_id
            for result in blocking_rule_results(
                evaluate_rule_group(
                    rule_group,
                    current,
                    schedule_available=True,
                    evening_start_period=evening_start,
                    class_head_teacher_ids=class_head_teacher_ids,
                )
            )
        }

        def accept(trial: list[ScheduleItem]) -> bool:
            blocked = blocking_rule_results(
                evaluate_rule_group(
                    rule_group,
                    trial,
                    schedule_available=True,
                    evening_start_period=evening_start,
                    class_head_teacher_ids=class_head_teacher_ids,
                )
            )
            # 基线已无硬违规时，软优化不得引入任何硬违规（比仅比较规则 ID 集合更严）。
            if not baseline_blocked:
                return not blocked
            return {result.rule_id for result in blocked} <= baseline_blocked

    score_kwargs = dict(
        early_ids=early_ids,
        fill_ids=fill_ids,
        late_from=late_from,
        evening_start=evening_start,
        class_slot_allowed_subjects=class_allowed,
    )
    score, r23, r24 = _period_score(current, **score_kwargs)
    stats.score_before = stats.score_after = score
    stats.r23_before = stats.r23_after = r23
    stats.r24_before = stats.r24_after = r24
    deadline = started + max(0.0, float(max_time_seconds))

    while time.perf_counter() < deadline:
        daytime = [
            index
            for index, item in enumerate(current)
            if item.period < evening_start and not _slot_mates(current, index)
        ]
        by_class: dict[int, list[int]] = defaultdict(list)
        for index in daytime:
            by_class[current[index].class_id].append(index)

        ranked: list[tuple[int, list[ScheduleItem], list[int], int, int]] = []
        for indexes in by_class.values():
            for pos, left in enumerate(indexes):
                a = current[left]
                for right in indexes[pos + 1 :]:
                    b = current[right]
                    if a.week_parity != b.week_parity:
                        continue
                    if a.weekday == b.weekday and a.period == b.period:
                        continue
                    stats.attempts += 1
                    trial = _apply_swap(current, left, right)
                    trial_score, trial_r23, trial_r24 = _period_score(trial, **score_kwargs)
                    if trial_score >= score:
                        continue
                    ranked.append((trial_score, trial, [left, right], trial_r23, trial_r24))
            fill_indexes = [
                index for index in indexes
                if current[index].subject_id in fill_ids and current[index].period < late_from
            ]
            donor_indexes = [
                index for index in indexes
                if current[index].subject_id in early_ids and current[index].period >= 8
            ]
            occupied_by_day: dict[tuple[int, WeekParity], set[int]] = defaultdict(set)
            for index in indexes:
                item = current[index]
                occupied_by_day[(item.weekday, item.week_parity)].add(item.period)
            for activity_index in fill_indexes:
                activity = current[activity_index]
                taken = occupied_by_day.get((activity.weekday, activity.week_parity), set())
                empty_late = [
                    period
                    for period in range(late_from, evening_start)
                    if period not in taken
                    and _slot_allows_subject(
                        class_allowed, activity.class_id, activity.weekday, period, activity.subject_id
                    )
                ]
                if not empty_late:
                    continue
                for empty_period in empty_late:
                    for donor_index in donor_indexes:
                        donor = current[donor_index]
                        if donor.week_parity != activity.week_parity:
                            continue
                        if donor_index == activity_index:
                            continue
                        stats.attempts += 1
                        trial = _apply_relocate(current, activity_index, empty_period, donor_index)
                        trial_score, trial_r23, trial_r24 = _period_score(trial, **score_kwargs)
                        if trial_score >= score:
                            continue
                        ranked.append(
                            (trial_score, trial, [activity_index, donor_index], trial_r23, trial_r24)
                        )
        ranked.sort(key=lambda row: row[0])
        if not stats.swaps:
            stats.improving = len(ranked)

        moved = False
        for trial_score, trial, moved_indexes, trial_r23, trial_r24 in ranked:
            if time.perf_counter() >= deadline:
                break
            if not structural_ok(trial, moved_indexes):
                stats.rejected += 1
                continue
            if accept is not None and not accept(trial):
                stats.rejected += 1
                continue
            current = trial
            score = trial_score
            r23, r24 = trial_r23, trial_r24
            stats.swaps += 1
            stats.items = current
            stats.score_after = score
            stats.r23_after = r23
            stats.r24_after = r24
            moved = True
            break
        if not moved:
            break

    stats.items = current
    stats.seconds = time.perf_counter() - started
    return stats
