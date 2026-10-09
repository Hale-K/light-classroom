from unittest.mock import AsyncMock

import pytest

from app.ai.agent import assistant_agent
from app.ai.gateway import model as gateway_model
from app.ai.gateway import tool as gateway_tool
from app.ai.harness import HarnessRouter
from app.ai.intent import AssistantIntent, AssistantRoute, IntentDecision, IntentGateway
from app.ai.model.chat import ChatEndpoint, ChatOutcome, ToolCallOut
from app.ai.runtime import AssistantRuntime, ServiceRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', [AssistantIntent.READINESS, AssistantIntent.DIAGNOSIS])
async def test_readonly_topic_does_not_force_a_workflow(kind):
    classify = AsyncMock(return_value=IntentDecision(
        kind, .95, 'test', route=AssistantRoute.SUPERVISOR,
        tool_hints=frozenset({'lookup_walk_classes'}),
    ))
    decision = await IntentGateway(classify).classify(None, '帮我分析目前的问题')
    assert decision.kind is kind
    assert decision.route is AssistantRoute.AGENT
    profile = HarnessRouter().select(decision)
    assert profile.name == 'planning'
    assert {'lookup_walk_classes', 'lookup_rules'} <= profile.allowed_tools
    assert 'propose_rules' not in profile.allowed_tools


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', [AssistantIntent.READINESS, AssistantIntent.DIAGNOSIS])
async def test_chat_can_choose_next_tool_from_observation(monkeypatch, kind):
    from app.api.v1 import onboarding

    monkeypatch.setattr(onboarding, 'load_onboarding_status', AsyncMock(
        side_effect=AssertionError('chat must not start the fixed preparation chain')))
    monkeypatch.setattr(gateway_model, 'resolve_chat_endpoints', AsyncMock(
        return_value=[ChatEndpoint('autonomy:test', 'test', 'http://test', '', 'test', 5)]))
    # Authorization is tested against real identities in school query tests;
    # this test isolates choosing the next tool from returned observations.
    monkeypatch.setattr(gateway_tool.evidence, 'authorized', AsyncMock(return_value=True))
    executed = []

    async def execute(name, arguments, **kwargs):
        executed.append(name)
        assert kwargs['tenant_id'] == 7
        if name == 'lookup_walk_classes':
            return '{"ok":true,"facts":["班级和任课已有配置"],"next":"需核对规则"}'
        assert name == 'lookup_rules'
        return '{"ok":true,"facts":["周二禁排规则"]}'

    monkeypatch.setattr(gateway_tool, 'execute_school_tool', execute)
    requests = []

    async def complete(**request):
        requests.append(request)
        if len(requests) == 1:
            return ChatOutcome(tool_calls=[ToolCallOut('plan', 'plan_task',
                '{"goal":"查证高一走班问题","steps":[{"id":"evidence","label":"按证据查询班级和规则"},{"id":"conflicts","label":"查明是否存在课表冲突"}]}')])
        if len(requests) == 2:
            return ChatOutcome(tool_calls=[ToolCallOut('classes', 'lookup_walk_classes', '{}')])
        if len(requests) == 3:
            assert '需核对规则' in request['messages'][-1]['content']
            assert request['messages'][-1]['role'] == 'tool'
            assert 'lookup_rules' in {tool['function']['name'] for tool in request['tools']}
            return ChatOutcome(tool_calls=[ToolCallOut('rules', 'lookup_rules', '{}')])
        if len(requests) == 4:
            assert '周二禁排规则' in request['messages'][-1]['content']
            return ChatOutcome(tool_calls=[ToolCallOut('evidence', 'update_plan_task',
                '{"task_id":"evidence","status":"completed","summary":"返回班级任课已有配置及周二禁排规则"}')])
        if len(requests) == 5:
            return ChatOutcome(tool_calls=[ToolCallOut('blocked', 'update_plan_task',
                '{"task_id":"conflicts","status":"blocked","summary":"尚缺实际课表碰撞证据，不能判定根因"}')])
        return ChatOutcome(text='已核对班级、任课和规则；仍需核对冲突才能判断根因。')

    monkeypatch.setattr(gateway_model, 'complete_chat_tools', complete)
    services = ServiceRegistry()
    services.register('intent_gateway', IntentGateway(AsyncMock(return_value=IntentDecision(
        kind, .95, 'test', tool_hints=frozenset({'lookup_walk_classes'})))))
    events = []

    async def trace(name, data):
        events.append(name)

    result = await assistant_agent.handle_assistant_turn(
        None, 7, [{'role': 'user', 'content': '请核对高一走班任课和规则是否有问题'}],
        runtime=AssistantRuntime(services=services), on_trace=trace,
        page_context={'grade_id': 3}, can_manage_rules=True,
    )
    assert executed == ['lookup_walk_classes', 'lookup_rules']
    assert len(requests) == 6
    assert '仍需核对冲突' in result.text
    assert not any(event.startswith('supervisor.') for event in events)
    assert all('propose_rules' not in {t['function']['name'] for t in req['tools'] or []}
               for req in requests)
