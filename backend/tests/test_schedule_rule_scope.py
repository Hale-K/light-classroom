import pytest

from app.services.scheduling.core import ScheduleItem
from app.services.scheduling.rules import (
    RuleGroupDocument, evaluate_rule_group, generation_global_forbidden_slots,
    rules_for_schedule,
)


def group():
    return RuleGroupDocument(
        id="test", name="高一下学期", academic_year="2026-2027", term="2", grade_id=12,
        rules=[dict(id=scope, title=scope, code="slot_forbidden", priority="hard",
                    schedule_scope=scope, target=dict(type="global"), weekdays=[2], periods=[5])
               for scope in ("all", "admin", "walk")],
    )


def test_admin_and_walk_rules_are_selected_without_changing_stored_catalog():
    original = group()
    assert [r.id for r in rules_for_schedule(original, "admin").rules] == ["all", "admin"]
    assert [r.id for r in rules_for_schedule(original, "walk").rules] == ["all", "walk"]
    assert len(original.rules) == 3
    assert original.term == "2"


def test_reserving_walk_slots_forbids_admin_but_not_walk_generation():
    reservation = group().model_copy(update={"rules": [group().rules[1]]})
    assert generation_global_forbidden_slots(rules_for_schedule(reservation, "admin")) == {(2, 5)}
    assert generation_global_forbidden_slots(rules_for_schedule(reservation, "walk")) == set()


@pytest.mark.parametrize("mode, expected", [("admin", ["all", "admin"]), ("walk", ["all", "walk"])])
def test_validation_uses_the_same_scope_as_generation(mode, expected):
    row = ScheduleItem(assignment_id=1, class_id=1, subject_id=1, teacher_id=1, weekday=2, period=5)
    summary = evaluate_rule_group(group(), [row], schedule_mode=mode)
    assert [r.rule_id for r in summary.results] == expected
    assert all(r.status == "fail" for r in summary.results)


def test_legacy_rules_keep_their_existing_all_schedule_semantics():
    old = group().rules[0].model_dump(exclude={"schedule_scope"})
    parsed = type(group().rules[0]).model_validate(old)
    assert parsed.schedule_scope == "all"


def test_walk_only_rules_do_not_reject_existing_admin_lessons():
    admin = ScheduleItem(assignment_id=1, class_id=1, subject_id=1, teacher_id=1, weekday=2, period=5)
    walk = ScheduleItem(assignment_id=-2, class_id=-2, subject_id=2, teacher_id=2, weekday=2, period=6)
    results = evaluate_rule_group(group(), [walk], schedule_mode="walk", shared_items=[admin]).results
    assert [(r.rule_id, r.status) for r in results] == [("all", "fail"), ("walk", "pass")]


def test_rule_scope_rejects_misspellings_instead_of_silently_ignoring_them():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        type(group().rules[0]).model_validate({**group().rules[0].model_dump(), "schedule_scope": "administrative"})


def test_reservation_is_consumed_by_the_existing_admin_and_walk_solvers():
    from app.services.scheduling.core import generate_schedule
    from app.services.scheduling.walk_recommendation import recommend_walk_slots

    reservation = group().model_copy(update={"rules": [group().rules[1]]})
    admin_result = generate_schedule(
        [dict(id=1, class_id=1, subject_id=1, teacher_id=1, weekly_periods=1)],
        days=2, periods_per_day=5,
        forbidden_slots=generation_global_forbidden_slots(rules_for_schedule(reservation, "admin")),
    )
    assert not admin_result.unplaced
    assert all((r.weekday, r.period) != (2, 5) for r in admin_result.items)
    walk_result = recommend_walk_slots(
        classes=[dict(id=2, name="walk", subject_id=2, teacher_id=2, weekly_periods=1)],
        members=[(2, 100)], rooms=[dict(id=1, name="room", capacity=40)], slots=[(2, 5)],
        blocked_slots=generation_global_forbidden_slots(rules_for_schedule(reservation, "walk")),
    )
    assert walk_result["status"] == "feasible"
    assert len(walk_result["placements"]) == 1
