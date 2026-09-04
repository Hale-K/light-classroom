from app.services.scheduling.rules import RuleGroupDocument
from app.services.scheduling import ScheduleItem
from app.services.scheduling.soft_search import improve_soft_period_preferences


def _item(
    assignment_id: int,
    class_id: int,
    subject_id: int,
    teacher_id: int | None,
    weekday: int,
    period: int,
) -> ScheduleItem:
    return ScheduleItem(
        assignment_id=assignment_id,
        class_id=class_id,
        subject_id=subject_id,
        teacher_id=teacher_id,
        weekday=weekday,
        period=period,
    )


def test_swaps_late_major_with_early_activity_same_day():
    items = [
        _item(1, 10, 1, 7, 1, 8),
        _item(2, 10, 20, 8, 1, 2),
        _item(3, 10, 2, 9, 1, 1),
    ]
    result = improve_soft_period_preferences(
        items,
        early_subject_ids={1, 2},
        gap_fill_subject_ids={20},
        late_from_period=8,
        evening_start_period=10,
        max_time_seconds=2,
    )
    by_subject = {item.subject_id: item.period for item in result.items if item.weekday == 1}
    assert by_subject[1] == 2
    assert by_subject[20] == 8
    assert result.r23_after == 0
    assert result.r24_after == 0
    assert result.swaps >= 1


def test_rejects_swap_that_double_books_a_teacher():
    items = [
        _item(1, 10, 1, 7, 1, 8),
        _item(2, 10, 20, 8, 1, 2),
        _item(3, 11, 3, 7, 1, 2),
    ]
    result = improve_soft_period_preferences(
        items,
        early_subject_ids={1},
        gap_fill_subject_ids={20},
        late_from_period=8,
        evening_start_period=10,
        max_time_seconds=2,
    )
    by_id = {item.assignment_id: (item.weekday, item.period) for item in result.items}
    assert by_id[1] == (1, 8)
    assert by_id[2] == (1, 2)
    assert result.swaps == 0


def test_rejects_swap_onto_teacher_forbidden_slot():
    items = [
        _item(1, 10, 1, 7, 1, 8),
        _item(2, 10, 20, 8, 1, 2),
    ]
    result = improve_soft_period_preferences(
        items,
        early_subject_ids={1},
        gap_fill_subject_ids={20},
        teacher_forbidden_slots={7: {(1, 2)}},
        late_from_period=8,
        evening_start_period=10,
        max_time_seconds=2,
    )
    assert result.swaps == 0
    assert {(item.subject_id, item.period) for item in result.items} == {(1, 8), (20, 2)}


def test_does_not_move_evening_lessons():
    items = [
        _item(1, 10, 1, 7, 1, 10),
        _item(2, 10, 20, 8, 1, 2),
    ]
    result = improve_soft_period_preferences(
        items,
        early_subject_ids={1},
        gap_fill_subject_ids={20},
        late_from_period=8,
        evening_start_period=10,
        max_time_seconds=2,
    )
    by_id = {item.assignment_id: item.period for item in result.items}
    assert by_id[1] == 10
    assert by_id[2] == 2


def test_hard_rule_group_blocks_activity_on_disallowed_slot():
    group = RuleGroupDocument(
        id="grade-1-rules",
        name="t",
        academic_year="2026-2027",
        term="1",
        rules=[
            {
                "id": "R18-s",
                "title": "第8、9节仅活动课",
                "code": "class_allowed_subjects",
                "priority": "hard",
                "target": {"type": "class", "ids": [10]},
                "weekdays": [1],
                "periods": [8, 9],
                "params": {"allowed_subject_ids": [20], "require_occupied_slots": False},
            },
            {
                "id": "R23",
                "title": "主科尽量靠前",
                "code": "subject_prefer_early_periods",
                "priority": "soft",
                "target": {"type": "subject", "ids": [1]},
            },
        ],
    )
    items = [
        _item(1, 10, 1, 7, 1, 3),
        _item(2, 10, 20, 8, 1, 8),
    ]
    result = improve_soft_period_preferences(
        items,
        early_subject_ids={1},
        gap_fill_subject_ids={20},
        class_slot_allowed_subjects={10: {(1, 8): {20}, (1, 9): {20}}},
        rule_group=group,
        late_from_period=8,
        evening_start_period=10,
        max_time_seconds=2,
    )
    by_subject = {item.subject_id: item.period for item in result.items}
    assert by_subject[20] == 8
    assert by_subject[1] == 3


def test_cross_day_swap_can_pull_major_out_of_period_eight():
    items = [
        _item(1, 10, 1, 7, 1, 8),
        _item(2, 10, 20, 8, 2, 2),
        _item(3, 10, 2, 9, 2, 1),
    ]
    result = improve_soft_period_preferences(
        items,
        early_subject_ids={1, 2},
        gap_fill_subject_ids={20},
        late_from_period=8,
        evening_start_period=10,
        max_time_seconds=2,
    )
    major = next(item for item in result.items if item.subject_id == 1)
    activity = next(item for item in result.items if item.subject_id == 20)
    assert major.period < 8
    assert activity.period >= 8
    assert result.r23_after == 0


def test_relocates_activity_to_empty_late_slot_and_fills_with_late_major():
    items = [
        _item(1, 10, 20, 8, 1, 2),
        _item(2, 10, 1, 7, 2, 8),
        _item(3, 10, 2, 9, 1, 1),
    ]
    result = improve_soft_period_preferences(
        items,
        early_subject_ids={1, 2},
        gap_fill_subject_ids={20},
        late_from_period=8,
        evening_start_period=10,
        max_time_seconds=2,
    )
    activity = next(item for item in result.items if item.subject_id == 20)
    major = next(item for item in result.items if item.subject_id == 1)
    assert activity.period >= 8
    assert major.period < 8
    assert result.r23_after == 0
    assert result.r24_after == 0
