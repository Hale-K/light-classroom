from app.ai.agent.assistant_agent import local_reply


def test_local_reply_only_handles_greeting():
    assert "教务助手" in (local_reply("你好") or "")
    assert local_reply("这份合同违约怎么起诉") is None
    assert local_reply("有多少语文老师") is None


def test_page_question_reaches_gateway():
    assert local_reply("我下一步该干什么", "/campus-buildings?tab=resources") is None
