from app.api.v1.exam_scheduling import router


def test_exam_room_catalog_is_read_only_for_exam_scheduling():
    methods_by_path = {
        (route.path, method)
        for route in router.routes
        for method in (route.methods or set())
    }

    assert ("/exam-scheduling/rooms", "GET") in methods_by_path
    assert ("/exam-scheduling/rooms", "POST") not in methods_by_path
    assert not any(path.startswith("/exam-scheduling/rooms/") for path, _ in methods_by_path)
