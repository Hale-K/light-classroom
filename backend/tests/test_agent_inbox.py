from app.ai.runs.inbox import consume, receive


def test_inbox_wake_and_boundary_semantics():
    events = [
        receive("followup", "继续检查高一"),
        receive("steer", "只处理课位冲突"),
        receive("inject", {"page_path": "/scheduling?tab=rules"}),
    ]

    turn = consume(events, "turn")
    assert [item.kind for item in turn] == ["followup"]
    assert turn[0].wake is True
    step = consume(events, "step")
    assert [item.kind for item in step] == ["steer", "inject"]
    assert [item.wake for item in step] == [True, False]
    assert consume(events, "step") == []
