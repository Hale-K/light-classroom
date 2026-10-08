from unittest.mock import AsyncMock

import pytest

from app.ai.agent import assistant_agent
from app.ai.intent import AssistantIntent, IntentDecision, IntentGateway
from app.ai.runtime import AssistantRuntime, ServiceRegistry
from app.ai.gateway import model as gateway_model
from app.ai.model.chat import ChatEndpoint


@pytest.mark.asyncio
async def test_diagnosis_intent_uses_agent_without_fixed_supervisor(monkeypatch):
    async def semantic(*_args):
        return IntentDecision(AssistantIntent.DIAGNOSIS, 0.96, "pgvector")

    class FakeDiagnosisSupervisor:
        tasks = ()

        async def run(self, execute, *, context, parallel=False, on_event=None):
            raise AssertionError("普通聊天不应自动运行标准诊断流程")

    model_reply = AsyncMock(return_value=assistant_agent.AssistantTurn(text="已收集排课失败证据"))
    monkeypatch.setattr(assistant_agent, "agent_reply", model_reply)
    monkeypatch.setattr(gateway_model, "resolve_chat_endpoints", AsyncMock(
        return_value=[ChatEndpoint("diagnosis:test", "测试模型", "http://test", "", "test", 5)]))
    services = ServiceRegistry()
    services.register("intent_gateway", IntentGateway(semantic))
    services.register("diagnosis_supervisor", FakeDiagnosisSupervisor())
    runtime = AssistantRuntime(services=services)

    result = await assistant_agent.handle_assistant_turn(
        None,
        1,
        [{"role": "user", "content": "排课生成失败，帮我诊断"}],
        runtime=runtime,
    )

    assert result.text == "已收集排课失败证据"
    model_reply.assert_awaited_once()
    assert model_reply.await_args.kwargs['harness'].name == 'guide'
