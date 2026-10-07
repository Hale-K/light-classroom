from app.services.scheduling.walk_recommendation import recommend_walk_slots


def test_walk_uses_one_window_when_three_independent_classes_fit_three_rooms():
    result = recommend_walk_slots(
        classes=[dict(id=i, name=str(i), teacher_id=i, weekly_periods=1) for i in [1, 2, 3]],
        members=[(i, i) for i in [1, 2, 3]],
        rooms=[dict(id=i, name=str(i), capacity=40) for i in [1, 2, 3]],
        slots=[(1, 3), (1, 4), (1, 5)],
    )
    assert result['status'] == 'feasible'
    assert result['recommended_count'] == 1
    assert len(result['placements']) == 3
    assert result['peak_concurrent_classes'] == 3
