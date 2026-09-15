from unittest.mock import AsyncMock

import pytest

from app.ai.agent import assistant_agent
from app.ai.intent import AssistantIntent, IntentDecision, IntentGateway
from app.ai.runtime import AssistantRuntime, ServiceRegistry
from app.ai.supervisor import SupervisorKind, SupervisorReport


@pytest.mark.asyncio
async def test_diagnosis_intent_uses_supervisor_without_model(monkeypatch):
    async def semantic(*_args):
        return IntentDecision(AssistantIntent.DIAGNOSIS, 0.96, "pgvector")

    class FakeDiagnosisSupervisor:
        tasks = ()

        async def run(self, execute, *, on_event=None):
            return SupervisorReport(kind=SupervisorKind.DIAGNOSIS, summary="已收集排课失败证据")

    model_reply = AsyncMock(side_effect=AssertionError("诊断 Supervisor 不应调用模型 Agent"))
    monkeypatch.setattr(assistant_agent, "agent_reply", model_reply)
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
    assert not model_reply.await_args
