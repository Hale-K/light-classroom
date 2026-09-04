from app.models.enums import WeekParity
from app.api.v1.scheduling import GenerateIn, SchedulingGridConfigIn, SubjectIn, _grid_forbidden_slots
from app.models.org import Subject
from datetime import date

from app.services.scheduling import (
    ScheduleItem,
    build_evening_study_items,
    expand_schedule,
    generate_schedule,
    occupancy_keys,
    parity_conflicts,
    validate_schedule_requirements,
)


def test_week_parity_uses_the_three_supported_values():
    assert {item.value for item in WeekParity} == {"all", "odd", "even"}


def test_odd_and_even_can_share_a_slot_but_all_conflicts_with_each():
    assert parity_conflicts(WeekParity.odd, WeekParity.even) is False
    assert parity_conflicts(WeekParity.all, WeekParity.odd) is True
    assert parity_conflicts(WeekParity.even, WeekParity.even) is True


def test_all_parity_occupies_both_week_legs():
    assert occupancy_keys(7, 2, 3, WeekParity.all) == [(7, 2, 3, "odd"), (7, 2, 3, "even")]
    assert occupancy_keys(7, 2, 3, WeekParity.odd) == [(7, 2, 3, "odd")]


def test_calendar_expansion_only_returns_the_matching_parity():
    items = [
        ScheduleItem(1, 1, 1, 1, 1, 1, "", WeekParity.all),
        ScheduleItem(2, 1, 2, 2, 1, 2, "", WeekParity.odd),
        ScheduleItem(3, 1, 3, 3, 1, 3, "", WeekParity.even),
    ]

    first_week = expand_schedule(items, date(2026, 8, 31))
    second_week = expand_schedule(items, date(2026, 9, 7), term_start_monday=date(2026, 8, 31))

    assert [item.assignment_id for item in first_week] == [1, 2]
    assert [item.assignment_id for item in second_week] == [1, 3]


def test_generator_places_two_half_periods_in_the_same_slot_on_opposite_weeks():
    result = generate_schedule([
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 11, "weekly_periods": 0.5},
        {"id": 2, "class_id": 1, "subject_id": 2, "teacher_id": 12, "weekly_periods": 0.5},
    ], days=5, periods_per_day=1)

    assert not result.unplaced
    assert {(item.weekday, item.period) for item in result.items} == {(1, 1)}
    assert {item.week_parity for item in result.items} == {WeekParity.odd, WeekParity.even}


def test_generator_keeps_saturday_half_periods_on_saturday():
    result = generate_schedule([
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 11,
         "weekday_periods": 1, "saturday_periods": 0.5, "weekly_periods": 1.5},
        {"id": 2, "class_id": 1, "subject_id": 2, "teacher_id": 12,
         "weekday_periods": 1, "saturday_periods": 0.5, "weekly_periods": 1.5},
    ], days=6, periods_per_day=1)

    saturday_halves = [item for item in result.items if item.weekday == 6]
    assert len(saturday_halves) == 2
    assert {(item.weekday, item.period) for item in saturday_halves} == {(6, 1)}
    assert {item.week_parity for item in saturday_halves} == {WeekParity.odd, WeekParity.even}


def test_generator_respects_explicit_parity_from_course_hour_plan():
    result = generate_schedule([
        {"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 11, "weekly_periods": 0.5, "week_parity": "even"},
        {"id": 2, "class_id": 1, "subject_id": 2, "teacher_id": 12, "weekly_periods": 0.5, "week_parity": "odd"},
    ], days=5, periods_per_day=1)

    assert not result.unplaced
    assert {(item.weekday, item.period) for item in result.items} == {(1, 1)}
    assert {item.week_parity for item in result.items} == {WeekParity.odd, WeekParity.even}
    assert {item.subject_id: item.week_parity for item in result.items} == {
        1: WeekParity.even,
        2: WeekParity.odd,
    }


def test_week_grid_turns_shorter_days_into_forbidden_slots():
    config = SchedulingGridConfigIn(
        academic_year="2026-2027", term="1",
        daily_periods=[8, 8, 7, 8, 8, 7, 0],
        enable_evening=True, evening_start_period=9,
    )

    assert config.days == 6
    assert config.periods_per_day == 8
    assert (3, 8) in _grid_forbidden_slots(config.model_dump())
    assert (6, 8) in _grid_forbidden_slots(config.model_dump())


def test_week_grid_persists_evening_rule_dimensions():
    config = SchedulingGridConfigIn(
        academic_year="2026-2027",
        term="1",
        daily_periods=[8, 8, 8, 8, 8, 7, 0],
        enable_evening=True,
        evening_start_period=9,
        evening_daily_periods_odd=[1, 0, 1, 0, 1, 0, 0],
        evening_daily_periods_even=[0, 1, 0, 1, 0, 0, 0],
        evening_subject_ids=[1, 2, 3],
    )

    assert config.evening_daily_periods_odd == [1, 0, 1, 0, 1, 0, 0]
    assert config.evening_daily_periods_even == [0, 1, 0, 1, 0, 0, 0]
    assert config.evening_subject_ids == [1, 2, 3]


def test_subject_defaults_to_not_allowed_for_evening_study():
    assert Subject.model_fields["evening_study_allowed"].default is False


def test_subject_input_can_mark_main_subject_for_evening_study():
    assert SubjectIn(name="数学", evening_study_allowed=True).evening_study_allowed is True


def test_generate_rules_keep_saturday_limits_separate_from_weekday_limits():
    rules = GenerateIn(
        academic_year="2026-2027",
        days=6,
        periods_per_day=7,
        max_class_lessons_per_day=6,
        max_teacher_lessons_per_day=6,
        max_class_lessons_on_saturday=7,
        max_teacher_lessons_on_saturday=7,
    )

    assert rules.max_class_lessons_per_day == 6
    assert rules.max_class_lessons_on_saturday == 7
    assert rules.max_teacher_lessons_on_saturday == 7


def test_generate_rules_accept_preview_and_locked_grid_cells():
    rules = GenerateIn(
        academic_year="2026-2027",
        preview=True,
        locked_items=[{
            "assignment_id": 1,
            "class_id": 10,
            "subject_id": 8,
            "teacher_id": 100,
            "weekday": 2,
            "period": 3,
        }],
    )

    assert rules.preview is True
    assert rules.locked_items[0].weekday == 2
    assert rules.locked_items[0].period == 3


def test_generate_rules_expose_the_pe_teacher_daily_limit():
    rules = GenerateIn(
        academic_year="2026-2027",
        max_pe_teacher_lessons_per_day=4,
    )

    assert rules.max_pe_teacher_lessons_per_day == 4


def test_generate_rules_carry_evening_subjects_in_the_rule_payload():
    rules = GenerateIn(
        academic_year="2026-2027",
        evening_start_period=9,
        evening_daily_periods_odd=[1, 0, 1, 0, 1, 0, 0],
        evening_daily_periods_even=[0, 1, 0, 1, 0, 0, 0],
        evening_subject_ids=[1, 2, 3],
    )

    assert rules.evening_start_period == 9
    assert rules.evening_daily_periods_odd == [1, 0, 1, 0, 1, 0, 0]
    assert rules.evening_daily_periods_even == [0, 1, 0, 1, 0, 0, 0]
    assert rules.evening_subject_ids == [1, 2, 3]


def test_generate_rules_normalize_subjects_for_each_evening_week():
    rules = GenerateIn(
        academic_year="2026-2027",
        evening_start_period=9,
        evening_daily_periods_odd=[1, 0, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 0, 0, 0, 0, 0, 0],
        evening_subject_ids_odd=[101],
        evening_subject_ids_even=[202],
    )

    assert rules.evening_subject_ids_odd == [101]
    assert rules.evening_subject_ids_even == [202]
    assert rules.evening_subject_ids == [101, 202]


def test_validation_counts_five_six_period_weekdays_plus_seven_period_saturday():
    result = validate_schedule_requirements(
        [{"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 11, "weekly_periods": 37}],
        days=6,
        periods_per_day=7,
        forbidden_slots={(weekday, 7) for weekday in range(1, 6)},
        max_class_lessons_per_day=6,
        max_teacher_lessons_per_day=6,
        max_class_lessons_on_saturday=7,
        max_teacher_lessons_on_saturday=7,
    )

    assert result.valid is True
    assert result.available_slots == 37
    assert next(rule for rule in result.rules if rule.code == "max_class_lessons_per_day").result == 37


def test_validation_applies_the_saturday_class_limit_only_to_saturday():
    result = validate_schedule_requirements(
        [{"id": 1, "class_id": 1, "subject_id": 1, "teacher_id": 11, "weekly_periods": 37}],
        days=6,
        periods_per_day=7,
        forbidden_slots={(weekday, 7) for weekday in range(1, 6)},
        max_class_lessons_per_day=6,
        max_teacher_lessons_per_day=6,
        max_class_lessons_on_saturday=6,
        max_teacher_lessons_on_saturday=7,
    )

    issue = next(issue for issue in result.issues if issue.code == "class_capacity_exceeded")
    assert issue.capacity == 36


def test_evening_study_adds_only_allowed_main_subjects_without_teacher_load():
    assignments = [
        {"id": 1, "class_id": 1, "subject_id": 101, "teacher_id": 11, "weekly_periods": 6},
        {"id": 2, "class_id": 1, "subject_id": 202, "teacher_id": 22, "weekly_periods": 2},
    ]

    items = build_evening_study_items(
        assignments,
        class_ids=[1],
        allowed_subject_ids={101},
        first_evening_period=7,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 0, 0],
        evening_daily_periods_even=[0, 0, 0, 0, 0, 0, 0],
    )

    assert len(items) == 5
    assert {item.subject_id for item in items} == {101}
    assert {item.period for item in items} == {7}
    assert {item.week_parity for item in items} == {WeekParity.odd}
    assert all(item.teacher_id is None for item in items)


def test_validation_counts_half_periods_as_alternating_week_load():
    result = validate_schedule_requirements([
        {"id": 1, "class_id": 1, "subject_id": 101, "teacher_id": 11, "weekly_periods": 0.5},
        {"id": 2, "class_id": 1, "subject_id": 202, "teacher_id": 22, "weekly_periods": 0.5},
    ], days=5, periods_per_day=6)

    assert result.requested_lessons == 1


def test_evening_study_uses_explicit_odd_and_even_week_profiles():
    items = build_evening_study_items(
        [{"id": 1, "class_id": 1, "subject_id": 101, "teacher_id": 11, "weekly_periods": 6}],
        class_ids=[1],
        allowed_subject_ids={101},
        first_evening_period=9,
        evening_daily_periods_odd=[1, 0, 2, 0, 0, 0, 0],
        evening_daily_periods_even=[0, 1, 0, 1, 0, 0, 0],
    )

    assert len(items) == 5
    assert [(item.weekday, item.period, item.week_parity) for item in items] == [
        (1, 9, WeekParity.odd),
        (3, 9, WeekParity.odd),
        (3, 10, WeekParity.odd),
        (2, 9, WeekParity.even),
        (4, 9, WeekParity.even),
    ]


def test_evening_study_uses_the_subjects_selected_for_each_week_parity():
    items = build_evening_study_items(
        [
            {"id": 1, "class_id": 1, "subject_id": 101, "teacher_id": 11, "weekly_periods": 6},
            {"id": 2, "class_id": 1, "subject_id": 202, "teacher_id": 22, "weekly_periods": 6},
        ],
        class_ids=[1],
        allowed_subject_ids_odd={101},
        allowed_subject_ids_even={202},
        first_evening_period=9,
        evening_daily_periods_odd=[1, 0, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 0, 0, 0, 0, 0, 0],
    )

    assert [(item.subject_id, item.week_parity) for item in items] == [
        (101, WeekParity.odd),
        (202, WeekParity.even),
    ]


def test_evening_builder_merges_same_assignment_odd_even_into_one_weekly_slot():
    items = build_evening_study_items(
        [
            {"id": 1, "class_id": 1, "subject_id": 101, "teacher_id": 11,
             "weekly_periods": 6, "evening_periods_odd": 1, "evening_periods_even": 1},
        ],
        class_ids=[1],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 0, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 0, 0, 0, 0, 0, 0],
    )

    assert [(item.subject_id, item.teacher_id, item.weekday, item.period, item.week_parity) for item in items] == [
        (101, 11, 1, 9, WeekParity.all),
    ]


def test_evening_study_can_use_subject_pools_per_class_and_week():
    items = build_evening_study_items(
        [
            {"id": 1, "class_id": 1, "subject_id": 101, "teacher_id": 11, "weekly_periods": 6},
            {"id": 2, "class_id": 1, "subject_id": 202, "teacher_id": 22, "weekly_periods": 6},
            {"id": 3, "class_id": 2, "subject_id": 303, "teacher_id": 33, "weekly_periods": 6},
        ],
        class_ids=[1, 2],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 0, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 0, 0, 0, 0, 0, 0],
        allowed_subject_ids_by_class_odd={1: {101}, 2: {303}},
        allowed_subject_ids_by_class_even={1: {202}, 2: {303}},
    )

    assert {(item.class_id, item.subject_id, item.week_parity) for item in items} == {
        (1, 101, WeekParity.odd),
        (1, 202, WeekParity.even),
        (2, 303, WeekParity.odd),
        (2, 303, WeekParity.even),
    }


def test_evening_study_can_be_a_standalone_activity_without_subject_or_teacher():
    items = build_evening_study_items(
        [],
        class_ids=[1],
        activity_subject_id=999,
        first_evening_period=9,
        evening_daily_periods_odd=[1, 0, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[0, 1, 0, 0, 0, 0, 0],
    )

    assert items == []


def test_evening_study_respects_teacher_forbidden_slots():
    items = build_evening_study_items(
        [
            {"id": 1, "class_id": 1, "subject_id": 101, "teacher_id": 11,
             "weekly_periods": 6, "evening_periods_odd": 1, "evening_periods_even": 0},
            {"id": 2, "class_id": 1, "subject_id": 202, "teacher_id": 22,
             "weekly_periods": 6, "evening_periods_odd": 1, "evening_periods_even": 0},
        ],
        class_ids=[1],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[0, 0, 0, 0, 0, 0, 0],
        teacher_forbidden_slots={11: {(1, 9)}},
    )

    placed = {(item.subject_id, item.weekday, item.period) for item in items}
    assert (101, 2, 9) in placed
    assert (101, 1, 9) not in placed
    assert (202, 1, 9) in placed


def test_evening_builder_aligns_explicit_parity_pairs_despite_asymmetric_loads():
    # 复现真实漂移：语文单双周都在，音乐挂单周，心理挂双周，物理单周/历史双周配对
    items = build_evening_study_items(
        [
            {"id": 1, "class_id": 1, "subject_id": 12, "teacher_id": 41,
             "weekly_periods": 6, "evening_periods_odd": 1, "evening_periods_even": 1},
            {"id": 2, "class_id": 1, "subject_id": 23, "teacher_id": 42,
             "weekly_periods": 3, "evening_periods_odd": 1, "evening_periods_even": 0},
            {"id": 3, "class_id": 1, "subject_id": 24, "teacher_id": 43,
             "weekly_periods": 3, "evening_periods_odd": 0, "evening_periods_even": 1},
            {"id": 4, "class_id": 1, "subject_id": 26, "teacher_id": 44,
             "weekly_periods": 6, "evening_periods_odd": 1, "evening_periods_even": 0},
            {"id": 5, "class_id": 1, "subject_id": 32, "teacher_id": 45,
             "weekly_periods": 6, "evening_periods_odd": 0, "evening_periods_even": 1},
        ],
        class_ids=[1],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 1, 1, 1, 1, 1, 0],
        evening_daily_periods_even=[1, 1, 1, 1, 1, 1, 0],
        parity_subject_pairs=[(26, 32)],
    )
    phy_odd = [(i.weekday, i.period) for i in items if i.subject_id == 26 and i.week_parity == WeekParity.odd]
    his_even = [(i.weekday, i.period) for i in items if i.subject_id == 32 and i.week_parity == WeekParity.even]
    assert phy_odd == his_even
    assert len(phy_odd) == 1

    # 每周各科目只出现一次，无重复落位
    from collections import Counter
    counter = Counter((i.subject_id, i.week_parity) for i in items)
    assert all(count == 1 for count in counter.values())


def test_evening_builder_pairing_is_direction_agnostic():
    # 课时方案若反向配置（物理双周、历史单周），同样应同位对齐
    items = build_evening_study_items(
        [
            {"id": 1, "class_id": 1, "subject_id": 26, "teacher_id": 31,
             "weekly_periods": 6, "evening_periods_odd": 0, "evening_periods_even": 1},
            {"id": 2, "class_id": 1, "subject_id": 32, "teacher_id": 32,
             "weekly_periods": 6, "evening_periods_odd": 1, "evening_periods_even": 0},
        ],
        class_ids=[1],
        first_evening_period=9,
        evening_daily_periods_odd=[1, 0, 0, 0, 0, 0, 0],
        evening_daily_periods_even=[1, 0, 0, 0, 0, 0, 0],
        parity_subject_pairs=[(26, 32)],
    )
    slots = {(i.subject_id, i.week_parity, i.weekday, i.period) for i in items}
    phys_even = [(s[2], s[3]) for s in slots if s[0] == 26 and s[1] == WeekParity.even]
    hist_odd = [(s[2], s[3]) for s in slots if s[0] == 32 and s[1] == WeekParity.odd]
    assert phys_even == hist_odd and phys_even
