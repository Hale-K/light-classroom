"""agent 消息构造与 OpenAI tool_calls 解析。"""
from app.ai.agent.assistant_agent import rule_jumps
from app.ai.model.chat import parse_tool_calls
from app.ai.prompt.messages import build_agent_messages, build_messages


def test_parse_tool_calls_reads_openai_shape():
    calls = parse_tool_calls(
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_a",
                    "type": "function",
                    "function": {"name": "lookup_teachers", "arguments": '{"subject":"数学"}'},
                },
                {"id": "call_b", "type": "function", "function": {"name": "lookup_rules", "arguments": ""}},
                {"id": "call_c", "type": "function", "function": {"name": "", "arguments": "{}"}},
            ],
        }
    )
    assert [c.id for c in calls] == ["call_a", "call_b"]
    assert calls[0].name == "lookup_teachers"
    assert calls[0].arguments == '{"subject":"数学"}'
    assert calls[1].arguments == "{}", "空参数要补成合法 JSON 对象"


def test_parse_tool_calls_empty_when_absent():
    assert parse_tool_calls({"content": "直接回答"}) == []
    assert parse_tool_calls("不是字典") == []


def test_agent_messages_declare_tools_and_catalog():
    turns = [{"role": "user", "content": "高一有多少数学老师"}]
    messages = build_agent_messages(turns, page_title="排课", page_path="/scheduling?tab=rules")
    assert messages[0]["role"] == "system"
    system = messages[0]["content"]
    assert "lookup_teachers" in system, "system 必须告诉模型可用工具"
    assert "说明书目录" in system, "lookup_playbook 依赖目录选编号"
    assert "规则组件目录" in system, "组件名必须能对上真实目录，防止模型编名字"
    assert "当前页：排课" in system
    assert messages[1:] == turns


def test_rule_jumps_only_when_off_rules_page():
    answer = "在排课页「规则组」里配置，添加组件「课位教师角色」。"
    assert rule_jumps("怎么设置周六晚课必须班主任", answer, "/settings") == [
        {"label": "去规则组", "path": "/scheduling?tab=rules", "requires_confirmation": True}
    ]
    assert rule_jumps("怎么设置周六晚课必须班主任", answer, "/scheduling?tab=rules") == []
    assert rule_jumps("数学老师有谁", "任教「数学」的在职教师共 3 人。", "/settings") == []


def test_plain_messages_keep_retrieved_section():
    turns = [{"role": "user", "content": "怎么加禁排"}]
    messages = build_messages(turns, retrieved="已取回的说明书：\n\n正文")
    system = messages[0]["content"]
    assert "已取回的说明书" in system
    assert "lookup_teachers" not in system, "旧路径不声明工具，避免模型输出 tool_calls"
