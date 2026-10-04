import pytest

from app.services.academic.gaokao import (
    SubjectChoice,
    SubjectChoicePolicy,
    form_teaching_classes,
    generate_walk_schedule,
    get_subject_choice_strategy,
    resolve_selection_phase,
    validate_scheme_configuration,
    validate_subject_choice,
)


def test_312_scheme_requires_three_required_two_primary_and_four_secondary_subjects():
    validate_scheme_configuration("3+1+2", [1, 2, 3], [4, 8], [5, 6, 7, 9])
    with pytest.raises(ValueError, match="4 门再选"):
        validate_scheme_configuration("3+1+2", [1, 2, 3], [4, 8], [5, 6, 7])


def test_scheme_subject_pools_cannot_overlap():
    with pytest.raises(ValueError, match="不能重复"):
        validate_scheme_configuration("3+1+2", [1, 2, 3], [4, 8], [5, 6, 7, 3])


def test_validate_312_choice_accepts_one_primary_and_two_distinct_secondary_subjects():
    validate_subject_choice(
        primary_subject_id=4,
        secondary_subject_ids=[5, 6],
        primary_pool={4, 8},
        secondary_pool={5, 6, 7, 9},
    )


def test_validate_312_choice_rejects_duplicate_or_out_of_pool_subjects():
    with pytest.raises(ValueError, match="再选科目"):
        validate_subject_choice(4, [5, 5], primary_pool={4, 8}, secondary_pool={5, 6, 7, 9})
    with pytest.raises(ValueError, match="首选科目"):
        validate_subject_choice(5, [6, 7], primary_pool={4, 8}, secondary_pool={5, 6, 7, 9})


def test_312_strategy_exposes_selected_subjects_for_walk_class_generation():
    strategy = get_subject_choice_strategy("3+1+2")
    policy = SubjectChoicePolicy(primary_subject_ids={4, 8}, secondary_subject_ids={5, 6, 7, 9})
    choice = SubjectChoice(primary_subject_id=4, secondary_subject_ids=(5, 7))

    strategy.validate(choice, policy)

    assert strategy.selected_subject_ids(choice, policy) == (4, 5, 7)
    assert strategy.combination_key(choice, policy) == "4-5-7"


def test_312_teaching_classes_default_to_secondary_subjects_only():
    strategy = get_subject_choice_strategy("3+1+2")
    policy = SubjectChoicePolicy(primary_subject_ids={4, 8}, secondary_subject_ids={5, 6, 7, 9})
    choice = SubjectChoice(primary_subject_id=4, secondary_subject_ids=(5, 7))

    assert strategy.teaching_class_subject_ids(choice, policy) == (5, 7)


def test_312_primary_subject_can_be_configured_for_walk_classes():
    strategy = get_subject_choice_strategy("3+1+2")
    policy = SubjectChoicePolicy(
        primary_subject_ids={4, 8},
        secondary_subject_ids={5, 6, 7, 9},
        primary_delivery_mode="teaching_class",
    )
    choice = SubjectChoice(primary_subject_id=4, secondary_subject_ids=(5, 7))

    assert strategy.teaching_class_subject_ids(choice, policy) == (4, 5, 7)
    assert strategy.teaching_class_subject_pool(policy) == frozenset({4, 5, 6, 7, 8, 9})


def test_312_admin_primary_mode_excludes_only_secondary_pool_from_admin_scheduling():
    strategy = get_subject_choice_strategy("3+1+2")
    policy = SubjectChoicePolicy(primary_subject_ids={4, 8}, secondary_subject_ids={5, 6, 7, 9})

    assert strategy.teaching_class_subject_pool(policy) == frozenset({5, 6, 7, 9})


def test_33_strategy_accepts_three_distinct_electives_without_primary_subject():
    strategy = get_subject_choice_strategy("3+3")
    policy = SubjectChoicePolicy(elective_subject_ids={4, 5, 6, 7, 8, 9}, elective_count=3)
    choice = SubjectChoice(selected_subject_ids=(4, 6, 8))

    strategy.validate(choice, policy)

    assert strategy.selected_subject_ids(choice, policy) == (4, 6, 8)
    with pytest.raises(ValueError, match="3 门不同科目"):
        strategy.validate(SubjectChoice(selected_subject_ids=(4, 4, 8)), policy)


def test_traditional_strategy_resolves_stream_subjects_from_policy():
    strategy = get_subject_choice_strategy("traditional")
    policy = SubjectChoicePolicy(stream_subject_ids={"文科": (8, 7, 9), "理科": (4, 5, 6)})
    choice = SubjectChoice(stream="理科")

    strategy.validate(choice, policy)

    assert strategy.selected_subject_ids(choice, policy) == (4, 5, 6)
    assert strategy.combination_key(choice, policy) == "理科"


def test_unknown_subject_choice_strategy_is_rejected():
    with pytest.raises(ValueError, match="不支持的高考模式"):
        get_subject_choice_strategy("custom")


@pytest.mark.parametrize(
    ("grade_level", "term", "code", "can_generate_classes", "can_generate_schedule"),
    [
        (1, "1", "exploration", False, False),
        (1, "2", "intention", True, False),
        (2, "1", "effective", True, True),
        (3, "2", "effective", True, True),
    ],
)
def test_312_selection_phase_controls_when_walk_classes_take_effect(
    grade_level, term, code, can_generate_classes, can_generate_schedule,
):
    phase = resolve_selection_phase(grade_level, term)

    assert phase.code == code
    assert phase.can_generate_teaching_classes is can_generate_classes
    assert phase.can_generate_schedule is can_generate_schedule


def test_form_teaching_classes_covers_each_selected_subject_without_exceeding_capacity():
    choices = [
        {"student_id": 1, "subject_ids": [4, 5, 6]},
        {"student_id": 2, "subject_ids": [4, 5, 7]},
        {"student_id": 3, "subject_ids": [8, 6, 7]},
        {"student_id": 4, "subject_ids": [8, 6, 9]},
        {"student_id": 5, "subject_ids": [4, 5, 6]},
    ]

    groups = form_teaching_classes(choices, capacity=2)

    assert all(len(group.student_ids) <= 2 for group in groups)
    memberships = {(student_id, group.subject_id) for group in groups for student_id in group.student_ids}
    assert memberships == {
        (choice["student_id"], subject_id)
        for choice in choices
        for subject_id in choice["subject_ids"]
    }


def test_generate_walk_schedule_prevents_shared_student_and_teacher_conflicts():
    tasks = [
        {"id": 1, "teacher_id": 10, "student_ids": [1, 2], "weekly_periods": 2},
        {"id": 2, "teacher_id": 11, "student_ids": [2, 3], "weekly_periods": 2},
        {"id": 3, "teacher_id": 10, "student_ids": [4, 5], "weekly_periods": 2},
    ]

    result = generate_walk_schedule(tasks, days=2, periods_per_day=3)

    assert result.unplaced == []
    for left_index, left in enumerate(result.items):
        for right in result.items[left_index + 1:]:
            if (left.weekday, left.period) != (right.weekday, right.period):
                continue
            assert left.teacher_id != right.teacher_id
            assert set(left.student_ids).isdisjoint(right.student_ids)


def test_generate_walk_schedule_prevents_shared_room_conflicts():
    tasks = [
        {"id": 1, "teacher_id": 10, "room_key": "A101", "student_ids": [1], "weekly_periods": 2},
        {"id": 2, "teacher_id": 11, "room_key": "A101", "student_ids": [2], "weekly_periods": 2},
    ]

    result = generate_walk_schedule(tasks, days=1, periods_per_day=4)

    assert result.unplaced == []
    slots = {(item.weekday, item.period) for item in result.items}
    assert len(slots) == len(result.items)
