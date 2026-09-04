from app.services.academic.rollover import (
    build_rollover_plan,
    next_grade_level,
    promoted_class_name,
)


def test_rollover_advances_academic_year_and_cohort():
    plan = build_rollover_plan(2026)
    assert plan.target_entry_year == 2027
    assert plan.source_academic_year == "2026-2027"
    assert plan.target_academic_year == "2027-2028"


def test_rollover_promotes_only_current_students():
    assert next_grade_level(1) == 2
    assert next_grade_level(2) == 3
    assert next_grade_level(3) is None
    assert promoted_class_name("崇仁一中 · 高一（1）班", 1) == "崇仁一中 · 高二（1）班"
