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


def test_regroup_honors_configured_class_counts_and_allows_capacity_overflow():
    choices = {sid: {10, 20} for sid in range(1, 48)}
    result = regroup_walk_students(choices, {sid: 100 for sid in choices},
        {100: 0}, {100: 0}, {0: 10}, capacity=47,
        class_counts={10: 1, 20: 1})
    assert result['status'] == 'feasible'
    assert {subject: sum(c['subject_id'] == subject for c in result['classes'])
            for subject in (10, 20)} == {10: 1, 20: 1}
    assert sorted(c['size'] for c in result['classes']) == [47, 47]


@pytest.mark.parametrize('choices,capacity', [({1: {10}}, 3), ({1: {10, 20}}, 0)])
def test_regroup_rejects_invalid_inputs(choices, capacity):
    with pytest.raises(ValueError):
        regroup_walk_students(choices, {1: 100}, {100: 0}, {100: 0},
                              {0: 10}, capacity=capacity)


@pytest.mark.parametrize('teachers,expected', [([501, 501, 501, 502], {501: 60, 502: 40}),
                                            ([501, 501, 502, 502], {501: 50, 502: 50})])
def test_regroup_balances_teacher_student_load_without_reassigning_teachers(teachers, expected):
    choices, admins = {}, {}
    for admin, size in enumerate([10, 20, 30, 40], 100):
        for _ in range(size):
            sid = len(choices) + 1
            choices[sid] = {10, 20}
            admins[sid] = admin
    groups = {admin: admin - 100 for admin in set(admins.values())}
    configured = [{'id': subject * 100 + i, 'subject_id': subject, 'teacher_id': teacher}
                  for subject in [10, 20] for i, teacher in enumerate(teachers)]
    result = regroup_walk_students(choices, admins, groups, groups,
        {g: 10 for g in groups.values()}, capacity=50, class_counts={10: 4, 20: 4},
        configured_classes=configured)
    assert result['status'] == 'feasible'
    shells = {c['id']: c for c in configured}
    for subject in [10, 20]:
        totals = defaultdict(int)
        for c in result['classes']:
            if c['subject_id'] == subject:
                shell = shells[c['configured_class_id']]
                assert shell['subject_id'] == subject
                totals[shell['teacher_id']] += c['size']
        assert dict(totals) == expected
    assert {c['configured_class_id'] for c in result['classes']} == set(shells)


def test_regroup_adjusts_students_to_balance_unequal_teacher_class_counts():
    choices = {sid: {10, 20} for sid in range(1, 71)}
    admins = {sid: 100 if sid <= 35 else 101 for sid in choices}
    configured = [{'id': subject * 100 + i, 'subject_id': subject, 'teacher_id': teacher}
                  for subject in [10, 20] for i, teacher in enumerate([501, 501, 502])]
    result = regroup_walk_students(choices, admins, {100: 0, 101: 1}, {100: 0, 101: 1},
        {0: 30, 1: 30}, capacity=50, class_counts={10: 3, 20: 3}, configured_classes=configured)
    assert result['status'] == 'feasible'
    shells = {c['id']: c for c in configured}
    for subject in [10, 20]:
        totals = defaultdict(int)
        for c in result['classes']:
            if c['subject_id'] == subject:
                totals[shells[c['configured_class_id']]['teacher_id']] += c['size']
        assert dict(totals) == {501: 35, 502: 35}
    actual = defaultdict(set)
    classes = {c['id']: c for c in result['classes']}
    for cid, sid in result['members']:
        actual[sid].add(classes[cid]['subject_id'])
    assert dict(actual) == choices


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
    result = trial_calendar(draft, [], [], {}, {},
        {10: {1}, 20: {2}}, 2, set(), slots=[(6, 1), (6, 2)],
        phase_hours=1, saturday_hours={'A': 1, 'B': 1}, subject_allowed={})
    assert result['status'] in ('FEASIBLE', 'OPTIMAL')
    assert len(result['phase_slots'][str(('A', 0))]) == 1
    assert len(result['phase_slots'][str(('B', 0))]) == 1


def test_calendar_cannot_reassign_a_configured_walk_class_teacher():
    from app.services.scheduling.walk_regroup_calendar import trial_calendar
    draft = {'classes': [
        {'id': 1, 'subject_id': 10, 'phase': ('A', 0), 'size': 1},
    ]}
    result = trial_calendar(draft, [], [], {}, {},
        {10: {501, 502}}, 1, set(), slots=[(6, 1)], phase_hours=1,
        saturday_hours={'A': 1, 'B': 0}, fixed_teachers={1: 502})
    assert result['status'] in ('FEASIBLE', 'OPTIMAL')
    assert result['teachers'] == {1: 502}


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
