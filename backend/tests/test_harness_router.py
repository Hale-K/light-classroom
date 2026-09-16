from unittest.mock import AsyncMock

import pytest

from app.ai.agent import assistant_agent
from app.ai.gateway import model as gateway_model
from app.ai.gateway.tool import ToolGateway
from app.ai.harness import HarnessRouter
from app.ai.intent import AssistantIntent, AssistantRoute, IntentDecision, IntentGateway
from app.ai.runtime import AssistantRuntime, ServiceRegistry
from app.ai.model.chat import ChatEndpoint, ChatOutcome


def test_router_maps_structured_intent_to_registered_harness():
    router = HarnessRouter()

    for kind in AssistantIntent:
        decision = IntentDecision(kind=kind, confidence=1, source="test")
        expected = "guide" if kind is AssistantIntent.UNKNOWN else kind.value
        assert router.select(decision).name == expected
    assert set(router.profiles) == {"direct", "guide", "readiness", "diagnosis", "configuration"}


def test_router_selects_direct_harness_for_fast_path():
    router = HarnessRouter()
    decision = IntentDecision(
        kind=AssistantIntent.GUIDE, confidence=1, source="fast_path",
        route=AssistantRoute.DIRECT,
    )
    profile = router.select(decision)
    assert profile.name == "direct"
    assert profile.max_steps == 1
    assert profile.allowed_tools == frozenset()


@pytest.mark.asyncio
async def test_intent_gateway_uses_semantic_classifier_without_phrase_enumeration():
    async def semantic(session, query, page_path, recent_turns):
        assert session == "db"
        assert page_path == "/scheduling"
        return IntentDecision(AssistantIntent.DIAGNOSIS, 0.87, "pgvector")

    decision = await IntentGateway(semantic).classify(
        "db", "它怎么又停了", page_path="/scheduling"
    )

    assert decision.kind is AssistantIntent.DIAGNOSIS
    assert decision.source == "pgvector"


@pytest.mark.asyncio
async def test_intent_gateway_fast_path_skips_semantic_classifier_for_arithmetic():
    async def semantic(*_args):
        raise AssertionError("fast path must not load semantic classification")

    decision = await IntentGateway(semantic).classify(None, "1 + 1 = ?")
    assert decision.route is AssistantRoute.DIRECT
    assert decision.source == "fast_path"


@pytest.mark.asyncio
async def test_intent_gateway_delegates_ambiguous_language_to_semantic_classifier():
    async def semantic(session, query, page_path, recent_turns):
        assert query == "照刚才说的处理"
        assert recent_turns[-1]["content"] == query
        return IntentDecision(AssistantIntent.CONFIGURATION, 0.82, "semantic")

    decision = await IntentGateway(semantic).classify(
        None, "照刚才说的处理",
        page_path="/rules",
        recent_turns=[{"role": "user", "content": "照刚才说的处理"}],
    )

    assert decision.kind is AssistantIntent.CONFIGURATION
    assert decision.source == "semantic"


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
    from app.api.v1 import onboarding
    foundation_keys = ("year", "personnel", "space", "allocation", "class_planning", "grid", "hours", "assignments")
    monkeypatch.setattr(onboarding, "load_onboarding_status", AsyncMock(return_value={
        "data": {"steps": [{"key": key, "done": True, "title": key, "detail": "已有记录", "path": "/scheduling"} for key in foundation_keys]}
    }))
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

    async def semantic(session, query, page_path, recent_turns):
        return IntentDecision(AssistantIntent.READINESS, 0.91, "pgvector")

    class FakeReadinessSupervisor:
        tasks = ()

        async def run(self, execute, *, context=None, on_event=None):
            from app.ai.supervisor import SupervisorKind, SupervisorReport
            return SupervisorReport(kind=SupervisorKind.READINESS, summary="已检查")

    services = ServiceRegistry()
    services.register("intent_gateway", IntentGateway(semantic))
    services.register("readiness_supervisor", FakeReadinessSupervisor())
    runtime = AssistantRuntime(services=services, on_trace=trace)

    result = await assistant_agent.handle_assistant_turn(
        None,
        1,
        [{"role": "user", "content": "帮我检查排课准备情况"}],
        on_trace=trace,
        runtime=runtime,
    )

    assert "已检查" in result.text
    assert events[0][0] == "intent.classified"
    assert events[0][1]["kind"] == "readiness"
    assert events[1][0] == "harness.selected"
    assert events[1][1]["name"] == "readiness"
    assert not invoke.await_args


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
        harness=HarnessRouter().profiles["diagnosis"],
    )

    assert result.text == "诊断完成"
    names = {item["function"]["name"] for item in calls[0]["tools"]}
    assert "lookup_generation_status" in names
    assert "propose_rules" not in names
    assert "本轮服务端执行约束" in calls[0]["messages"][0]["content"]
    assert calls[0]["timeout"] == 75
