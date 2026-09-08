from app.ai.conversations.projector import project_messages, project_summary


def test_project_messages_excludes_operational_and_degraded_assistant_bubbles():
    messages = [
        {"role": "user", "content": "帮我检查排课准备"},
        {"role": "assistant", "content": "Network Error"},
        {"role": "assistant", "content": "暂时无法连接后台。已保留任务编号。"},
        {"role": "assistant", "content": "模型服务暂时不可用，助手已进入本地说明模式。"},
        {"role": "assistant", "content": "当前学年还没有规则组。"},
    ]

    assert project_messages(messages) == [
        {"role": "user", "content": "帮我检查排课准备"},
        {"role": "assistant", "content": "当前学年还没有规则组。"},
    ]


def test_explicit_visibility_wins_and_user_reported_error_remains_context():
    messages = [
        {"role": "assistant", "content": "普通文字", "model_visible": False},
        {"role": "user", "content": "页面提示 Network Error，怎么处理？", "model_visible": False},
    ]

    assert project_messages(messages) == [
        {"role": "user", "content": "页面提示 Network Error，怎么处理？"},
    ]


def test_project_summary_removes_legacy_failure_answer_only():
    summary = "\n".join([
        "老师：你好",
        "助手：模型服务暂时不可用，助手已进入本地说明模式。",
        "助手：你好，我是轻课堂教务助手。",
    ])

    assert project_summary(summary) == "老师：你好\n助手：你好，我是轻课堂教务助手。"


def test_project_summary_removes_truncated_legacy_failure_line():
    summary = "模型服务暂时不可用，助手已进入本地说明模式。\n老师：再试一次"

    assert project_summary(summary) == "老师：再试一次"
