from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.ai.agent.assistant_agent import AssistantTurn
from app.ai.gateway import assistant as gateway_module
from app.ai.gateway.assistant import AssistantGateway, AssistantRequest


@pytest.mark.asyncio
async def test_chat_projects_transport_notices_before_agent_call(monkeypatch):
    invoke = AsyncMock(return_value=AssistantTurn(text="已完成核对"))
    monkeypatch.setattr(gateway_module, "handle_assistant_turn", invoke)
    gateway = AssistantGateway()
    request = AssistantRequest(messages=[
        {"role": "user", "content": "帮我核对排课"},
        {"role": "assistant", "content": "Network Error"},
        {"role": "assistant", "content": "正在处理", "model_visible": False},
        {"role": "assistant", "content": "请先设置学年学期"},
    ])

    result = await gateway.chat(object(), 1, 2, request, can_manage_rules=False)

    assert result.text == "已完成核对"
    turns = invoke.await_args.args[2]
    assert turns == [
        {"role": "user", "content": "帮我核对排课"},
        {"role": "assistant", "content": "请先设置学年学期"},
    ]


@pytest.mark.asyncio
async def test_start_run_uses_projected_memory_and_only_spawns_new_run(monkeypatch):
    monkeypatch.setattr(gateway_module, "remember_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(gateway_module, "memory_context", AsyncMock(return_value=""))
    monkeypatch.setattr(
        gateway_module,
        "get_conversation",
        AsyncMock(return_value=SimpleNamespace(summary="助手：Network Error\n用户：继续核对")),
    )
    create = AsyncMock(return_value=({"id": "a" * 32, "status": "running"}, True))
    spawn = Mock()
    monkeypatch.setattr(gateway_module, "create_run", create)
    monkeypatch.setattr(gateway_module, "spawn_run", spawn)
    request = AssistantRequest(
        messages=[{"role": "user", "content": "继续"}],
        page_path="/scheduling",
        message_id="message-1",
    )

    result = await AssistantGateway().start_run(object(), 1, 2, "a" * 32, request)

    assert result["status"] == "running"
    payload = create.await_args.args[4]
    assert payload["memory_summary"].startswith("用户：继续核对")
    assert "Network Error" not in payload["memory_summary"]
    assert payload["context_state"]["latest_request"] == "继续"
    assert payload["page_path"] == "/scheduling"
    spawn.assert_called_once_with("a" * 32, 1, 2, payload)


@pytest.mark.asyncio
async def test_existing_run_is_not_spawned_twice(monkeypatch):
    monkeypatch.setattr(gateway_module, "remember_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(gateway_module, "memory_context", AsyncMock(return_value=""))
    monkeypatch.setattr(gateway_module, "get_conversation", AsyncMock(return_value=None))
    monkeypatch.setattr(
        gateway_module,
        "create_run",
        AsyncMock(return_value=({"id": "b" * 32, "status": "running"}, False)),
    )
    spawn = Mock()
    monkeypatch.setattr(gateway_module, "spawn_run", spawn)

    await AssistantGateway().start_run(
        object(), 1, 2, "b" * 32,
        AssistantRequest(messages=[{"role": "user", "content": "继续"}]),
    )

    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_gateway_steer_delegates_to_durable_inbox(monkeypatch):
    steer = AsyncMock(return_value={"accepted": True, "kind": "steer"})
    monkeypatch.setattr(gateway_module, "steer_run", steer)
    session = object()

    result = await AssistantGateway().steer(session, 1, 2, "c" * 32, "只检查高一")

    assert result == {"accepted": True, "kind": "steer"}
    steer.assert_awaited_once_with(session, "c" * 32, 1, 2, "只检查高一")
