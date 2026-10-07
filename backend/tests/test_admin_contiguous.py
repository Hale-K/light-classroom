from app.models.enums import WeekParity
from app.services.scheduling.core import ScheduleItem
from app.services.scheduling.rules import RuleDefinition, RuleGroupDocument, evaluate_rule_group
from app.services.scheduling.cpsat import solve_daytime_cpsat


def rule_group():
    return RuleGroupDocument(id='g', name='g', academic_year='2026-2027', term='2', rules=[
        RuleDefinition(id='admin-prefix', title='行政课连续（末尾可空）', code='class_gap_free',
            priority='hard', schedule_scope='admin', target={'type': 'global'},
            weekdays=[1], periods=[1, 2, 7, 8, 9], params={'trailing_empty': True})])


def lesson(period, parity=WeekParity.all):
    return ScheduleItem(assignment_id=1, class_id=1, subject_id=1, teacher_id=1, weekday=1,
        period=period, week_parity=parity)


def test_admin_prefix_skips_reserved_slots_and_allows_only_trailing_blanks():
    group = rule_group()
    assert evaluate_rule_group(group, [lesson(p) for p in [1, 2, 7, 8]], schedule_mode='admin').valid
    assert not evaluate_rule_group(group, [lesson(p) for p in [1, 7, 8]], schedule_mode='admin').valid
    assert not evaluate_rule_group(group, [lesson(p) for p in [2, 7]], schedule_mode='admin').valid
    assert not evaluate_rule_group(group, [lesson(1), lesson(2, WeekParity.odd), lesson(7)], schedule_mode='admin').valid


def test_solver_enforces_prefix_even_when_earlier_slot_has_no_candidates():
    from app.services.scheduling.rules import generation_class_prefix_groups
    opts = dict(days=1, periods_per_day=9, forbidden_slots={(1, p) for p in [3, 4, 5, 6]},
        class_prefix_groups=generation_class_prefix_groups(rule_group()),
        max_time_seconds=2, polish_seconds=0)
    assignments = [dict(id=s, class_id=1, subject_id=s, teacher_id=1, weekly_periods=1) for s in [1, 2, 3]]
    result = solve_daytime_cpsat(assignments, **opts)
    assert result.status in {'OPTIMAL', 'FEASIBLE'}
    assert sorted(item.period for item in result.items) == [1, 2, 7]
    blocked = solve_daytime_cpsat(assignments, teacher_forbidden_slots={1: {(1, 2)}}, **opts)
    assert blocked.status == 'INFEASIBLE'


def test_prefix_rule_is_not_compiled_as_legacy_full_day_rule():
    from app.services.scheduling.rules import generation_class_gap_free_weekdays
    assert generation_class_gap_free_weekdays(rule_group()) == []
