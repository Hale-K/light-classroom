from unittest.mock import AsyncMock

import pytest

from app.ai.agent import assistant_agent as assistant
from app.ai.gateway import model as gateway_model
from app.ai.model.chat import ChatEndpoint, ChatOutcome, ToolCallOut

teacher = assistant


@pytest.mark.asyncio
async def test_greeting_with_history_uses_local_fast_path():
    result = await assistant.handle_assistant_turn(
        None,
        1,
        [
            {"role": "user", "content": "之前的问题"},
            {"role": "assistant", "content": "之前的回答"},
            {"role": "user", "content": "你好"},
        ],
    )

    from app.ai.guide import local_reply
    assert result.text == local_reply("你好")


@pytest.mark.asyncio
async def test_short_followup_keeps_history_and_rules_query_uses_agent(monkeypatch):
    monkeypatch.setattr(gateway_model, "resolve_chat_endpoints", AsyncMock(return_value=[ChatEndpoint("1:test", "测试模型", "http://test", "", "test", 5)]))
    agent = AsyncMock(return_value=teacher.AssistantTurn(text="已查询"))
    monkeypatch.setattr(teacher, "agent_reply", agent)
    for turns in [
        [{"role": "user", "content": "本校有哪些规则？"}],
        [{"role": "user", "content": "数学禁排"}, {"role": "assistant", "content": "周几？"}, {"role": "user", "content": "周三"}],
    ]:
        result = await assistant.handle_assistant_turn(None, 1, turns)
        assert result.text == "已查询"
        assert agent.call_args.args[2] == turns


@pytest.mark.asyncio
async def test_operational_failure_bubbles_do_not_reach_agent_history(monkeypatch):
    monkeypatch.setattr(
        gateway_model,
        "resolve_chat_endpoints",
        AsyncMock(return_value=[ChatEndpoint("1:test", "测试模型", "http://test", "", "test", 5)]),
    )
    agent = AsyncMock(return_value=teacher.AssistantTurn(text="当前使用测试模型"))
    monkeypatch.setattr(teacher, "agent_reply", agent)
    turns = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "模型服务暂时不可用，助手已进入本地说明模式。"},
        {"role": "assistant", "content": "暂时无法连接后台。已保留任务编号。"},
        {"role": "user", "content": "你是什么模型"},
    ]

    result = await assistant.handle_assistant_turn(None, 1, turns)

    assert result.text == "当前使用测试模型"
    assert agent.call_args.args[2] == [
        {"role": "user", "content": "你好"},
        {"role": "user", "content": "你是什么模型"},
    ]


@pytest.mark.asyncio
async def test_model_has_no_execute_tool_and_unprivileged_proposal_is_denied(monkeypatch):
    seen = []
    async def caller(**kwargs):
        seen.append(kwargs)
        if len(seen) == 1:
            return ChatOutcome(tool_calls=[ToolCallOut(id="1", name="propose_rules", arguments="{}")])
        return ChatOutcome(text="无配置权限")
    monkeypatch.setattr(gateway_model, "complete_chat_tools", caller)
    result = await assistant.agent_reply(None, 1, [{"role": "user", "content": "添加规则"}], base_url="http://test", api_key="", model="test", timeout=5)
    assert result.plan is None
    assert all("execute" not in t["function"]["name"] and t["function"]["name"] != "propose_rules" for t in seen[0]["tools"])
    assert "没有排课配置权限" in seen[1]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_context_overflow_keeps_error_without_reexecuting_verified_tools(monkeypatch):
    from app.ai.model.chat import ChatError
    from app.ai.gateway import tool as gateway_tool
    seen = []
    overflow = ChatError("对话内容超出模型上下文长度。", "context_overflow")
    lookup = AsyncMock(return_value='{"ok":true,"facts":["本校规则已核对"]}')
    monkeypatch.setattr(gateway_tool, 'execute_school_tool', lookup)

    async def caller(**kwargs):
        seen.append(kwargs)
        if len(seen) == 1:
            return ChatOutcome(tool_calls=[ToolCallOut('rules', 'lookup_rules', '{}')])
        assert '本校规则已核对' in kwargs['messages'][-1]['content']
        raise overflow

    monkeypatch.setattr(gateway_model, "complete_chat_tools", caller)
    turns = [{"role": "user", "content": f"第{i}问"} for i in range(10)]
    with pytest.raises(ChatError) as caught:
        await assistant.agent_reply(None, 1, turns, base_url="http://test", api_key="", model="test", timeout=5)
    assert caught.value is overflow
    lookup.assert_awaited_once()
    assert len(seen) == 2
    assert any(message.get('content') == '第9问' for message in seen[1]['messages'])


@pytest.mark.asyncio
async def test_unavailable_tool_model_bubbles_without_text_fallback(monkeypatch):
    from app.ai.model.chat import ChatError
    teacher.provider_circuits.clear()
    monkeypatch.setattr(gateway_model, "resolve_chat_endpoints", AsyncMock(return_value=[ChatEndpoint("1:test", "测试模型", "http://test", "", "test", 200)]))

    failure = ChatError("模型服务暂时不可用，请稍后重试。", "unavailable")
    caller = AsyncMock(side_effect=failure)
    text_fallback = AsyncMock(return_value="不应交付的无证据说明")
    monkeypatch.setattr(gateway_model, "complete_chat_tools", caller)
    monkeypatch.setattr(gateway_model, "complete_chat", text_fallback)
    turns = [
        {"role": "user", "content": "开始"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "帮我把数学排在周五下午"},
    ]
    with pytest.raises(ChatError) as caught:
        await assistant.handle_assistant_turn(None, 1, turns)
    assert caught.value is failure
    caller.assert_awaited_once()
    text_fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_model_reply_stays_precise_without_text_only_retry(monkeypatch):
    from app.ai.model.chat import ChatError
    teacher.provider_circuits.clear()
    monkeypatch.setattr(gateway_model, "resolve_chat_endpoints", AsyncMock(return_value=[ChatEndpoint("1:test", "测试模型", "http://test", "", "test", 60)]))
    failure = ChatError("模型没有返回文本，请重试。", "empty")
    caller = AsyncMock(side_effect=failure)
    text_fallback = AsyncMock(return_value="不应交付的压缩说明")
    monkeypatch.setattr(gateway_model, "complete_chat_tools", caller)
    monkeypatch.setattr(gateway_model, "complete_chat", text_fallback)
    turns = [{"role": "user", "content": f"第{i}问"} for i in range(9)]
    with pytest.raises(ChatError) as caught:
        await assistant.handle_assistant_turn(None, 1, turns)
    assert caught.value is failure
    caller.assert_awaited_once()
    text_fallback.assert_not_awaited()
