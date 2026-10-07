import pytest
from app.services.scheduling.walk_regroup_calendar import trial_calendar, audit_draft


def test_hour_bounds_allow_more_than_minimum_and_read_dynamic_capacity():
    from app.services.scheduling.walk_regroup_calendar import check_hour_bounds
    slots = {(d, p) for d in range(1, 7) for p in range(1, 10)}
    required = {(d, p) for d in range(1, 7) for p in range(1, 8)}
    assert check_hour_bounds(44, 37, 7, slots, required) is None
    assert '少2节' in check_hour_bounds(40, 33, 7, slots, required)
    assert '上限54节' in check_hour_bounds(55, 48, 7, slots, required)
    assert '周末' in check_hour_bounds(44, 38, 6, slots, required)
    seven_days = slots | {(7, p) for p in range(1, 10)}
    assert check_hour_bounds(55, 41, 14, seven_days, required) is None


def test_joint_can_place_extra_hours_outside_required_prefix_and_audit_them():
    draft = {'classes': [
        {'id': 1, 'subject_id': 10, 'phase': ('A', 0), 'size': 1, 'weekday_periods': 1, 'weekend_periods': 0},
        {'id': 2, 'subject_id': 20, 'phase': ('B', 0), 'size': 1, 'weekday_periods': 1, 'weekend_periods': 0}],
        'members': [(1, 1), (2, 1)]}
    assignments = [dict(id=4, class_id=100, subject_id=30, teacher_id=3, room='home',
                        weekly_periods=1, weekday_periods=1, saturday_periods=0, counts_toward_teacher_load=True)]
    slots = [(1, p) for p in range(1, 5)]
    required = {(1, 1), (1, 2)}
    result = trial_calendar(draft, assignments, [100], {100: 0}, {100: 0},
        {10: {1}, 20: {2}}, 2, set(), slots=slots, required_slots=required, phase_hours=1)
    assert result['status'] in ('FEASIBLE', 'OPTIMAL')
    report, placements = audit_draft(draft, result, {1: {10, 20}}, {1: 100}, assignments,
        [{'id': 1, 'capacity': 45}, {'id': 2, 'capacity': 45}], set(),
        slots=slots, required_slots=required, phase_hours=1)
    assert len(placements) + len(result['public']) == 3
    assert report['student_conflicts'] == report['student_gaps_1_7'] == 0
    # Removing the prefix requirement in a saved candidate must not fool the audit.
    result['public'][0]['period'] = 4
    result['phase_slots'] = {str(('A', 0)): [(1, 2)], str(('B', 0)): [(1, 3)]}
    with pytest.raises(AssertionError, match='Student gap'):
        audit_draft(draft, result, {1: {10, 20}}, {1: 100}, assignments,
            [{'id': 1, 'capacity': 45}], set(), slots=slots, required_slots=required, phase_hours=1)
