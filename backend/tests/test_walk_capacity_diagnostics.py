from app.services.scheduling.walk_recommendation import recommend_walk_slots


def test_weekend_shortage_names_class_and_shortfall():
    result = recommend_walk_slots(
        [dict(id=1, name='化学走班01', teacher_id=1, weekly_periods=5,
              weekday_periods=4, weekend_periods=1)],
        [(1, 10)], [dict(id=1, name='教室', capacity=45)],
        [(1, p) for p in range(1, 6)],
    )
    assert result['status'] == 'infeasible'
    assert '化学走班01' in result['message']
    assert '周末需1节，可用0节，缺1节' in result['message']
    assert result['diagnostics'][0]['code'] == 'class_slot_shortage'


def test_teacher_combined_demand_exceeds_available_slots():
    result = recommend_walk_slots(
        [dict(id=cid, name=f'化学走班0{cid}', teacher_id=1, weekly_periods=2)
         for cid in (1, 2)], [(1, 10), (2, 20)],
        [dict(id=1, name='教室', capacity=45)], [(1, p) for p in (1, 2, 3)],
    )
    assert result['status'] == 'infeasible'
    assert '同一教师' in result['message']
    assert '需4节，可用3节，缺1节' in result['message']


def test_shared_constraints_do_not_claim_hours_are_excessive():
    # Two classes each fit individually, but share both student and teacher.
    result = recommend_walk_slots(
        [dict(id=cid, name=f'班{cid}', teacher_id=1, weekly_periods=1) for cid in (1, 2)],
        [(1, 10), (2, 10)], [dict(id=1, name='教室', capacity=45)], [(1, 1), (1, 2)],
    )
    assert result['status'] == 'feasible'
