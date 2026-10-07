from collections import defaultdict
import pytest

from app.services.scheduling.walk_regroup import regroup_walk_students


def test_regroup_preserves_choices_and_separates_the_two_courses():
    choices = {1: {10, 20}, 2: {10, 30}, 3: {20, 30}}
    result = regroup_walk_students(choices, {1: 100, 2: 100, 3: 100},
        {100: 0}, {100: 0}, {0: 10}, capacity=3)
    assert result['status'] == 'feasible'
    classes = {c['id']: c for c in result['classes']}
    actual = defaultdict(set)
    phases = defaultdict(set)
    for cid, sid in result['members']:
        actual[sid].add(classes[cid]['subject_id'])
        phases[sid].add(classes[cid]['phase'])
    assert dict(actual) == choices
    assert all(len(p) == 2 for p in phases.values())


def test_regroup_rejects_capacity_shortage_without_partial_memberships():
    result = regroup_walk_students({1: {10, 20}, 2: {10, 20}},
        {1: 100, 2: 100}, {100: 0}, {100: 0}, {0: 10}, capacity=1)
    assert result['status'] == 'infeasible'
    assert not result.get('members')


@pytest.mark.parametrize('choices,capacity', [({1: {10}}, 3), ({1: {10, 20}}, 0)])
def test_regroup_rejects_invalid_inputs(choices, capacity):
    with pytest.raises(ValueError):
        regroup_walk_students(choices, {1: 100}, {100: 0}, {100: 0},
                              {0: 10}, capacity=capacity)


def _complete_calendar():
    draft = {'classes': [
        {'id': 1, 'subject_id': 10, 'phase': ('A', 0), 'size': 1},
        {'id': 2, 'subject_id': 20, 'phase': ('B', 0), 'size': 1}],
        'members': [(1, 1), (2, 1)]}
    walk_slots = {('A', 0): [(1, p) for p in range(1, 5)],
                  ('B', 0): [(2, p) for p in range(1, 5)]}
    calendar = {'phase_slots': {str(k): v for k, v in walk_slots.items()},
                'teachers': {1: 2, 2: 3}, 'public': []}
    reserved = {s for slots in walk_slots.values() for s in slots}
    calendar['public'] = [dict(id=4, teacher_id=1, class_id=100, room='home',
        weekday=d, period=p) for d in range(1, 7) for p in range(1, 8)
        if (d, p) not in reserved]
    return draft, calendar


def test_independent_audit_accepts_full_merged_timetable():
    from app.services.scheduling.walk_regroup_calendar import audit_draft
    draft, calendar = _complete_calendar()
    report, placements = audit_draft(draft, calendar, {1: {10, 20}}, {1: 100},
        [{'id': 4, 'weekly_periods': 34}], [{'id': 1, 'capacity': 45}], set())
    assert report['student_gaps_1_7'] == 0
    assert len(placements) == 8


def test_calendar_reads_required_periods_and_walk_hours_from_configuration():
    from app.services.scheduling.walk_regroup_calendar import trial_calendar
    draft = {'classes': [
        {'id': 1, 'subject_id': 10, 'phase': ('A', 0), 'size': 1},
        {'id': 2, 'subject_id': 20, 'phase': ('B', 0), 'size': 1}]}
    result = trial_calendar(draft, [], [100], {100: 0}, {100: 0},
        {10: {1}, 20: {2}}, 2, set(), slots=[(6, 1), (6, 2)],
        phase_hours=1, saturday_hours={'A': 1, 'B': 1}, subject_allowed={})
    assert result['status'] in ('FEASIBLE', 'OPTIMAL')
    assert len(result['phase_slots'][str(('A', 0))]) == 1
    assert len(result['phase_slots'][str(('B', 0))]) == 1


@pytest.mark.parametrize('corruption', ['student_choice', 'teacher', 'external_teacher', 'hours', 'room'])
def test_independent_audit_rejects_corrupted_candidate(corruption):
    from app.services.scheduling.walk_regroup_calendar import audit_draft
    draft, calendar = _complete_calendar()
    external = set()
    rooms = [{'id': 1, 'capacity': 45}]
    if corruption == 'student_choice':
        draft['classes'][0]['subject_id'] = 99
    elif corruption == 'teacher':
        calendar['teachers'][1] = 1
        calendar['public'][0].update(weekday=1, period=1)
    elif corruption == 'external_teacher':
        external.add((2, (1, 1)))
    elif corruption == 'hours':
        calendar['public'].pop()
    elif corruption == 'room':
        rooms[0]['capacity'] = 0
    with pytest.raises(AssertionError):
        audit_draft(draft, calendar, {1: {10, 20}}, {1: 100},
            [{'id': 4, 'weekly_periods': 34}], rooms, external)
