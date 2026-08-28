from app.api.v1.scheduling import _assignment_room_name


def test_assignment_uses_class_home_room_when_room_is_empty():
    assert _assignment_room_name(None, 101, {101: "行政班固定教室001"}) == "行政班固定教室001"


def test_assignment_keeps_explicit_special_room():
    assert _assignment_room_name("化学实验室1", 101, {101: "行政班固定教室001"}) == "化学实验室1"
