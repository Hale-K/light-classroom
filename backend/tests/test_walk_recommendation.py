from collections import Counter, defaultdict
from app.services.scheduling.walk_recommendation import recommend_walk_slots


def classes(teachers=(10, 11)):
    return [dict(id=i+1, name=f'class{i+1}', subject_id=i+1, teacher_id=t, weekly_periods=2) for i, t in enumerate(teachers)]


def test_recommendation_fulfils_every_student_hour_and_no_collision():
    members = [(1, 100), (1, 101), (2, 100), (2, 102)]
    rooms = [dict(id=1, name='room1', capacity=2), dict(id=2, name='room2', capacity=2)]
    result = recommend_walk_slots(classes(), members, rooms, [(d, p) for d in (1, 2) for p in (1, 2, 3)], time_limit=2)
    assert result['status'] == 'feasible'
    assert result['recommended_count'] == 4  # Enough rooms do not remove a shared student's conflicts.
    assert Counter(p['teaching_class_id'] for p in result['placements']) == {1: 2, 2: 2}
    by_student = defaultdict(list)
    for p in result['placements']:
        for cid, sid in members:
            if cid == p['teaching_class_id']: by_student[sid].append((p['weekday'], p['period']))
    assert len(by_student[100]) == 4
    assert all(len(set(slots)) == len(slots) for slots in by_student.values())
    assert len(set((p['weekday'], p['period'], p['room_id']) for p in result['placements'])) == 4


def test_teacher_and_room_capacity_and_existing_occupancy_are_hard_constraints():
    members = [(1, 100), (1, 101), (2, 102), (2, 103)]
    rooms = [dict(id=1, name='room1', capacity=2), dict(id=2, name='room2', capacity=1)]
    slots = [(d, p) for d in (1, 2, 3) for p in (1, 2)]
    result = recommend_walk_slots(classes((10, 10)), members, rooms, slots,
        blocked_students={100: {(1, 1)}}, blocked_teachers={10: {(2, 1)}}, blocked_rooms={1: {(3, 1)}}, time_limit=2)
    assert result['status'] == 'feasible'
    assert not any(p['weekday'] == 2 and p['period'] == 1 for p in result['placements'])
    assert not any(p['weekday'] == 3 and p['period'] == 1 for p in result['placements'])
    assert not any(p['teaching_class_id'] == 1 and p['weekday'] == 1 and p['period'] == 1 for p in result['placements'])
    result = recommend_walk_slots(classes((10, 10)), members, rooms, slots,
        blocked_teachers={10: {(1, 1), (2, 1)}}, blocked_rooms={1: {(3, 1)}}, time_limit=2)
    assert result['status'] == 'infeasible'  # Only three usable periods for a four-period teacher load.
    result = recommend_walk_slots(classes(), members, [dict(id=1, name='small', capacity=1)], slots, time_limit=2)
    assert result['status'] == 'infeasible'


def test_unassigned_teacher_and_empty_roster_block_recommendation():
    assert recommend_walk_slots(classes((None, 11)), [(1, 100), (2, 101)],
        [dict(id=1, name='room', capacity=10)], [(1, 1)])['status'] == 'blocked'
    assert recommend_walk_slots(classes(), [(1, 100)],
        [dict(id=1, name='room', capacity=10)], [(1, 1)])['status'] == 'blocked'


def test_hard_rule_slots_are_excluded_from_the_recommendation():
    members = [(1, 100), (1, 101), (2, 102), (2, 103)]
    rooms = [dict(id=1, name='room1', capacity=2), dict(id=2, name='room2', capacity=2)]
    slots = [(d, p) for d in (1, 2, 3) for p in (1, 2)]
    result = recommend_walk_slots(classes(), members, rooms, slots,
        blocked_slots={(1, 1)}, blocked_subjects={1: {(1, 2)}}, time_limit=2)
    assert result['status'] == 'feasible'
    assert not any((p['weekday'], p['period']) in {(1, 1), (1, 2)} for p in result['placements']
                   if p['teaching_class_id'] == 1)


def test_cohorts_share_one_reserved_window_when_resources_allow():
    members = [(1, 100), (1, 101), (2, 102), (2, 103)]
    rooms = [dict(id=1, name='room1', capacity=2), dict(id=2, name='room2', capacity=2)]
    cohorts = [dict(id=i, name=f'class{i}', subject_id=1, teacher_id=9 + i, weekly_periods=1) for i in (1, 2)]
    result = recommend_walk_slots(cohorts, members, rooms, [(1, 1), (1, 2)], time_limit=2)
    assert result['status'] == 'feasible'
    # 新目标函数优先少占课位窗口：两个教学班并入同一窗口，不再为降并发错峰铺开
    assert result['peak_concurrent_classes'] == 2
    assert len({(p['weekday'], p['period']) for p in result['placements']}) == 1
