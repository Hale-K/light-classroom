from unittest.mock import AsyncMock

import pytest

from app.ai.agent import assistant_agent
from app.ai.gateway import model as gateway_model
from app.ai.gateway.tool import ToolGateway
from app.ai.harness import HarnessRouter
from app.ai.intent import AssistantIntent, AssistantRoute, FailureAction, IntentDecision, IntentGateway, ReviewAction
from app.ai.runtime import AssistantRuntime, ServiceRegistry
from app.ai.model.chat import ChatEndpoint, ChatOutcome


def test_router_maps_structured_intent_to_registered_harness():
    router = HarnessRouter()

    for kind in AssistantIntent:
        decision = IntentDecision(kind=kind, confidence=1, source="test")
        expected = "configuration" if kind is AssistantIntent.CONFIGURATION else "guide"
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


def test_router_jev_tool_hint_does_not_lock_readonly_queries():
    router = HarnessRouter()
    decision = IntentDecision(
        kind=AssistantIntent.GUIDE,
        confidence=0.95,
        source="jev",
        tool_hints=frozenset({"lookup_teachers"}),
    )
    profile = router.select(decision)
    assert profile.allowed_tools == router.profiles["guide"].allowed_tools
    assert 'propose_rules' not in profile.allowed_tools

    unknown = IntentDecision(
        kind=AssistantIntent.GUIDE,
        confidence=0.95,
        source="jev",
        tool_hints=frozenset({"delete_everything"}),
    )
    assert router.select(unknown).allowed_tools == router.profiles["guide"].allowed_tools


def test_router_policy_retries_then_creates_followup_or_waits_for_user():
    assert IntentGateway.failure_policy(retry_count=0, max_retries=1).action is FailureAction.RETRY
    assert IntentGateway.failure_policy(retry_count=1, max_retries=1).action is FailureAction.CREATE_FOLLOWUP
    assert IntentGateway.failure_policy(retry_count=1, max_retries=1, missing=("任教关系",)).action is FailureAction.WAIT_USER


def test_router_policy_requires_review_for_writes_and_recommends_it_for_gaps():
    assert IntentGateway.review_policy().action is ReviewAction.NONE
    assert IntentGateway.review_policy(missing=("规则组",)).action is ReviewAction.RECOMMENDED
    assert IntentGateway.review_policy(mutates_data=True).action is ReviewAction.REQUIRED


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
    assert decision.route is AssistantRoute.AGENT


@pytest.mark.asyncio
async def test_intent_gateway_fast_path_skips_semantic_classifier_for_arithmetic():
    async def semantic(*_args):
        raise AssertionError("fast path must not load semantic classification")

    decision = await IntentGateway(semantic).classify(None, "1 + 1 = ?")
    assert decision.route is AssistantRoute.DIRECT
    assert decision.source == "fast_path"


@pytest.mark.asyncio
async def test_optional_decision_layer_falls_back_when_unavailable_or_uncertain():
    async def jev(*_args):
        return IntentDecision(AssistantIntent.DIAGNOSIS, 0.40, "jev")

    async def semantic(_session, _query, _page_path, _recent_turns):
        return IntentDecision(AssistantIntent.READINESS, 0.88, "pgvector")

    decision = await IntentGateway(semantic, decision_classifier=jev).classify(None, "检查排课准备")

    assert decision.kind is AssistantIntent.READINESS
    assert decision.source == "pgvector"
    assert decision.route is AssistantRoute.AGENT


@pytest.mark.asyncio
async def test_optional_decision_layer_is_used_when_confident():
    async def jev(*_args):
        return IntentDecision(AssistantIntent.DIAGNOSIS, 0.91, "jev")

    async def semantic(*_args):
        raise AssertionError("fallback classifier should not run")

    decision = await IntentGateway(semantic, decision_classifier=jev).classify(None, "排课为什么失败")

    assert decision.kind is AssistantIntent.DIAGNOSIS
    assert decision.source == "jev"
    assert decision.route is AssistantRoute.AGENT


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
    monkeypatch.setattr(onboarding, "load_onboarding_status", AsyncMock(
        side_effect=AssertionError("普通聊天不应自动启动基础准备检查")))
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

        async def run(self, execute, *, context=None, parallel=False, on_event=None):
            raise AssertionError("普通聊天不应自动启动固定 Supervisor")

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
    assert events[1][1]["name"] == "guide"
    invoke.assert_awaited_once()
    assert invoke.await_args.kwargs['harness'].name == 'guide'
    assert not any(name.startswith('supervisor.') for name, _ in events)


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
