import pytest

from app.ai.guide import AssistantUiGuide
from app.ai.model.routing import ModelProviderRouter
from app.ai.runtime import AssistantRuntime, ServiceRegistry


def test_service_registry_has_named_runtime_capabilities():
    runtime = AssistantRuntime()

    assert isinstance(runtime.service("model_router"), ModelProviderRouter)
    assert runtime.service("ui_guide") is AssistantUiGuide


@pytest.mark.asyncio
async def test_runtime_allows_service_replacement_and_emits_trace():
    events = []
    services = ServiceRegistry()
    replacement = object()
    services.register("model_router", replacement)

    async def on_trace(kind, data):
        events.append((kind, data))

    runtime = AssistantRuntime(services=services, on_trace=on_trace)
    await runtime.emit("turn.started", {"agent": "teacher"})

    assert runtime.service("model_router") is replacement
    assert runtime.service("ui_guide") is AssistantUiGuide
    assert events == [("turn.started", {"agent": "teacher"})]


def test_service_registry_rejects_duplicate_and_unknown_services():
    services = ServiceRegistry()
    services.register("test", object())

    with pytest.raises(ValueError):
        services.register("test", object())
    with pytest.raises(LookupError):
        services.get("missing")
