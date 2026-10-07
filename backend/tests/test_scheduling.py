from datetime import date
from time import perf_counter

import pytest

from app.models.enums import WeekParity
from app.services.scheduling import (
    ExamRoomResource,
    arrange_students,
    arrange_exam_candidates,
    build_evening_study_items,
    repair_evening_hard_constraints,
    ScheduleItem,
    diagnose_staffing_gaps,
    expand_schedule,
    filter_zero_hour_assignments,
    generate_exam_schedule,
    generate_schedule,
    normalize_exam_room_resources,
    compact_class_gaps,
    repair_class_gaps,
    resolve_exam_candidates,
    validate_schedule_requirements,
)


def test_zero_hour_assignments_are_excluded_but_evening_only_assignments_remain():
    assignments = [
        {
            "id": 1,
            "class_id": 1,
            "subject_id": 10,
            "teacher_id": 100,
            "weekly_periods": 0.5,
            "weekday_periods": 0,
            "saturday_periods": 0,
            "evening_periods_odd": 0,
            "evening_periods_even": 0,
        },
        {
            "id": 2,
            "class_id": 1,
            "subject_id": 11,
            "teacher_id": 101,
            "weekly_periods": 0.5,
            "weekday_periods": 0,
            "saturday_periods": 0,
            "evening_periods_odd": 1,
            "evening_periods_even": 0,
        },
        {
            "id": 3,
            "class_id": 1,
            "subject_id": 12,
            "teacher_id": 102,
            "weekly_periods": 0,
        },
    ]

    filtered = filter_zero_hour_assignments(assignments)

    assert [item["id"] for item in filtered] == [2]


def test_invigilator_pool_uses_all_active_teachers_but_excludes_school_admins():
    from types import SimpleNamespace
    from app.models.enums import BaseUserRole, UserStatus
    from app.services.scheduling import select_invigilator_ids

    users = [
        SimpleNamespace(id=1, role=BaseUserRole.teacher, status=UserStatus.active),
        SimpleNamespace(id=2, role=BaseUserRole.teacher, status=UserStatus.disabled),
        SimpleNamespace(id=3, role=BaseUserRole.director, status=UserStatus.active),
        SimpleNamespace(id=4, role=BaseUserRole.teacher, status=UserStatus.active),
    ]

    assert select_invigilator_ids(users) == [1, 4]


def test_exam_room_status_follows_resource_and_exam_lifecycle():
    from datetime import date
    from app.services.scheduling import resolve_exam_room_status

    today = date(2026, 8, 24)
    assert resolve_exam_room_status('available', today=today) == 'available'
    assert resolve_exam_room_status('available', selected=True, today=today) == 'selected'
    assert resolve_exam_room_status('available', selected=True, scheduled_dates=[date(2026, 8, 25)], today=today) == 'scheduled'
    assert resolve_exam_room_status('available', selected=True, scheduled_dates=[today], today=today) == 'ongoing'
    assert resolve_exam_room_status('available', selected=True, scheduled_dates=[date(2026, 8, 23)], today=today) == 'completed'
    assert resolve_exam_room_status('maintenance', selected=True, scheduled_dates=[today], today=today) == 'maintenance'
    assert resolve_exam_room_status('disabled', today=today) == 'disabled'


def test_exam_room_resources_are_trimmed_and_duplicate_names_are_rejected():
    rooms = normalize_exam_room_resources([
        ExamRoomResource(name="  实验楼报告厅  ", capacity=120),
        ExamRoomResource(name="高三(1)班教室", capacity=40),
    ])

    assert rooms[0] == ExamRoomResource(name="实验楼报告厅", capacity=120)
    with pytest.raises(ValueError, match="考场名称重复"):
        normalize_exam_room_resources([
            ExamRoomResource(name="备用考场", capacity=30),
            ExamRoomResource(name=" 备用考场 ", capacity=20),
        ])


def test_remaining_gap_reports_the_subject_teacher_conflict_and_staffing_need():
    from app.services.scheduling import ScheduleItem

    items = [
        *[
            ScheduleItem(period=period, weekday=1, class_id=1, teacher_id=period,
                         subject_id=period, assignment_id=period)
            for period in range(1, 6)
        ],
        ScheduleItem(period=7, weekday=1, class_id=1, teacher_id=10,
                     subject_id=8, assignment_id=7),
        ScheduleItem(period=6, weekday=1, class_id=2, teacher_id=10,
                     subject_id=8, assignment_id=8),
    ]

    issues = diagnose_staffing_gaps(items)

    assert issues == [{
        "class_id": 1,
        "subject_id": 8,
        "teacher_id": 10,
        "weekday": 1,
        "gap_period": 6,
        "scheduled_period": 7,
        "blocking_class_id": 2,
        "additional_teachers": 1,
    }]


def test_evening_study_items_use_course_hours_and_teaching_relations():
    assignments = [
        {
            "id": 101,
            "class_id": 1,
            "subject_id": 10,
            "teacher_id": 1001,
            "room": "高一（1）班",
            "week_parity": "all",
            "evening_periods_odd": 1,
            "evening_periods_even": 1,
        },
        {
            "id": 102,
            "class_id": 1,
            "subject_id": 20,
            "teacher_id": 1002,
            "room": "高一（1）班",
            "week_parity": "all",
            "evening_periods_odd": 0,
            "evening_periods_even": 1,
        },
    ]

    items = build_evening_study_items(
        assignments,
        class_ids=[1],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 1, 0, 0, 0, 0, 0],
    )

    full = [i for i in items if i.subject_id == 10 and i.week_parity.value == "all"]
    half = [i for i in items if i.subject_id == 20 and i.week_parity.value == "even"]
    assert len(full) == 1 and full[0].teacher_id == 1001
    assert len(half) == 1 and half[0].teacher_id == 1002
    assert full[0].weekday != half[0].weekday or full[0].period != half[0].period
    assert all(item.subject_id != 999 for item in items)


def test_evening_cpsat_places_full_and_half_quotas_with_activity_fill():
    from app.services.scheduling.evening_cpsat import generate_evening_schedule

    result = generate_evening_schedule(
        [
            {
                "id": 101,
                "class_id": 1,
                "subject_id": 10,
                "teacher_id": 1001,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
            {
                "id": 102,
                "class_id": 1,
                "subject_id": 20,
                "teacher_id": 1002,
                "week_parity": "all",
                "evening_periods_odd": 0,
                "evening_periods_even": 1,
            },
        ],
        class_ids=[1],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 1, 0, 0, 0, 0, 0],
        activity_subject_id=999,
        r15_enabled=False,
        max_time_seconds=5,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    full = [i for i in result.items if i.subject_id == 10 and i.week_parity.value == "all"]
    half = [i for i in result.items if i.subject_id == 20 and i.week_parity.value == "even"]
    assert len(full) == 1 and full[0].teacher_id == 1001
    assert len(half) == 1 and half[0].teacher_id == 1002
    assert full[0].weekday != half[0].weekday or full[0].period != half[0].period
    assert all(item.subject_id != 999 for item in result.items)


def test_evening_cpsat_half_flex_lets_solver_pick_odd_or_even():
    from app.services.scheduling.evening_cpsat import generate_evening_schedule

    result = generate_evening_schedule(
        [
            {
                "id": 1,
                "class_id": 2,
                "subject_id": 25,
                "teacher_id": 716,
                "week_parity": "odd",
                "weekday_periods": 3.0,
                "saturday_periods": 0.5,
                "weekly_periods": 3.5,
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
                "evening_parity": "either",
            },
            {
                "id": 2,
                "class_id": 4,
                "subject_id": 25,
                "teacher_id": 716,
                "week_parity": "even",
                "weekday_periods": 3.0,
                "saturday_periods": 0.5,
                "weekly_periods": 3.5,
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
                "evening_parity": "either",
            },
        ],
        class_ids=[2, 4],
        first_evening_period=10,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        teacher_forbidden_slots={716: {(2, 10), (3, 10), (5, 10), (6, 10)}},
        r15_enabled=False,
        max_time_seconds=5,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    items = [item for item in result.items if item.teacher_id == 716]
    assert len(items) == 2
    assert {item.weekday for item in items} <= {1, 4}
    assert {item.week_parity for item in items} == {WeekParity.odd, WeekParity.even}


def test_evening_cpsat_pairs_physics_and_history_in_either_orientation():
    from app.services.scheduling.evening_cpsat import generate_evening_schedule

    result = generate_evening_schedule(
        [
            {
                "id": 1,
                "class_id": 1,
                "subject_id": 26,
                "teacher_id": 100,
                "week_parity": "all",
                "weekday_periods": 3,
                "saturday_periods": 1,
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
                "evening_parity": "either",
            },
            {
                "id": 2,
                "class_id": 1,
                "subject_id": 32,
                "teacher_id": 200,
                "week_parity": "all",
                "weekday_periods": 3,
                "saturday_periods": 1,
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
                "evening_parity": "either",
            },
        ],
        class_ids=[1],
        first_evening_period=10,
        evening_daily_periods_odd=[1, 0, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 0, 0, 0, 0, 0, 0],
        parity_subject_pairs=[(26, 32)],
        r15_enabled=False,
        max_time_seconds=5,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    placed = [(item.subject_id, item.week_parity, item.weekday) for item in result.items if item.subject_id in {26, 32}]
    assert len(placed) == 2
    assert {item.weekday for item in result.items if item.subject_id in {26, 32}} == {1}
    parities = {item.subject_id: item.week_parity for item in result.items if item.subject_id in {26, 32}}
    assert set(parities.values()) == {WeekParity.odd, WeekParity.even}


def test_evening_cpsat_honors_head_teacher_pin_and_r15_cycle():
    from app.services.scheduling.evening_cpsat import generate_evening_schedule

    result = generate_evening_schedule(
        [
            {
                "id": 1,
                "class_id": 1,
                "subject_id": 10,
                "teacher_id": 7001,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
            {
                "id": 2,
                "class_id": 2,
                "subject_id": 10,
                "teacher_id": 7001,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
        ],
        class_ids=[1, 2],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        activity_subject_id=999,
        required_teacher_by_slot={(6, 9): {1: 7001}},
        r15_exclude_subject_ids={999},
        r15_enabled=True,
        max_time_seconds=5,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    from app.services.scheduling.rules import (
        _sequence_follows_class_cycle,
        _teacher_evening_class_sequence,
    )

    teacher_items = [i for i in result.items if i.teacher_id == 7001 and i.subject_id == 10]
    seq = _teacher_evening_class_sequence(teacher_items, evening_start=9, exclude_subjects={999})
    class_ids = {i.class_id for i in teacher_items}
    assert any(i.class_id == 1 and i.weekday == 6 for i in teacher_items)
    assert class_ids == {1, 2}
    assert _sequence_follows_class_cycle(seq, class_ids)
    assert all(item.subject_id != 999 for item in result.items)


def test_evening_cpsat_pins_teacher_to_named_class_monday():
    from app.services.scheduling.evening_cpsat import generate_evening_schedule

    result = generate_evening_schedule(
        [
            {
                "id": 1,
                "class_id": 10,
                "subject_id": 12,
                "teacher_id": 695,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
            {
                "id": 2,
                "class_id": 7,
                "subject_id": 12,
                "teacher_id": 695,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
        ],
        class_ids=[10, 7],
        first_evening_period=10,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        required_teacher_by_slot={(1, 10): {10: 695}},
        r15_enabled=False,
        max_time_seconds=5,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    monday_class10 = [
        item for item in result.items
        if item.class_id == 10 and item.weekday == 1 and item.period == 10
    ]
    assert monday_class10
    assert all(item.teacher_id == 695 for item in monday_class10)
    class7_days = {item.weekday for item in result.items if item.class_id == 7}
    assert class7_days and 1 not in class7_days


def test_evening_cpsat_r15_allows_weekday_holes():
    from app.services.scheduling.rules import (
        _sequence_follows_class_cycle,
        _teacher_evening_class_sequence,
    )
    from app.services.scheduling.evening_cpsat import generate_evening_schedule

    result = generate_evening_schedule(
        [
            {
                "id": 1,
                "class_id": 1,
                "subject_id": 10,
                "teacher_id": 7001,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
            {
                "id": 2,
                "class_id": 2,
                "subject_id": 10,
                "teacher_id": 7001,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
        ],
        class_ids=[1, 2],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        teacher_forbidden_slots={
            7001: {(2, 9), (4, 9), (5, 9), (6, 9)},
        },
        r15_enabled=True,
        max_time_seconds=5,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    teacher_items = [item for item in result.items if item.teacher_id == 7001]
    days = sorted({item.weekday for item in teacher_items})
    assert days == [1, 3]
    seq = _teacher_evening_class_sequence(teacher_items, evening_start=9, exclude_subjects=set())
    assert _sequence_follows_class_cycle(seq, {1, 2})


def test_evening_cpsat_requires_monday_tuesday_cover_when_other_days_forbidden():
    from app.services.scheduling.evening_cpsat import generate_evening_schedule

    result = generate_evening_schedule(
        [
            {
                "id": 1,
                "class_id": 1,
                "subject_id": 10,
                "teacher_id": 679,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
            {
                "id": 2,
                "class_id": 2,
                "subject_id": 10,
                "teacher_id": 679,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
        ],
        class_ids=[1, 2],
        first_evening_period=10,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        teacher_forbidden_slots={679: {(3, 10), (4, 10), (5, 10), (6, 10)}},
        teacher_required_evening_weekdays={679: {1, 2}},
        r15_enabled=False,
        max_time_seconds=5,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    days = sorted({item.weekday for item in result.items if item.teacher_id == 679})
    classes = {item.class_id for item in result.items if item.teacher_id == 679}
    assert days == [1, 2]
    assert classes == {1, 2}


def test_evening_cpsat_requires_monday_thursday_for_four_flex_halves():
    from app.services.scheduling.evening_cpsat import generate_evening_schedule

    assignments = [
        {
            "id": idx,
            "class_id": cid,
            "subject_id": 25,
            "teacher_id": 716,
            "week_parity": "all",
            "evening_periods_odd": 1,
            "evening_periods_even": 1,
            "evening_parity": "either",
        }
        for idx, cid in enumerate((2, 4, 7, 10), start=1)
    ]
    result = generate_evening_schedule(
        assignments,
        class_ids=[2, 4, 7, 10],
        first_evening_period=10,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        teacher_forbidden_slots={716: {(2, 10), (3, 10), (5, 10), (6, 10)}},
        teacher_required_evening_weekdays={716: {1, 4}},
        r15_enabled=True,
        r15_exclude_teacher_ids={716},
        max_time_seconds=5,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    items = [item for item in result.items if item.teacher_id == 716]
    assert len(items) == 4
    assert {item.weekday for item in items} == {1, 4}
    by_day_parity = {(item.weekday, item.week_parity) for item in items}
    assert by_day_parity == {
        (1, WeekParity.odd), (1, WeekParity.even),
        (4, WeekParity.odd), (4, WeekParity.even),
    }


def test_evening_cpsat_pin_without_subject_quota_is_infeasible():
    from app.services.scheduling.evening_cpsat import generate_evening_schedule

    result = generate_evening_schedule(
        [{
            "id": 1,
            "class_id": 1,
            "subject_id": 10,
            "teacher_id": 1001,
            "week_parity": "all",
            "evening_periods_odd": 1,
            "evening_periods_even": 1,
        }],
        class_ids=[1],
        first_evening_period=9,
        evening_daily_periods_odd=[0, 0, 0, 0, 0, 1, 0],
        evening_daily_periods_even=[0, 0, 0, 0, 0, 1, 0],
        required_teacher_by_slot={(6, 9): {1: 7001}},
        r15_enabled=False,
        max_time_seconds=5,
    )
    assert result.status == "INFEASIBLE"


def test_evening_slot_can_be_reserved_for_the_class_head_teacher():
    with pytest.raises(ValueError, match="晚课 CP-SAT 无解"):
        build_evening_study_items(
            [{
                "id": 103,
                "class_id": 1,
                "subject_id": 10,
                "teacher_id": 1001,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            }],
            class_ids=[1],
            first_evening_period=9,
            evening_daily_periods_odd=[0, 0, 0, 0, 0, 1, 0],
            evening_daily_periods_even=[0, 0, 0, 0, 0, 1, 0],
            required_teacher_by_slot={(6, 9): {1: 7001}},
        )


def test_head_teacher_reserved_slot_consumes_own_subject_evening_quota():
    """班主任晚课与学科晚课是同一角色：保留位落学科，不再另排一节。"""
    items = build_evening_study_items(
        [
            {
                "id": 103,
                "class_id": 1,
                "subject_id": 10,
                "teacher_id": 7001,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
            {
                "id": 104,
                "class_id": 2,
                "subject_id": 10,
                "teacher_id": 7001,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 1,
            },
        ],
        class_ids=[1, 2],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        activity_subject_id=999,
        required_teacher_by_slot={(6, 9): {1: 7001}},
        r15_enabled=True,
    )

    teacher_items = [
        item for item in items
        if item.teacher_id == 7001 and item.subject_id == 10
    ]
    assert any(item.class_id == 1 and item.weekday == 6 and item.week_parity.value == "all" for item in teacher_items)
    class2 = [item for item in teacher_items if item.class_id == 2]
    assert len(class2) == 1 and class2[0].week_parity.value == "all"
    from app.services.scheduling.rules import (
        _sequence_follows_class_cycle,
        _teacher_evening_class_sequence,
    )
    seq = _teacher_evening_class_sequence(teacher_items, evening_start=9, exclude_subjects=set())
    assert _sequence_follows_class_cycle(seq, {item.class_id for item in teacher_items})
    assert not any(
        item.class_id == 1 and item.weekday != 6 and item.teacher_id == 7001
        for item in items
    )


def test_head_teacher_half_evening_pairs_with_parity_partner_on_reserved_slot():
    """班主任每班仅 0.5 晚课：周六位落本科单腿，并对课另一科 0.5 拼同一格。"""
    items = build_evening_study_items(
        [
            {
                "id": 1,
                "class_id": 1,
                "subject_id": 10,  # 物理
                "teacher_id": 7001,
                "week_parity": "all",
                "evening_periods_odd": 1,
                "evening_periods_even": 0,
            },
            {
                "id": 2,
                "class_id": 1,
                "subject_id": 20,  # 历史
                "teacher_id": 8001,
                "week_parity": "all",
                "evening_periods_odd": 0,
                "evening_periods_even": 1,
            },
        ],
        class_ids=[1],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        activity_subject_id=999,
        required_teacher_by_slot={(6, 9): {1: 7001}},
        parity_subject_pairs=[(10, 20)],
    )

    saturday = [
        (item.subject_id, item.teacher_id, item.week_parity.value)
        for item in items
        if item.weekday == 6 and item.period == 9
    ]
    assert sorted(saturday) == [
        (10, 7001, "odd"),
        (20, 8001, "even"),
    ]
    # 额度已在周六消耗，工作日不应再出现这对物理/历史晚课
    assert not any(
        item.weekday != 6 and item.subject_id in {10, 20}
        for item in items
    )


def test_generate_schedule_enforces_one_of_two_class_slot_patterns():
    assignments = [{
        "id": 801,
        "class_id": 10,
        "subject_id": 8,
        "teacher_id": 7001,
        "weekly_periods": 2,
    }]
    patterns = [{
        "rule_id": "R08-02",
        "target_type": "subject",
        "target_ids": [8],
        "alternatives": [
            [
                {"weekdays": [2], "periods": [3, 4], "count": 1},
                {"weekdays": [4], "periods": [6, 7], "count": 1},
            ],
            [
                {"weekdays": [2], "periods": [6, 7], "count": 1},
                {"weekdays": [4], "periods": [3, 4], "count": 1},
            ],
        ],
    }]

    result = generate_schedule(
        assignments,
        days=5,
        periods_per_day=7,
        slot_patterns=patterns,
        strategy_codes=["random_tiebreak"],
        random_seed=4,
    )

    assert result.unplaced == []
    assert {(item.weekday, item.period) for item in result.items} in ({
        (2, 3), (4, 6),
    }, {
        (2, 4), (4, 6),
    }, {
        (2, 3), (4, 7),
    }, {
        (2, 4), (4, 7),
    }, {
        (2, 6), (4, 3),
    }, {
        (2, 6), (4, 4),
    }, {
        (2, 7), (4, 3),
    }, {
        (2, 7), (4, 4),
    })


def test_generate_schedule_preserves_locked_slots_and_fills_remaining_hours():
    result = generate_schedule(
        [{
            "id": 901,
            "class_id": 1,
            "subject_id": 10,
            "teacher_id": 100,
            "weekly_periods": 2,
        }],
        days=2,
        periods_per_day=2,
        locked_items=[{
            "assignment_id": 901,
            "class_id": 1,
            "subject_id": 10,
            "teacher_id": 100,
            "weekday": 1,
            "period": 1,
        }],
    )

    assert len(result.items) == 2
    assert (1, 1) in {(item.weekday, item.period) for item in result.items}
    assert len({(item.class_id, item.weekday, item.period) for item in result.items}) == 2


def test_cross_class_gap_repair_relocates_a_teacher_blocker():
    from app.services.scheduling import ScheduleItem

    items = [
        *[
            ScheduleItem(period=period, weekday=1, class_id=1, teacher_id=period,
                         subject_id=period, assignment_id=period)
            for period in range(1, 6)
        ],
        ScheduleItem(period=7, weekday=1, class_id=1, teacher_id=10,
                     subject_id=7, assignment_id=7),
        ScheduleItem(period=6, weekday=1, class_id=2, teacher_id=10,
                     subject_id=8, assignment_id=8),
    ]

    repaired = repair_class_gaps(items, days=2, periods_per_day=7)

    class_one_monday = sorted(
        item.period for item in repaired if item.class_id == 1 and item.weekday == 1
    )
    assert class_one_monday == [1, 2, 3, 4, 5, 6]
    assert len({(item.class_id, item.weekday, item.period) for item in repaired}) == len(repaired)
    assert len({(item.teacher_id, item.weekday, item.period) for item in repaired}) == len(repaired)


def test_class_gap_repair_leaves_empty_slots_only_after_the_last_lesson():
    from app.services.scheduling import ScheduleItem

    items = [
        ScheduleItem(period=3, weekday=1, class_id=1, teacher_id=10,
                     subject_id=1, assignment_id=1),
        ScheduleItem(period=4, weekday=1, class_id=1, teacher_id=11,
                     subject_id=2, assignment_id=2),
    ]

    repaired = repair_class_gaps(items, days=1, periods_per_day=4)

    assert sorted(item.period for item in repaired) == [1, 2]


def test_compact_class_gaps_moves_a_non_conflicting_lesson_forward():
    from app.services.scheduling import ScheduleItem

    items = [
        ScheduleItem(period=2, weekday=1, class_id=1, teacher_id=10,
                     subject_id=1, assignment_id=1),
        ScheduleItem(period=4, weekday=1, class_id=1, teacher_id=11,
                     subject_id=2, assignment_id=2),
    ]

    compacted = compact_class_gaps(items, days=1, periods_per_day=4)

    assert sorted(item.period for item in compacted) == [1, 2]


def test_generate_schedule_has_no_teacher_or_class_conflicts():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 10, "weekly_periods": 5},
        {"id": 2, "class_id": 1, "subject_id": 2, "teacher_id": 11, "weekly_periods": 4},
        {"id": 3, "class_id": 2, "subject_id": 1, "teacher_id": 10, "weekly_periods": 5},
    ]

    result = generate_schedule(assignments, days=5, periods_per_day=8)

    assert result.unplaced == []
    assert len(result.items) == 14
    class_slots = {(item.class_id, item.weekday, item.period) for item in result.items}
    teacher_slots = {(item.teacher_id, item.weekday, item.period) for item in result.items}
    assert len(class_slots) == len(result.items)
    assert len(teacher_slots) == len(result.items)


def test_validate_schedule_requirements_reports_class_capacity_shortage():
    assignments = [
        {"id": 1, "class_id": 7, "subject_id": 1, "teacher_id": 10, "weekly_periods": 3},
        {"id": 2, "class_id": 7, "subject_id": 2, "teacher_id": 11, "weekly_periods": 2},
    ]

    result = validate_schedule_requirements(assignments, days=1, periods_per_day=4)

    assert result.valid is False
    assert [(issue.code, issue.entity_id, issue.requested, issue.capacity) for issue in result.issues] == [
        ("class_capacity_exceeded", 7, 5, 4),
    ]


def test_activity_teacher_is_not_counted_in_subject_workload_or_class_count():
    result = validate_schedule_requirements(
        [
            {"id": 1, "class_id": 1, "subject_id": 10, "teacher_id": 7, "weekly_periods": 5},
            {
                "id": 2,
                "class_id": 2,
                "subject_id": 20,
                "teacher_id": 7,
                "weekly_periods": 1,
                "counts_toward_teacher_load": False,
            },
        ],
        days=1,
        periods_per_day=8,
        max_teacher_weekly_periods=5,
    )

    assert result.valid is True
    assert not any(item.entity_type == "teacher" for item in result.issues)


def test_subject_capacity_shortage_explains_rule_and_suggests_a_valid_limit():
    assignments = [
        {"id": 1, "class_id": 2, "subject_id": 1, "teacher_id": 10, "weekly_periods": 8},
    ]

    result = validate_schedule_requirements(
        assignments,
        days=5,
        periods_per_day=8,
        max_same_subject_per_day=1,
    )

    issue = result.issues[0]
    assert issue.code == "subject_capacity_exceeded"
    assert issue.rule_code == "max_same_subject_per_day"
    assert issue.formula == "5 个可排教学日 × 每日最多 1 节 = 5 节"
    assert issue.suggestions[0].field == "max_same_subject_per_day"
    assert issue.suggestions[0].recommended_value == 2
    assert issue.suggestions[1].field == "weekly_periods"
    assert issue.suggestions[1].recommended_value == 5
    assert any(rule.code == "max_same_subject_per_day" and rule.result == 5 for rule in result.rules)


def test_capacity_suggestion_does_not_claim_a_daily_limit_can_solve_an_impossible_week():
    assignments = [
        {"id": index, "class_id": 2, "subject_id": index, "teacher_id": index, "weekly_periods": 8}
        for index in range(1, 10)
    ]

    result = validate_schedule_requirements(
        assignments,
        days=5,
        periods_per_day=8,
        max_class_lessons_per_day=7,
        max_same_subject_per_day=1,
    )

    class_issue = next(issue for issue in result.issues if issue.code == "class_capacity_exceeded")
    assert class_issue.suggestions[0].code == "reduce_class_weekly_load"
    assert class_issue.suggestions[0].field == "class_total_weekly_periods"
    assert class_issue.suggestions[0].recommended_value == 40


def test_generate_schedule_repairs_a_single_blocking_lesson():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 3, "teacher_id": 1, "weekly_periods": 2},
        {"id": 2, "class_id": 2, "subject_id": 2, "teacher_id": 3, "weekly_periods": 2},
        {"id": 3, "class_id": 1, "subject_id": 2, "teacher_id": 2, "weekly_periods": 1},
        {"id": 4, "class_id": 2, "subject_id": 1, "teacher_id": 2, "weekly_periods": 2},
    ]

    result = generate_schedule(assignments, days=2, periods_per_day=2)

    assert result.unplaced == []
    assert len(result.items) == 7
    assert len({(item.class_id, item.weekday, item.period) for item in result.items}) == 7
    assert len({(item.teacher_id, item.weekday, item.period) for item in result.items}) == 7


def test_generate_schedule_prioritizes_full_schedule_over_teacher_gap():
    result = generate_schedule(
        [{"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 1, "weekly_periods": 4}],
        days=2,
        periods_per_day=2,
        avoid_consecutive_teacher_lessons=True,
    )

    assert result.unplaced == []
    assert len(result.items) == 4


def test_generate_schedule_accepts_a_registered_strategy_combination():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 10, "weekly_periods": 4},
        {"id": 2, "class_id": 2, "subject_id": 1, "teacher_id": 10, "weekly_periods": 4},
        {"id": 3, "class_id": 1, "subject_id": 2, "teacher_id": 11, "weekly_periods": 3},
    ]

    result = generate_schedule(
        assignments,
        strategy_codes=["class_compact", "teacher_friendly", "daily_balance"],
    )

    assert result.unplaced == []
    assert len(result.items) == 11
    assert len({(item.class_id, item.weekday, item.period) for item in result.items}) == 11
    assert len({(item.teacher_id, item.weekday, item.period) for item in result.items}) == 11


def test_generate_schedule_spreads_same_subject_without_a_daily_cap():
    result = generate_schedule(
        [{"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 1, "weekly_periods": 8}],
        days=5,
        periods_per_day=8,
        strategy_codes=["daily_balance"],
    )

    daily_counts = {
        weekday: sum(item.weekday == weekday for item in result.items)
        for weekday in range(1, 6)
    }
    assert result.unplaced == []
    assert all(count >= 1 for count in daily_counts.values())
    assert max(daily_counts.values()) == 2


def test_generate_schedule_preserves_required_weekly_periods():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 10, "weekly_periods": 6},
        {"id": 2, "class_id": 1, "subject_id": 2, "teacher_id": 11, "weekly_periods": 3},
    ]

    result = generate_schedule(assignments, days=5, periods_per_day=8)

    assert sum(item.assignment_id == 1 for item in result.items) == 6
    assert sum(item.assignment_id == 2 for item in result.items) == 3


def test_generate_schedule_avoids_same_subject_at_same_period_on_consecutive_days():
    assignments = [
        {"id": subject_id, "class_id": 1, "teacher_id": None,
         "subject_id": subject_id, "weekly_periods": 5}
        for subject_id in range(1, 9)
    ]

    result = generate_schedule(assignments, random_seed=20260824)

    for subject_id in range(1, 9):
        periods_by_day = {
            item.weekday: item.period
            for item in result.items
            if item.subject_id == subject_id
        }
        consecutive_repeats = sum(
            periods_by_day.get(day) == periods_by_day.get(day + 1)
            for day in range(1, 5)
        )
        assert consecutive_repeats == 0


def test_generate_schedule_random_tiebreak_is_repeatable_with_the_same_seed():
    assignments = [
        {"id": subject_id, "class_id": 1, "teacher_id": None,
         "subject_id": subject_id, "weekly_periods": 3}
        for subject_id in range(1, 7)
    ]

    first = generate_schedule(assignments, random_seed=11)
    repeated = generate_schedule(assignments, random_seed=11)
    different = generate_schedule(assignments, random_seed=29)
    positions = lambda result: [(item.subject_id, item.weekday, item.period) for item in result.items]

    assert positions(first) == positions(repeated)
    assert positions(first) != positions(different)


def test_generate_schedule_respects_custom_forbidden_slots_and_daily_limit():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 10, "weekly_periods": 5},
        {"id": 2, "class_id": 1, "subject_id": 2, "teacher_id": 11, "weekly_periods": 5},
    ]

    result = generate_schedule(
        assignments,
        days=5,
        periods_per_day=8,
        forbidden_slots={(1, 1), (3, 8)},
        max_class_lessons_per_day=2,
        max_same_subject_per_day=1,
    )

    assert result.unplaced == []
    assert all((item.weekday, item.period) not in {(1, 1), (3, 8)} for item in result.items)
    assert all(sum(entry.class_id == 1 and entry.weekday == day for entry in result.items) <= 2 for day in range(1, 6))
    assert all(
        sum(entry.class_id == 1 and entry.subject_id == subject and entry.weekday == day for entry in result.items) <= 1
        for subject in (1, 2)
        for day in range(1, 6)
    )


def test_generate_schedule_respects_teacher_specific_forbidden_slots():
    result = generate_schedule(
        [{"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 7, "weekly_periods": 6}],
        days=6,
        periods_per_day=8,
        teacher_forbidden_slots={7: {
            (1, 1), (1, 3), (1, 5),
            (2, 1), (2, 5), (2, 7), (2, 8),
            (3, 1), (3, 2), (3, 5),
            (4, 1), (4, 5), (4, 6),
            (5, 1), (5, 2), (5, 5),
            (6, 1), (6, 3), (6, 5),
        }},
    )

    assert result.unplaced == []
    assert all(
        (item.weekday, item.period) not in {
            (1, 1), (1, 3), (1, 5), (2, 1), (2, 5), (2, 7), (2, 8),
            (3, 1), (3, 2), (3, 5), (4, 1), (4, 5), (4, 6),
            (5, 1), (5, 2), (5, 5), (6, 1), (6, 3), (6, 5),
        }
        for item in result.items
    )


def test_generate_schedule_never_puts_teacher_in_forbidden_first_period():
    result = generate_schedule(
        [{"id": 1, "class_id": 1, "subject_id": 5, "teacher_id": 701, "weekly_periods": 5}],
        days=6,
        periods_per_day=7,
        teacher_forbidden_slots={701: {(day, 1) for day in range(1, 7)}},
    )
    assert result.unplaced == []
    assert all(item.period != 1 for item in result.items if item.teacher_id == 701)


def test_generate_schedule_handles_school_scale_without_timing_out():
    periods = [5, 5, 5, 3, 3, 3, 2, 2, 2]
    teacher_pools = [14, 14, 14, 10, 10, 10, 8, 8, 8]
    assignments = [
        {
            "id": (class_id - 1) * 9 + subject_index + 1,
            "class_id": class_id,
            "subject_id": subject_index + 1,
            "teacher_id": subject_index * 100 + (class_id - 1) % teacher_pools[subject_index] + 1,
            "weekly_periods": periods[subject_index],
        }
        for class_id in range(1, 41)
        for subject_index in range(9)
    ]

    started = perf_counter()
    result = generate_schedule(
        assignments,
        max_class_lessons_per_day=7,
        max_teacher_lessons_per_day=6,
        max_same_subject_per_day=1,
    )
    elapsed = perf_counter() - started

    assert len(result.items) == 1200
    assert result.unplaced == []
    assert elapsed < 1.5


def test_expand_schedule_maps_weekday_to_calendar_date():
    result = generate_schedule(
        [{"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 10, "weekly_periods": 2}],
        days=5,
        periods_per_day=8,
    )

    dated = expand_schedule(result.items, date(2026, 8, 24))

    assert all(item.lesson_date == date(2026, 8, 24 + item.weekday - 1) for item in dated)


def test_expand_schedule_requires_monday():
    with pytest.raises(ValueError, match="周一"):
        expand_schedule([], date(2026, 8, 25))


def test_arrange_students_rejects_insufficient_capacity():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    with pytest.raises(ValueError, match="容量"):
        arrange_students(students, rows=2, cols=2, rule="roster")


def test_arrange_students_uses_snake_row_direction():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    seats = arrange_students(students, rows=2, cols=3, rule="snake")

    assert [(seat.row, seat.col, seat.student_id) for seat in seats] == [
        (1, 1, 1), (1, 2, 2), (1, 3, 3),
        (2, 3, 4), (2, 2, 5), (2, 1, 6),
    ]


def test_arrange_students_gender_rule_alternates_when_possible():
    students = [
        {"id": 1, "gender": "male", "roster_order": 1},
        {"id": 2, "gender": "male", "roster_order": 2},
        {"id": 3, "gender": "female", "roster_order": 3},
        {"id": 4, "gender": "female", "roster_order": 4},
    ]

    seats = arrange_students(students, rows=2, cols=2, rule="gender")

    assert [seat.student_id for seat in seats] == [1, 3, 2, 4]


def test_arrange_students_random_rule_is_repeatable_with_seed():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    first = arrange_students(students, rows=2, cols=3, rule="random", seed=2026)
    second = arrange_students(students, rows=2, cols=3, rule="random", seed=2026)

    assert [seat.student_id for seat in first] == [seat.student_id for seat in second]


def test_arrange_students_places_priority_students_in_front():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    seats = arrange_students(students, rows=2, cols=3, rule="roster", front_student_ids={5, 6})

    assert [seat.student_id for seat in seats[:2]] == [5, 6]


def _seat_pos(seats, student_id: int) -> tuple[int, int]:
    seat = next(s for s in seats if s.student_id == student_id)
    return (seat.row, seat.col)


def _are_adjacent(seats, a: int, b: int) -> bool:
    ra, ca = _seat_pos(seats, a)
    rb, cb = _seat_pos(seats, b)
    return max(abs(ra - rb), abs(ca - cb)) == 1


def test_arrange_students_height_pairing_alternates_tall_and_short():
    students = [
        {"id": i, "gender": "male", "roster_order": i, "height_cm": h}
        for i, h in enumerate([160, 180, 165, 178, 170, 172], start=1)
    ]

    seats = arrange_students(students, rows=2, cols=3, order="roster", layout="normal", pairing="height")

    order_of_ids = [seat.student_id for seat in seats]
    # 相邻座位应为“一高一矮”，不允许出现连续递增/递减的高低走势
    heights = {s["id"]: s["height_cm"] for s in students}
    seq = [heights[i] for i in order_of_ids]
    monotonic = all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)) or \
        all(seq[i] >= seq[i + 1] for i in range(len(seq) - 1))
    assert not monotonic


def test_arrange_students_separation_pairs_are_not_adjacent():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    seats = arrange_students(
        students, rows=2, cols=3, order="roster", layout="normal",
        separation_pairs=[[1, 2]],
    )

    assert not _are_adjacent(seats, 1, 2)


def test_arrange_students_adjacency_pairs_are_adjacent():
    students = [{"id": i, "gender": "male", "roster_order": i} for i in range(1, 7)]

    seats = arrange_students(
        students, rows=1, cols=6, order="roster", layout="normal",
        adjacency_pairs=[[1, 3]],
    )

    assert _are_adjacent(seats, 1, 3)


def test_arrange_students_score_rule_orders_descending_with_missing_last():
    students = [
        {"id": 1, "gender": "male", "roster_order": 1, "exam_score": 88.0},
        {"id": 2, "gender": "male", "roster_order": 2, "exam_score": 70.0},
        {"id": 3, "gender": "male", "roster_order": 3, "exam_score": 95.0},
        {"id": 4, "gender": "male", "roster_order": 4},  # 无成绩
    ]

    seats = arrange_students(students, rows=1, cols=4, order="score", layout="normal")

    assert [seat.student_id for seat in seats] == [3, 1, 2, 4]


def test_arrange_students_score_puts_tallest_on_edges():
    students = [
        {"id": 1, "gender": "male", "roster_order": 1, "exam_score": 90.0, "height_cm": 160},
        {"id": 2, "gender": "male", "roster_order": 2, "exam_score": 80.0, "height_cm": 180},
        {"id": 3, "gender": "male", "roster_order": 3, "exam_score": 85.0, "height_cm": 150},
    ]

    seats = arrange_students(students, rows=1, cols=3, order="score", layout="normal")

    col_of = {seat.student_id: seat.col for seat in seats}
    # 同一行三列：个子最高的落侧边，最矮的居中
    assert col_of[2] in (1, 3)
    assert col_of[3] == 2


def test_generate_exam_schedule_skips_weekends():
    papers = [{"id": i, "subject_id": i, "grade_id": 1, "teacher_id": i} for i in range(1, 6)]

    items = generate_exam_schedule(papers, start_date=date(2026, 8, 28))

    assert [item.exam_date.isoformat() for item in items] == [
        "2026-08-28", "2026-08-28", "2026-08-31", "2026-08-31", "2026-09-01",
    ]


def test_generate_exam_schedule_assigns_available_invigilators():
    papers = [
        {"id": 1, "subject_id": 1, "grade_id": 1, "teacher_id": 10},
        {"id": 2, "subject_id": 2, "grade_id": 1, "teacher_id": 11},
    ]

    items = generate_exam_schedule(papers, start_date=date(2026, 8, 24), teacher_ids=[10, 11, 12])

    assert items[0].invigilator_id != 10
    assert items[1].invigilator_id != 11
    assert items[0].session_index != items[1].session_index


def test_generate_exam_schedule_skips_custom_excluded_dates():
    papers = [{"id": i, "subject_id": i, "grade_id": 1, "teacher_id": i} for i in range(1, 5)]

    items = generate_exam_schedule(
        papers,
        start_date=date(2026, 8, 24),
        excluded_dates={date(2026, 8, 25)},
    )

    assert {item.exam_date for item in items} == {date(2026, 8, 24), date(2026, 8, 26)}


def test_312_exam_schedule_uses_three_day_gaokao_template():
    subject_names = {
        1: "语文", 2: "数学", 3: "英语", 4: "物理", 5: "化学",
        6: "生物", 7: "政治", 8: "历史", 9: "地理",
    }
    papers = [
        {"id": subject_id, "subject_id": subject_id, "grade_id": 3, "teacher_id": subject_id}
        for subject_id in subject_names
    ]

    items = generate_exam_schedule(
        papers,
        start_date=date(2026, 6, 7),
        mode="3+1+2",
        subject_names=subject_names,
    )

    by_subject = {subject_names[item.subject_id]: item for item in items}
    assert {item.exam_date for item in items} == {
        date(2026, 6, 8), date(2026, 6, 9), date(2026, 6, 10),
    }
    assert (by_subject["语文"].exam_date, by_subject["语文"].start_time) == (date(2026, 6, 8), "09:00")
    assert (by_subject["数学"].exam_date, by_subject["数学"].start_time) == (date(2026, 6, 8), "15:00")
    assert (by_subject["物理"].exam_date, by_subject["物理"].start_time) == (date(2026, 6, 9), "09:00")
    assert (by_subject["历史"].exam_date, by_subject["历史"].start_time) == (date(2026, 6, 9), "09:00")
    assert (by_subject["英语"].exam_date, by_subject["英语"].start_time) == (date(2026, 6, 9), "15:00")
    assert (by_subject["化学"].exam_date, by_subject["化学"].start_time) == (date(2026, 6, 10), "08:30")
    assert (by_subject["地理"].exam_date, by_subject["地理"].start_time) == (date(2026, 6, 10), "11:00")
    assert (by_subject["政治"].exam_date, by_subject["政治"].start_time) == (date(2026, 6, 10), "14:30")
    assert (by_subject["生物"].exam_date, by_subject["生物"].start_time) == (date(2026, 6, 10), "17:00")


def test_312_exam_schedule_runs_same_subject_for_multiple_grades_in_parallel():
    papers = [
        {"id": 1, "subject_id": 1, "grade_id": 1, "teacher_id": 10},
        {"id": 2, "subject_id": 1, "grade_id": 2, "teacher_id": 11},
        {"id": 3, "subject_id": 2, "grade_id": 1, "teacher_id": 12},
        {"id": 4, "subject_id": 2, "grade_id": 2, "teacher_id": 13},
    ]

    items = generate_exam_schedule(
        papers,
        start_date=date(2026, 6, 8),
        mode="3+1+2",
        subject_names={1: "语文", 2: "数学"},
    )

    chinese = [item for item in items if item.subject_id == 1]
    mathematics = [item for item in items if item.subject_id == 2]
    assert len({(item.exam_date, item.start_time, item.end_time) for item in chinese}) == 1
    assert len({(item.exam_date, item.start_time, item.end_time) for item in mathematics}) == 1
    assert chinese[0].session_index != mathematics[0].session_index


def test_exam_candidate_arrangement_assigns_every_student_to_a_room_and_seat():
    schedules = generate_exam_schedule(
        [
            {"id": 101, "subject_id": 1, "grade_id": 3, "teacher_id": 90},
            {"id": 102, "subject_id": 2, "grade_id": 3, "teacher_id": 91},
        ],
        start_date=date(2026, 6, 8),
        mode="3+1+2",
        subject_names={1: "语文", 2: "数学"},
    )

    result = arrange_exam_candidates(
        schedules,
        candidate_ids_by_course={101: [1, 2, 3, 4, 5], 102: [1, 2, 3, 4, 5]},
        rooms=[ExamRoomResource(name="高三01考场", capacity=3), ExamRoomResource(name="高三02考场", capacity=3)],
        teacher_ids=[10, 11, 12, 13],
        invigilators_per_room=1,
    )

    assert len(result.seats) == 10
    assert len(result.rooms) == 4
    assert {(seat.course_key, seat.student_id) for seat in result.seats} == {
        (paper_id, student_id) for paper_id in (101, 102) for student_id in range(1, 6)
    }
    assert all(1 <= seat.seat_no <= 3 for seat in result.seats)
    assert len({(room.exam_date, room.session_index, room.room_name) for room in result.rooms}) == len(result.rooms)


def test_exam_candidate_arrangement_rejects_room_capacity_shortage():
    schedules = generate_exam_schedule(
        [{"id": 101, "subject_id": 1, "grade_id": 3, "teacher_id": 90}],
        start_date=date(2026, 6, 8),
        mode="3+1+2",
        subject_names={1: "语文"},
    )

    with pytest.raises(ValueError, match="考场容量不足"):
        arrange_exam_candidates(
            schedules,
            candidate_ids_by_course={101: [1, 2, 3, 4, 5]},
            rooms=[ExamRoomResource(name="高三01考场", capacity=4)],
            teacher_ids=[10],
            invigilators_per_room=1,
        )


def test_exam_candidate_arrangement_skips_teacher_on_leave_for_the_slot():
    schedules = generate_exam_schedule(
        [{"id": 101, "subject_id": 1, "grade_id": 3, "teacher_id": 90}],
        start_date=date(2026, 6, 8),
        mode="3+1+2",
        subject_names={1: "语文"},
    )
    slot = (schedules[0].exam_date, schedules[0].session_index)

    result = arrange_exam_candidates(
        schedules,
        candidate_ids_by_course={101: [1]},
        rooms=[ExamRoomResource(name="高三01考场", capacity=40)],
        teacher_ids=[10, 11],
        unavailable_teacher_slots={10: {slot}},
        invigilators_per_room=1,
    )

    assert result.rooms[0].invigilator_ids == (11,)


def test_resolve_312_exam_candidates_uses_grade_roster_and_confirmed_choices():
    papers = [
        {"id": 101, "subject_id": 1, "grade_id": 3},
        {"id": 104, "subject_id": 4, "grade_id": 3},
        {"id": 108, "subject_id": 8, "grade_id": 3},
    ]

    result = resolve_exam_candidates(
        papers,
        student_ids_by_grade={3: [1, 2, 3, 4]},
        selected_subject_ids_by_student={
            1: {4, 5, 6},
            2: {4, 7, 9},
            3: {8, 5, 6},
            4: {8, 7, 9},
        },
        subject_names={1: "语文", 4: "物理", 8: "历史"},
    )

    assert result[101] == [1, 2, 3, 4]
    assert result[104] == [1, 2]
    assert result[108] == [3, 4]


def test_generate_schedule_respects_subject_forbidden_slots():
    assignments = [
        {
            "id": 901,
            "class_id": 10,
            "subject_id": 12,
            "teacher_id": 8001,
            "weekly_periods": 3,
        },
        {
            "id": 902,
            "class_id": 10,
            "subject_id": 27,
            "teacher_id": 8002,
            "weekly_periods": 3,
        },
    ]
    subject_forbidden = {12: {(1, 6), (1, 7), (2, 6), (2, 7), (3, 6), (3, 7), (4, 6), (4, 7), (5, 6), (5, 7)}}

    result = generate_schedule(
        assignments,
        days=5,
        periods_per_day=7,
        subject_forbidden_slots=subject_forbidden,
        strategy_codes=["random_tiebreak"],
        random_seed=4,
    )

    assert result.unplaced == []
    chinese = [item for item in result.items if item.subject_id == 12]
    assert len(chinese) == 3
    assert all(item.period <= 5 for item in chinese)


def test_generate_schedule_teacher_daily_limit_overrides_default_daily_cap():
    assignments = [
        {
            "id": 911 + offset,
            "class_id": 10,
            "subject_id": 12 + offset,
            "teacher_id": 9001,
            "weekly_periods": 2,
        }
        for offset in range(3)
    ]

    result = generate_schedule(
        assignments,
        days=5,
        periods_per_day=8,
        teacher_daily_limits={9001: 2},
        strategy_codes=["random_tiebreak"],
        random_seed=4,
    )

    assert result.unplaced == []
    per_day = [sum(1 for item in result.items if item.weekday == day) for day in range(1, 6)]
    assert max(per_day) <= 2


def test_generate_schedule_respects_class_slot_allowed_subjects():
    assignments = [
        {
            "id": 921,
            "class_id": 10,
            "subject_id": 23,
            "teacher_id": 9101,
            "weekly_periods": 2,
        },
        {
            "id": 922,
            "class_id": 10,
            "subject_id": 27,
            "teacher_id": 9102,
            "weekly_periods": 4,
        },
    ]
    # 班级10 的周一第2节只允许音乐(23)
    allowed = {10: {(1, 2): {23}}}

    result = generate_schedule(
        assignments,
        days=5,
        periods_per_day=8,
        class_slot_allowed_subjects=allowed,
        strategy_codes=["random_tiebreak"],
        random_seed=4,
    )

    assert result.unplaced == []
    english = [item for item in result.items if item.subject_id == 27]
    assert english
    assert all(not (item.weekday == 1 and item.period == 2) for item in english)


def test_evening_builder_aligns_odd_even_paired_subjects_in_the_same_slot():
    # 规则21：物理(26)单周、历史(32)双周，共用同一晚课位
    items = build_evening_study_items(
        [
            {"id": 1, "class_id": 10, "subject_id": 26, "teacher_id": 31,
             "weekly_periods": 6, "evening_periods_odd": 1, "evening_periods_even": 0},
            {"id": 2, "class_id": 10, "subject_id": 32, "teacher_id": 32,
             "weekly_periods": 6, "evening_periods_odd": 0, "evening_periods_even": 1},
        ],
        class_ids=[10],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 0, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 0, 0, 0, 0, 0, 0],
        parity_subject_pairs=[(26, 32)],
    )

    odd = [i for i in items if i.week_parity == WeekParity.odd]
    even = [i for i in items if i.week_parity == WeekParity.even]
    assert [(i.subject_id, i.weekday, i.period) for i in odd] == [(26, 1, 9)]
    assert [(i.subject_id, i.weekday, i.period) for i in even] == [(32, 1, 9)]


def test_evening_builder_fills_all_half_pairs_without_self_study():
    """0.5 晚课排满：物|史强制成对；其余 0.5 任意互配；不落自主学习。"""
    items = build_evening_study_items(
        [
            {"id": 1, "class_id": 10, "subject_id": 12, "teacher_id": 1,
             "evening_periods_odd": 1, "evening_periods_even": 1},
            {"id": 2, "class_id": 10, "subject_id": 27, "teacher_id": 2,
             "evening_periods_odd": 1, "evening_periods_even": 1},
            {"id": 3, "class_id": 10, "subject_id": 29, "teacher_id": 3,
             "evening_periods_odd": 1, "evening_periods_even": 1},
            {"id": 4, "class_id": 10, "subject_id": 26, "teacher_id": 4,
             "evening_periods_odd": 1, "evening_periods_even": 0},
            {"id": 5, "class_id": 10, "subject_id": 32, "teacher_id": 5,
             "evening_periods_odd": 0, "evening_periods_even": 1},
            {"id": 6, "class_id": 10, "subject_id": 28, "teacher_id": 6,
             "evening_periods_odd": 1, "evening_periods_even": 0},
            {"id": 7, "class_id": 10, "subject_id": 31, "teacher_id": 7,
             "evening_periods_odd": 0, "evening_periods_even": 1},
            {"id": 8, "class_id": 10, "subject_id": 33, "teacher_id": 8,
             "evening_periods_odd": 1, "evening_periods_even": 0},
            {"id": 9, "class_id": 10, "subject_id": 25, "teacher_id": 9,
             "evening_periods_odd": 0, "evening_periods_even": 1},
        ],
        class_ids=[10],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        activity_subject_id=99,
        parity_subject_pairs=[(26, 32)],
        required_teacher_by_slot={(6, 9): {10: 3}},
    )

    by_slot: dict[tuple[int, int], dict[str, int]] = {}
    for item in items:
        if item.class_id != 10 or item.period < 9:
            continue
        bucket = by_slot.setdefault((item.weekday, item.period), {})
        if item.week_parity == WeekParity.all:
            bucket["all"] = item.subject_id
        else:
            bucket[item.week_parity.value] = item.subject_id

    assert 99 not in {item.subject_id for item in items if item.period >= 9}
    half_slots = [
        slot for slot, parts in by_slot.items()
        if "odd" in parts and "even" in parts
    ]
    assert len(half_slots) == 3
    pairs = {(by_slot[s]["odd"], by_slot[s]["even"]) for s in half_slots}
    assert (26, 32) in pairs  # 规则强制
    assert {o for o, _ in pairs} == {26, 28, 33}
    assert {e for _, e in pairs} == {32, 31, 25}
    full = [parts["all"] for parts in by_slot.values() if "all" in parts]
    assert sorted(full) == [12, 27, 29]


def test_evening_builder_places_unpaired_halves_on_legal_days():
    """未声明对课的 0.5 各自落位；对不上同一天也不会整对作废。"""
    items = build_evening_study_items(
        [
            {"id": 1, "class_id": 1, "subject_id": 12, "teacher_id": 1,
             "evening_periods_odd": 1, "evening_periods_even": 1},
            {"id": 2, "class_id": 1, "subject_id": 33, "teacher_id": 8,
             "evening_periods_odd": 1, "evening_periods_even": 0},
            {"id": 3, "class_id": 1, "subject_id": 25, "teacher_id": 9,
             "evening_periods_odd": 0, "evening_periods_even": 1},
        ],
        class_ids=[1],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 1, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 1, 1, 0, 0, 0, 0],
        teacher_forbidden_slots={
            8: {(1, 9), (2, 9)},
            9: {(3, 9)},
        },
    )
    bio = [i for i in items if i.subject_id == 33]
    geo = [i for i in items if i.subject_id == 25]
    assert len(bio) == 1 and bio[0].weekday == 3
    assert len(geo) == 1 and geo[0].weekday in {1, 2}


def test_repair_keeps_head_teacher_subject_on_required_slot():
    """班主任保留位：整周同科或单双拼格（如单物双历），不能被挪成空自习。"""
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 12, "teacher_id": 100,
         "evening_periods_odd": 1, "evening_periods_even": 1},
        {"id": 2, "class_id": 1, "subject_id": 26, "teacher_id": 200,
         "evening_periods_odd": 1, "evening_periods_even": 0},
        {"id": 3, "class_id": 1, "subject_id": 32, "teacher_id": 201,
         "evening_periods_odd": 0, "evening_periods_even": 1},
    ]
    # 周六被自习占住；修补后应落回班主任语文（整周）。
    items = [
        ScheduleItem(0, 1, 99, None, 6, 9, week_parity=WeekParity.odd),
        ScheduleItem(0, 1, 99, None, 6, 9, week_parity=WeekParity.even),
        ScheduleItem(1, 1, 12, 100, 1, 9, week_parity=WeekParity.all),
    ]
    repaired = repair_evening_hard_constraints(
        items,
        assignments=assignments,
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        parity_subject_pairs=[(26, 32)],
        free_evening_days={},
        required_teacher_by_slot={(6, 9): {1: 100}},
        teacher_forbidden_slots={},
        activity_subject_id=99,
        anchor_items=[],
        teacher_evening_daytime_links=[],
    )
    sat = [i for i in repaired if i.class_id == 1 and i.weekday == 6 and i.period == 9]
    assert any(i.teacher_id == 100 for i in sat)
    assert any(i.subject_id == 12 for i in sat)


def test_repair_displaces_full_evening_to_seat_half_pair():
    """对课缺位时，可把同班整周晚课挪开以落生|地。"""
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 12, "teacher_id": 1,
         "evening_periods_odd": 1, "evening_periods_even": 1},
        {"id": 2, "class_id": 1, "subject_id": 33, "teacher_id": 8,
         "evening_periods_odd": 1, "evening_periods_even": 0},
        {"id": 3, "class_id": 1, "subject_id": 25, "teacher_id": 9,
         "evening_periods_odd": 0, "evening_periods_even": 1},
    ]
    items = [
        ScheduleItem(1, 1, 12, 1, 1, 9, week_parity=WeekParity.all),
        ScheduleItem(0, 1, 99, None, 2, 9, week_parity=WeekParity.all),
    ]
    repaired = repair_evening_hard_constraints(
        items,
        assignments=assignments,
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 1, 0, 0, 0, 0, 0],
        parity_subject_pairs=[],
        free_evening_days={},
        required_teacher_by_slot={},
        teacher_forbidden_slots={},
        activity_subject_id=99,
        anchor_items=[],
        teacher_evening_daytime_links=[],
    )
    bio = [i for i in repaired if i.subject_id == 33]
    geo = [i for i in repaired if i.subject_id == 25]
    assert len(bio) == 1 and len(geo) == 1
    assert bio[0].weekday == geo[0].weekday
    chinese = [i for i in repaired if i.subject_id == 12]
    assert len(chinese) == 1


def test_forbidden_conflict_moves_instead_of_replacing_with_self_study():
    """禁排冲突只挪位：空位可以自习，学科课时不能改成自习。"""
    assignments = [
        {
            "id": 1, "class_id": 1, "subject_id": 25, "teacher_id": 717,
            "evening_periods_odd": 0, "evening_periods_even": 1,
        },
        {
            "id": 2, "class_id": 2, "subject_id": 10, "teacher_id": 800,
            "evening_periods_odd": 1, "evening_periods_even": 1,
        },
    ]
    forbidden = {(weekday, 9) for weekday in (1, 3, 4, 5, 6)}
    items = build_evening_study_items(
        assignments,
        class_ids=[1, 2],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 0, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 0, 0],
        activity_subject_id=99,
        teacher_forbidden_slots={717: forbidden},
    )
    repaired = repair_evening_hard_constraints(
        items,
        assignments=assignments,
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 0, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 0, 0],
        parity_subject_pairs=[],
        free_evening_days={},
        required_teacher_by_slot={},
        teacher_forbidden_slots={717: forbidden},
        activity_subject_id=99,
        anchor_items=[],
        teacher_evening_daytime_links=[],
    )
    geo = [item for item in repaired if item.subject_id == 25]
    assert len(geo) == 1
    assert geo[0].weekday == 2
    assert geo[0].teacher_id == 717
    assert not any(
        item.subject_id == 99 and item.class_id == 1 and item.week_parity in {WeekParity.even, WeekParity.all}
        for item in repaired
        if item.weekday == geo[0].weekday
    )


def _repair_kwargs(**extra):
    base = dict(
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 1, 0, 0, 0, 0, 0],
        parity_subject_pairs=[(26, 32)],
        free_evening_days={},
        required_teacher_by_slot={},
        teacher_forbidden_slots={},
        activity_subject_id=99,
        anchor_items=[],
        teacher_evening_daytime_links=[],
        self_study_candidates=None,
    )
    base.update(extra)
    return base


def test_repair_moves_complete_pair_onto_self_study_when_slot_is_legal():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 26, "teacher_id": 100, "evening_periods_odd": 1, "evening_periods_even": 0},
        {"id": 2, "class_id": 1, "subject_id": 32, "teacher_id": 200, "evening_periods_odd": 0, "evening_periods_even": 1},
        {"id": 3, "class_id": 2, "subject_id": 26, "teacher_id": 100, "evening_periods_odd": 1, "evening_periods_even": 0},
        {"id": 4, "class_id": 2, "subject_id": 32, "teacher_id": 201, "evening_periods_odd": 0, "evening_periods_even": 1},
    ]
    items = [
        ScheduleItem(1, 1, 26, 100, 1, 9, week_parity=WeekParity.odd),
        ScheduleItem(2, 1, 32, 200, 1, 9, week_parity=WeekParity.even),
        ScheduleItem(0, 1, 99, None, 2, 9, week_parity=WeekParity.all),
        ScheduleItem(0, 2, 99, None, 1, 9, week_parity=WeekParity.all),
        ScheduleItem(9, 2, 12, 300, 2, 9, week_parity=WeekParity.all),
    ]
    repaired = repair_evening_hard_constraints(items, assignments=assignments, **_repair_kwargs())
    def legs(class_id, subject_id):
        return [item for item in repaired if item.class_id == class_id and item.subject_id == subject_id and item.period >= 9]
    assert len(legs(1, 26)) == 1 and len(legs(1, 32)) == 1
    assert len(legs(2, 26)) == 1 and len(legs(2, 32)) == 1
    assert legs(1, 26)[0].weekday == legs(1, 32)[0].weekday
    assert legs(2, 26)[0].weekday == legs(2, 32)[0].weekday


def test_repair_can_swap_class_self_study_onto_candidate_origin_only():
    """班级自习日只能调到候选日上的当前课位；非候选日不能占自习日。"""
    assignments = [
        {"id": 1, "class_id": 10, "subject_id": 26, "teacher_id": 100, "evening_periods_odd": 1, "evening_periods_even": 0},
        {"id": 2, "class_id": 10, "subject_id": 32, "teacher_id": 200, "evening_periods_odd": 0, "evening_periods_even": 1},
    ]
    # 物史错位在周三/周四；周五自习。候选日 3/4/5，可整组落到周五并把自习调回候选日。
    items = [
        ScheduleItem(1, 10, 26, 100, 3, 9, week_parity=WeekParity.odd),
        ScheduleItem(2, 10, 32, 200, 4, 9, week_parity=WeekParity.even),
        ScheduleItem(0, 10, 99, None, 5, 9, week_parity=WeekParity.all),
        ScheduleItem(9, 10, 12, 300, 1, 9, week_parity=WeekParity.all),
        ScheduleItem(8, 10, 12, 301, 2, 9, week_parity=WeekParity.all),
    ]
    repaired = repair_evening_hard_constraints(
        items,
        assignments=assignments,
        **_repair_kwargs(
            evening_daily_periods_odd=[1, 1, 1, 1, 1, 0, 0],
            evening_daily_periods_even=[1, 1, 1, 1, 1, 0, 0],
            free_evening_days={10: {5}},
            self_study_candidates={10: {3, 4, 5}},
        ),
    )
    phys = [i for i in repaired if i.subject_id == 26 and i.class_id == 10]
    hist = [i for i in repaired if i.subject_id == 32 and i.class_id == 10]
    assert len(phys) == 1 and len(hist) == 1
    assert phys[0].weekday == hist[0].weekday
    assert phys[0].weekday in {3, 4, 5}


def test_repair_does_not_steal_hours_when_no_legal_move():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 26, "teacher_id": 100, "evening_periods_odd": 1, "evening_periods_even": 0},
        {"id": 2, "class_id": 1, "subject_id": 32, "teacher_id": 200, "evening_periods_odd": 0, "evening_periods_even": 1},
        {"id": 3, "class_id": 2, "subject_id": 26, "teacher_id": 100, "evening_periods_odd": 1, "evening_periods_even": 0},
        {"id": 4, "class_id": 2, "subject_id": 32, "teacher_id": 201, "evening_periods_odd": 0, "evening_periods_even": 1},
    ]
    items = [
        ScheduleItem(1, 1, 26, 100, 1, 9, week_parity=WeekParity.odd),
        ScheduleItem(2, 1, 32, 200, 1, 9, week_parity=WeekParity.even),
        ScheduleItem(8, 1, 12, 400, 2, 9, week_parity=WeekParity.all),
        ScheduleItem(0, 2, 99, None, 1, 9, week_parity=WeekParity.all),
        ScheduleItem(9, 2, 12, 300, 2, 9, week_parity=WeekParity.all),
    ]
    repaired = repair_evening_hard_constraints(
        items,
        assignments=assignments,
        **_repair_kwargs(teacher_forbidden_slots={400: {(1, 9)}, 200: {(2, 9)}}),
    )
    class1_phys = [item for item in repaired if item.class_id == 1 and item.subject_id == 26]
    class1_hist = [item for item in repaired if item.class_id == 1 and item.subject_id == 32]
    assert len(class1_phys) == 1 and len(class1_hist) == 1
    assert class1_phys[0].weekday == 1
    assert class1_hist[0].weekday == 1
