from unittest.mock import AsyncMock

import pytest

from app.ai.agent import teacher
from app.ai.model.chat import ChatEndpoint, ChatOutcome, ToolCallOut


@pytest.mark.asyncio
async def test_short_followup_keeps_history_and_rules_query_uses_agent(monkeypatch):
    monkeypatch.setattr(teacher, "resolve_chat_endpoints", AsyncMock(return_value=[ChatEndpoint("1:test", "测试模型", "http://test", "", "test", 5)]))
    agent = AsyncMock(return_value=teacher.TeacherTurn(text="已查询"))
    monkeypatch.setattr(teacher, "agent_reply", agent)
    for turns in [
        [{"role": "user", "content": "本校有哪些规则？"}],
        [{"role": "user", "content": "数学禁排"}, {"role": "assistant", "content": "周几？"}, {"role": "user", "content": "周三"}],
    ]:
        result = await teacher.handle_teacher_turn(None, 1, turns)
        assert result.text == "已查询"
        assert agent.call_args.args[2] == turns


@pytest.mark.asyncio
async def test_model_has_no_execute_tool_and_unprivileged_proposal_is_denied(monkeypatch):
    from app.ai.graph import loop
    seen = []
    async def caller(**kwargs):
        seen.append(kwargs)
        if len(seen) == 1:
            return ChatOutcome(tool_calls=[ToolCallOut(id="1", name="propose_rules", arguments="{}")])
        return ChatOutcome(text="无配置权限")
    monkeypatch.setattr(loop, "complete_chat_tools", caller)
    result = await teacher.agent_reply(None, 1, [{"role": "user", "content": "添加规则"}], base_url="http://test", api_key="", model="test", timeout=5)
    assert result.plan is None
    assert all("execute" not in t["function"]["name"] and t["function"]["name"] != "propose_rules" for t in seen[0]["tools"])
    assert "没有排课配置权限" in seen[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_context_overflow_trims_history_and_retries(monkeypatch):
    from app.ai.graph import loop
    from app.ai.model.chat import ChatError
    seen = []

    async def caller(**kwargs):
        seen.append(kwargs)
        if len(seen) == 1:
            raise ChatError("对话内容超出模型上下文长度。", "context_overflow")
        return ChatOutcome(text="已按最近上下文回答")

    monkeypatch.setattr(loop, "complete_chat_tools", caller)
    turns = [{"role": "user", "content": f"第{i}问"} for i in range(10)]
    result = await teacher.agent_reply(None, 1, turns, base_url="http://test", api_key="", model="test", timeout=5)
    assert result.text == "已按最近上下文回答"
    assert len(seen) == 2
    assert len(seen[1]["messages"]) < len(seen[0]["messages"])
    assert seen[1]["messages"][-1]["content"] == "第9问"


@pytest.mark.asyncio
async def test_fallback_calls_are_budget_capped(monkeypatch):
    from app.ai.graph import loop
    from app.ai.model.chat import ChatError
    monkeypatch.setattr(teacher, "resolve_chat_endpoints", AsyncMock(return_value=[ChatEndpoint("1:test", "测试模型", "http://test", "", "test", 200)]))

    async def caller(**kwargs):
        raise ChatError("模型服务暂时不可用，请稍后重试。", "unavailable")

    monkeypatch.setattr(loop, "complete_chat_tools", caller)
    monkeypatch.setattr(teacher, "retrieve_skill", AsyncMock(return_value=""))
    timeouts = []

    async def fake_complete(**kwargs):
        timeouts.append(kwargs["timeout"])
        return "先到排课页配置课位结构"

    monkeypatch.setattr(teacher, "complete_chat", fake_complete)
    turns = [
        {"role": "user", "content": "开始"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "帮我把数学排在周五下午"},
    ]
    result = await teacher.handle_teacher_turn(None, 1, turns)
    assert result.text.startswith("当前模型工具调用不可用")
    assert timeouts and all(t <= 75 for t in timeouts), "降级两轮必须压进 RUN_TIMEOUT 剩余预算"


@pytest.mark.asyncio
async def test_fallback_context_overflow_retries_trimmed(monkeypatch):
    from app.ai.graph import loop
    from app.ai.model.chat import ChatError
    monkeypatch.setattr(teacher, "resolve_chat_endpoints", AsyncMock(return_value=[ChatEndpoint("1:test", "测试模型", "http://test", "", "test", 60)]))
    monkeypatch.setattr(loop, "complete_chat_tools", AsyncMock(side_effect=ChatError("模型没有返回文本，请重试。", "empty")))
    monkeypatch.setattr(teacher, "retrieve_skill", AsyncMock(return_value=""))
    calls = []

    async def fake_complete(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ChatError("对话内容超出模型上下文长度。", "context_overflow")
        return "压缩后的说明"

    monkeypatch.setattr(teacher, "complete_chat", fake_complete)
    turns = [{"role": "user", "content": f"第{i}问"} for i in range(9)]
    result = await teacher.handle_teacher_turn(None, 1, turns)
    assert "压缩后的说明" in result.text
    assert len(calls) == 2
    assert len(calls[1]["messages"]) < len(calls[0]["messages"])
