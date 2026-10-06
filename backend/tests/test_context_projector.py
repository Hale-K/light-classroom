from app.ai.conversations.projector import project_messages, project_summary, project_state


def test_repeated_greeting_remains_latest_user_turn():
    messages = [
        {"role": "user", "content": "检查排课准备情况"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么能帮到你"},
        {"role": "user", "content": "你好"},
    ]
    assert project_messages(messages) == messages
    assert project_messages(project_messages(messages)) == messages


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


def test_project_messages_respects_token_budget_and_keeps_latest_user_message():
    messages = [
        {"role": "user", "content": "早期规则组信息 " * 80},
        {"role": "assistant", "content": "早期回答 " * 80},
        {"role": "user", "content": "请继续处理数学规则"},
    ]

    result = project_messages(messages, token_budget=80)

    assert result[-1] == {"role": "user", "content": "请继续处理数学规则"}
    assert sum(len(item["content"]) for item in result) < 500


def test_project_state_extracts_confirmed_slots_without_replacing_messages():
    state = project_state([
        {"role": "user", "content": "在高一规则组，数学周三第6节不能排课"},
        {"role": "assistant", "content": "已确认规则组为高一规则组"},
    ])

    assert state["confirmed"] == ["高一规则组"]
    assert "数学周三第6节不能排课" in state["latest_request"]


def test_project_messages_drops_tool_and_operational_noise_without_summarizing_it():
    messages = [
        {"role": "user", "content": "查一下数学老师"},
        {"role": "tool", "content": "搜索结果：" + "无关记录 " * 100},
        {"role": "assistant", "content": "无关中间结果", "message_kind": "tool_result"},
        {"role": "assistant", "content": "数学老师有 3 位。"},
    ]

    assert project_messages(messages) == [
        {"role": "user", "content": "查一下数学老师"},
        {"role": "assistant", "content": "数学老师有 3 位。"},
    ]


def test_project_messages_keeps_only_tool_conclusion_and_evidence_id():
    messages = [{
        "role": "tool", "message_kind": "tool_result",
        "content": "完整搜索原文和大量无关字段",
        "conclusion": "数学教师共 3 位",
        "evidence_id": "teachers:2026-1:math",
    }]

    assert project_messages(messages) == [{
        "role": "assistant",
        "content": "工具结论：数学教师共 3 位\n证据ID：teachers:2026-1:math",
    }]


def test_project_messages_deduplicates_stale_and_retry_results():
    messages = [
        {"role": "assistant", "content": "正在重试", "message_kind": "retry"},
        {"role": "assistant", "content": "已过期结果", "stale": True},
        {"role": "assistant", "content": "规则组有 2 个。"},
        {"role": "assistant", "content": "规则组有 2 个。"},
    ]

    assert project_messages(messages) == [{"role": "assistant", "content": "规则组有 2 个。"}]
