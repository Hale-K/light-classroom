import pytest

from app.ai.guide import AssistantUiGuide
from app.ai.gateway import ModelGateway, ToolGateway
from app.ai.harness import HarnessRouter
from app.ai.intent import IntentGateway
from app.ai.runtime import AssistantRuntime, ServiceRegistry


def test_service_registry_has_named_runtime_capabilities():
    runtime = AssistantRuntime()

    assert isinstance(runtime.service("model_gateway"), ModelGateway)
    assert isinstance(runtime.service("tool_gateway"), ToolGateway)
    assert runtime.service("ui_guide") is AssistantUiGuide
    assert isinstance(runtime.service("intent_gateway"), IntentGateway)
    assert isinstance(runtime.service("harness_router"), HarnessRouter)


@pytest.mark.asyncio
async def test_runtime_allows_service_replacement_and_emits_trace():
    events = []
    services = ServiceRegistry()
    replacement = object()
    services.register("model_gateway", replacement)

    async def on_trace(kind, data):
        events.append((kind, data))

    runtime = AssistantRuntime(services=services, on_trace=on_trace)
    await runtime.emit("turn.started", {"agent": "assistant"})

    assert runtime.service("model_gateway") is replacement
    assert runtime.service("ui_guide") is AssistantUiGuide
    assert events == [("turn.started", {"agent": "assistant"})]


def test_service_registry_rejects_duplicate_and_unknown_services():
    services = ServiceRegistry()
    services.register("test", object())

    with pytest.raises(ValueError):
        services.register("test", object())
    with pytest.raises(LookupError):
        services.get("missing")
