from app.services.scheduling.walk_coordination_check import check


def sample(rooms):
    return dict(classes=[dict(id=1, teacher_id=10, weekly_periods=1)],
                members=[(1, 100)], rooms=rooms, slots=[(1, 1), (1, 2), (1, 3)],
                kwargs={'student_contiguous_periods': {1: [1, 2, 3]}})


def test_joint_check_can_coordinate_public_and_walk_without_more_rooms():
    result = check(sample([dict(id=1, capacity=40)]), {100: 9},
                   {'odd': {9: 1}, 'even': {9: 1}})
    assert result['status'] in ('OPTIMAL', 'FEASIBLE')
    public = set(result['public_windows'][9])
    walk = {tuple(slot) for slot in result['walk_windows']}
    assert len(public) == len(walk) == 1
    assert not public & walk
    assert public | walk == {(1, 1), (1, 2)}  # Trailing third period remains empty.


def test_joint_check_does_not_hide_a_real_room_shortage():
    result = check(sample([]), {100: 9}, {'odd': {9: 1}, 'even': {9: 1}})
    assert result['status'] == 'INFEASIBLE'
