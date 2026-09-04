"""连堂修复器：为满足教师/学科连堂硬规则做有界局部挪位。

只挪动 week_parity=all 的课程；每次挪位都通过 _can_place_schedule_item 的
全部硬约束（冲突、禁排、日上限、允许课位），并验证挪后确实形成目标连堂。
时间复杂度：O(目标数 × 有界尝试次数 × 单次校验 O(n))，n 为课程总数。
"""

from collections import defaultdict
from typing import TYPE_CHECKING, Any, Mapping

from app.models.enums import WeekParity

if TYPE_CHECKING:  # 避免与 core 循环导入，运行时在函数内延迟导入
    from app.services.scheduling.core import ScheduleItem


def _longest_block(periods: set[int]) -> int:
    longest = current = 0
    for period in sorted(periods):
        current = current + 1 if period - 1 in periods else 1
        longest = max(longest, current)
    return longest


def repair_consecutive_blocks(
    items: "list[ScheduleItem]",
    *,
    subject_blocks: Mapping[int, Mapping[str, Any]],
    teacher_blocks: Mapping[int, Mapping[str, Any]],
    days: int,
    periods_per_day: int,
    forbidden_slots: set[tuple[int, int]],
    max_class_lessons_per_day: int | None = None,
    max_teacher_lessons_per_day: int | None = None,
    max_teacher_lessons_on_saturday: int | None = None,
    max_same_subject_per_day: int | None = None,
    teacher_daily_limits: dict[int, int] | None = None,
    teacher_forbidden_slots=None,
    subject_forbidden_slots=None,
    class_slot_allowed_subjects=None,
    max_moves: int = 1500,
    max_attempts_per_target: int = 12,
) -> "list[ScheduleItem]":
    """逐目标尝试把散课挪成连堂；修不动就保留现状（由评估器如实报告）。"""
    from app.services.scheduling.core import ScheduleItem, _can_place_schedule_item

    def owner_satisfied(owner_idxs: list[int], scope: set[int], min_block: int) -> tuple[int, dict[int, set[int]]]:
        by_day: dict[int, set[int]] = defaultdict(set)
        for idx in owner_idxs:
            item = items[idx]
            by_day[item.weekday].add(item.period)
        satisfied = sum(
            1
            for day, periods in by_day.items()
            if day in scope and _longest_block(periods) >= min_block
        )
        return satisfied, by_day

    def attempt(owner_idxs: list[int], scope: set[int], min_block: int, min_days: int) -> int:
        """返回本次尝试新增的满足天数（0/1）。"""
        satisfied, by_day = owner_satisfied(owner_idxs, scope, min_block)
        if satisfied >= min_days:
            return 0
        unsatisfied_days = [
            day for day in by_day
            if day in scope and _longest_block(by_day[day]) < min_block
        ]
        if not unsatisfied_days:
            return 0
        # 锚点：不满足日里课最多的那天
        anchor = max(unsatisfied_days, key=lambda day: len(by_day[day]))
        anchor_periods = by_day[anchor]

        # 锚点日各节次的占用者（供交换用）
        occupant_at: dict[int, int] = {}
        for idx2, item2 in enumerate(items):
            if item2.weekday == anchor and item2.period not in anchor_periods:
                occupant_at[item2.period] = idx2

        move_candidates: list[tuple[int, ScheduleItem, set[int], int | None]] = []
        for base in sorted(anchor_periods):
            for delta in (1, -1):
                target_period = base + delta
                if target_period < 1 or target_period > periods_per_day or target_period in anchor_periods:
                    continue
                swap_with = occupant_at.get(target_period)
                for idx in owner_idxs:
                    item = items[idx]
                    if item.week_parity != WeekParity.all:
                        continue
                    if item.weekday == anchor:
                        if item.period in anchor_periods and abs(item.period - base) == 1:
                            continue
                        if item.period == base:
                            continue
                        candidate = replace_period(item, target_period)
                        projected = (anchor_periods - {item.period}) | {target_period}
                        if _longest_block(projected) < min_block:
                            continue
                        move_candidates.append((idx, candidate, projected, None))
                    else:
                        candidate = replace_weekday_period(item, anchor, target_period)
                        projected = anchor_periods | {target_period}
                        if _longest_block(projected) < min_block:
                            continue
                        # 情形C：目标位被他人占用 → 交换课位
                        move_candidates.append((idx, candidate, projected, swap_with))
                    if len(move_candidates) >= max_attempts_per_target * 6:
                        break
                if len(move_candidates) >= max_attempts_per_target * 6:
                    break
            if len(move_candidates) >= max_attempts_per_target * 6:
                break

        def _check(candidate, ignored: int) -> bool:
            return _can_place_schedule_item(
                candidate, items,
                days=days, periods_per_day=periods_per_day,
                forbidden_slots=forbidden_slots,
                max_class_lessons_per_day=max_class_lessons_per_day,
                max_teacher_lessons_per_day=max_teacher_lessons_per_day,
                max_teacher_lessons_on_saturday=max_teacher_lessons_on_saturday,
                max_same_subject_per_day=max_same_subject_per_day,
                teacher_daily_limits=teacher_daily_limits,
                teacher_forbidden_slots=teacher_forbidden_slots,
                subject_forbidden_slots=subject_forbidden_slots,
                class_slot_allowed_subjects=class_slot_allowed_subjects,
                ignored_index=ignored,
            )

        tried = 0
        for idx, candidate, projected, swap_idx in move_candidates:
            if tried >= max_attempts_per_target:
                break
            if swap_idx is not None:
                # 交换：双方先落位再校验，任一失败则整体回滚
                original_owner = items[idx]
                original_occ = items[swap_idx]
                items[idx] = candidate
                back_candidate = replace_weekday_period(original_occ, original_owner.weekday, original_owner.period)
                items[swap_idx] = back_candidate
                if not _check(candidate, idx) or not _check(back_candidate, swap_idx):
                    items[idx] = original_owner
                    items[swap_idx] = original_occ
                    continue
                tried += 1
            else:
                if not _check(candidate, idx):
                    continue
                tried += 1
                items[idx] = candidate
            new_satisfied, _ = owner_satisfied(owner_idxs, scope, min_block)
            if new_satisfied > satisfied:
                return 1
            return 0
        return 0

    moves_left = max_moves

    def run_pass(moves_left: int) -> tuple[int, int]:
        gained = 0

        for req in subject_blocks:
            scope = set(req.get("weekdays") or range(1, days + 1))
            min_block = int(req["min_block"])
            min_days = int(req["min_days"])
            target_id = int(req["target_id"])
            by_class: dict[int, list[int]] = defaultdict(list)
            for idx, item in enumerate(items):
                if item.subject_id == target_id and item.week_parity == WeekParity.all:
                    by_class[item.class_id].append(idx)
            for class_id in sorted(by_class):
                if moves_left <= 0:
                    return gained, moves_left
                used = attempt(by_class[class_id], scope, min_block, min_days)
                moves_left -= used
                gained += used

        for req in teacher_blocks:
            scope = set(req.get("weekdays") or range(1, days + 1))
            min_block = int(req["min_block"])
            min_days = int(req["min_days"])
            target_id = int(req["target_id"])
            owner_idxs = [
                idx for idx, item in enumerate(items)
                if item.teacher_id == target_id and item.week_parity == WeekParity.all
            ]
            if moves_left <= 0:
                return gained, moves_left
            used = attempt(owner_idxs, scope, min_block, min_days)
            moves_left -= used
            gained += used
        return gained, moves_left

    moves_left = max_moves
    for _ in range(6):
        if moves_left <= 0:
            break
        gained, moves_left = run_pass(moves_left)
        if gained == 0:
            break

    return items


def replace_period(item: "ScheduleItem", period: int) -> "ScheduleItem":
    from dataclasses import replace
    return replace(item, period=period)


def replace_weekday_period(item: "ScheduleItem", weekday: int, period: int) -> "ScheduleItem":
    from dataclasses import replace
    return replace(item, weekday=weekday, period=period)
