import pytest

from app.services.scheduling.strategies import (
    CandidateContext,
    build_schedule_strategy,
    list_schedule_strategies,
)


def test_schedule_strategy_registry_exposes_teacher_selectable_options():
    options = list_schedule_strategies()

    assert [option.code for option in options] == [
        "daily_balance",
        "cross_day_variety",
        "random_tiebreak",
        "class_compact",
        "teacher_friendly",
        "resource_tight",
        "cross_class_gap_repair",
        "slot_teacher_spread",
    ]
    assert all(option.name and option.description for option in options)


def test_schedule_strategy_combination_respects_teacher_selected_priority():
    compact_first = build_schedule_strategy(["class_compact", "daily_balance"])
    balance_first = build_schedule_strategy(["daily_balance", "class_compact"])
    compact_slot = CandidateContext(
        same_subject_today=0,
        class_day_load=3,
        teacher_day_load=0,
        period=4,
        class_gap_penalty=0,
        teacher_gap_penalty=0,
        teacher_adjacent_count=0,
    )
    balanced_slot = CandidateContext(
        same_subject_today=0,
        class_day_load=0,
        teacher_day_load=0,
        period=1,
        class_gap_penalty=1,
        teacher_gap_penalty=0,
        teacher_adjacent_count=0,
    )

    assert compact_first.score(compact_slot) < compact_first.score(balanced_slot)
    assert balance_first.score(balanced_slot) < balance_first.score(compact_slot)


def test_schedule_strategy_registry_rejects_unknown_codes():
    with pytest.raises(ValueError, match="未知排课策略"):
        build_schedule_strategy(["not_registered"])
