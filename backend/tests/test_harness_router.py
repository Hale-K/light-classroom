from unittest.mock import AsyncMock

import pytest

from app.ai.agent import assistant_agent
from app.ai.gateway import model as gateway_model
from app.ai.gateway.tool import ToolGateway
from app.ai.harness import HarnessRouter
from app.ai.model.chat import ChatEndpoint, ChatOutcome


def test_router_selects_registered_harnesses_deterministically():
    router = HarnessRouter()

    assert router.select("这个页面怎么使用").name == "guide"
    assert router.select("帮我检查排课准备情况，还缺什么").name == "readiness"
    assert router.select("排课生成失败，为什么卡住了").name == "diagnosis"
    assert router.select("为什么会这样", page_path="/scheduling").name == "diagnosis"
    assert router.select("创建数学晚课禁排规则").name == "configuration"
    assert set(router.profiles) == {"guide", "readiness", "diagnosis", "configuration"}


def test_tool_scope_cannot_exceed_harness_allowlist():
    scope = ToolGateway().open_scope(
        session=None,
        tenant_id=1,
        user_id=2,
        can_manage_rules=True,
        page_context=None,
        allowed_tools=HarnessRouter().profiles["readiness"].allowed_tools,
    )

    names = {item["function"]["name"] for item in scope.definitions}
    assert "lookup_schedule_setup" in names
    assert "propose_rules" not in names
    assert "lookup_generation_status" not in names


@pytest.mark.asyncio
async def test_selected_harness_is_traced_and_passed_to_agent(monkeypatch):
    monkeypatch.setattr(
        gateway_model,
        "resolve_chat_endpoints",
        AsyncMock(return_value=[ChatEndpoint("1:test", "测试模型", "http://test", "", "test", 5)]),
    )
    invoke = AsyncMock(return_value=assistant_agent.AssistantTurn(text="已检查"))
    monkeypatch.setattr(assistant_agent, "agent_reply", invoke)
    events = []

    async def trace(kind, data):
        events.append((kind, data))

    result = await assistant_agent.handle_assistant_turn(
        None,
        1,
        [{"role": "user", "content": "帮我检查排课准备情况"}],
        on_trace=trace,
    )

    assert result.text == "已检查"
    assert events[0][0] == "harness.selected"
    assert events[0][1]["name"] == "readiness"
    assert invoke.await_args.kwargs["harness"].name == "readiness"


@pytest.mark.asyncio
async def test_agent_applies_harness_prompt_and_tool_budget(monkeypatch):
    calls = []

    async def complete(**request):
        calls.append(request)
        return ChatOutcome(text="诊断完成")

    monkeypatch.setattr(gateway_model, "complete_chat_tools", complete)
    result = await assistant_agent.agent_reply(
        None,
        1,
        [{"role": "user", "content": "排课生成失败，帮我诊断"}],
        base_url="http://test",
        api_key="",
        model="test",
        timeout=120,
    )

    assert result.text == "诊断完成"
    names = {item["function"]["name"] for item in calls[0]["tools"]}
    assert "lookup_generation_status" in names
    assert "propose_rules" not in names
    assert "本轮服务端执行约束" in calls[0]["messages"][0]["content"]
    assert calls[0]["timeout"] == 75
