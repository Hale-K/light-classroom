import pytest

from app.api.v1.scheduling import CourseHourIn, _apply_course_hour_plans, _sort_course_hour_plans, _sort_subjects
from app.models.org import CourseHourPlan, Subject, TeachingAssignment


def test_half_period_must_choose_odd_or_even_week():
    with pytest.raises(ValueError, match="0.5"):
        CourseHourIn(
            class_id=1,
            subject_id=2,
            academic_year="2026-2027",
            term="1",
            weekly_periods=0.5,
            week_parity="all",
        )


def test_full_period_defaults_to_every_week():
    item = CourseHourIn(
        class_id=1,
        subject_id=2,
        academic_year="2026-2027",
        term="1",
        weekly_periods=5,
    )

    assert item.week_parity == "all"


def test_course_hours_keep_weekday_and_saturday_dimensions_and_derive_total():
    item = CourseHourIn(
        class_id=1,
        subject_id=2,
        academic_year="2026-2027",
        term="1",
        weekday_periods=3,
        saturday_periods=1,
    )

    assert item.weekday_periods == 3
    assert item.saturday_periods == 1
    assert item.weekly_periods == 4


def test_zero_course_hours_are_allowed_for_unassigned_subjects():
    item = CourseHourIn(
        class_id=1,
        subject_id=2,
        academic_year="2026-2027",
        term="1",
        weekly_periods=0,
        weekday_periods=0,
        saturday_periods=0,
        evening_periods_odd=0,
        evening_periods_even=0,
    )

    assert item.weekday_periods == 0
    assert item.saturday_periods == 0
    assert item.weekly_periods == 0

    plan = CourseHourPlan(
        tenant_id=1,
        class_id=1,
        subject_id=2,
        academic_year="2026-2027",
        term="1",
        weekday_periods=0,
        saturday_periods=0,
        weekly_periods=0,
    )

    assert plan.weekly_periods == 0


def test_course_hours_can_configure_evening_subject_load_for_each_week():
    item = CourseHourIn(
        class_id=1,
        subject_id=2,
        academic_year="2026-2027",
        term="1",
        weekday_periods=5,
        saturday_periods=1,
        evening_periods_odd=1,
        evening_periods_even=0,
    )

    assert item.evening_periods_odd == 1
    assert item.evening_periods_even == 0
    assert item.evening_parity == "odd"


def test_course_hours_unspecified_evening_parity_keeps_both_flags():
    item = CourseHourIn(
        class_id=1,
        subject_id=4,
        academic_year="2026-2027",
        term="1",
        weekday_periods=3,
        saturday_periods=1,
        evening_periods_odd=1,
        evening_periods_even=1,
        evening_parity="either",
    )

    assert item.evening_parity == "either"
    assert item.week_parity == "all"


def test_course_hour_plan_overrides_assignment_snapshot_and_keeps_teacher():
    assignment = TeachingAssignment(
        id=10,
        tenant_id=1,
        class_id=2,
        subject_id=3,
        teacher_id=4,
        academic_year="2026-2027",
        term="1",
        weekly_periods=4,
    )
    plans = [
        CourseHourPlan(
            id=20,
            tenant_id=1,
            class_id=2,
            subject_id=3,
            academic_year="2026-2027",
            term="1",
            weekly_periods=0.5,
            week_parity="odd",
        ),
        CourseHourPlan(
            id=21,
            tenant_id=1,
            class_id=2,
            subject_id=3,
            academic_year="2026-2027",
            term="1",
            weekly_periods=0.5,
            week_parity="even",
        ),
    ]

    payloads = _apply_course_hour_plans([assignment], plans)

    assert [(item["weekly_periods"], item["week_parity"]) for item in payloads] == [
        (0.5, "even"),
        (0.5, "odd"),
    ]
    assert {item["teacher_id"] for item in payloads} == {4}


def test_subjects_use_curriculum_order():
    subjects = [
        Subject(id=4, tenant_id=7, name="物理"),
        Subject(id=1, tenant_id=7, name="语文"),
        Subject(id=12, tenant_id=7, name="美术"),
        Subject(id=11, tenant_id=7, name="体育"),
        Subject(id=2, tenant_id=7, name="数学"),
    ]

    assert [item.name for item in _sort_subjects(subjects)] == ["语文", "数学", "物理", "体育", "美术"]


def test_course_hour_plans_use_curriculum_subject_order():
    subjects = [
        Subject(id=4, tenant_id=7, name="物理"),
        Subject(id=1, tenant_id=7, name="语文"),
        Subject(id=12, tenant_id=7, name="美术"),
        Subject(id=11, tenant_id=7, name="体育"),
        Subject(id=2, tenant_id=7, name="数学"),
    ]
    plans = [
        CourseHourPlan(id=101, tenant_id=7, class_id=1, subject_id=12, academic_year="2026-2027", term="1", weekly_periods=0.5, week_parity="even"),
        CourseHourPlan(id=102, tenant_id=7, class_id=1, subject_id=4, academic_year="2026-2027", term="1", weekly_periods=3, week_parity="all"),
        CourseHourPlan(id=103, tenant_id=7, class_id=1, subject_id=1, academic_year="2026-2027", term="1", weekly_periods=5, week_parity="all"),
        CourseHourPlan(id=104, tenant_id=7, class_id=1, subject_id=11, academic_year="2026-2027", term="1", weekly_periods=2, week_parity="all"),
        CourseHourPlan(id=105, tenant_id=7, class_id=1, subject_id=2, academic_year="2026-2027", term="1", weekly_periods=6, week_parity="all"),
    ]

    ordered = _sort_course_hour_plans(plans, subjects)

    assert [item.subject_id for item in ordered] == [1, 2, 4, 11, 12]
