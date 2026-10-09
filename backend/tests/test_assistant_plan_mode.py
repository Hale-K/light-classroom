from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError


def test_mode_is_validated_and_old_requests_remain_standard():
    from app.api.v1.assistant import ChatIn, _assistant_request
    args = {'messages': [{'role': 'user', 'content': '帮我做方案'}]}
    assert _assistant_request(ChatIn(**args)).page_context['assistant_mode'] == 'standard'
    assert _assistant_request(ChatIn(**args, page_context={'assistant_mode': 'plan'})).page_context['assistant_mode'] == 'plan'
    with pytest.raises(ValidationError):
        ChatIn(**args, page_context={'assistant_mode': 'execute_anything'})


@pytest.mark.asyncio
async def test_plan_scope_denies_proposal_even_with_admin_and_all_tools(monkeypatch):
    from app.ai.gateway import tool
    propose = AsyncMock()
    monkeypatch.setattr(tool, 'propose_rules', propose)
    scope = tool.ToolGateway().open_scope(session=None, tenant_id=1, user_id=2,
        can_manage_rules=True, page_context={'assistant_mode': 'plan'})
    assert 'propose_rules' not in {item['function']['name'] for item in scope.definitions}
    result = await scope.execute('propose_rules', '{}')
    assert '拒绝' in result
    assert scope.plan is None
    propose.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_scope_keeps_queries_and_does_not_allow_unknown_tools(monkeypatch):
    from app.ai.gateway import tool
    execute = AsyncMock(return_value='只读查询结果')
    monkeypatch.setattr(tool, 'execute_school_tool', execute)
    scope = tool.ToolGateway().open_scope(session=None, tenant_id=7, user_id=2,
        can_manage_rules=True, page_context={'assistant_mode': 'plan'})
    assert await scope.execute('lookup_rules', '{}') == '只读查询结果'
    assert '拒绝' in await scope.execute('write_anything', '{}')
    assert execute.await_count == 1


@pytest.mark.asyncio
async def test_plan_scope_cannot_be_unlocked_by_mutating_page_metadata(monkeypatch):
    from app.ai.gateway import tool
    propose = AsyncMock()
    monkeypatch.setattr(tool, 'propose_rules', propose)
    context = {'assistant_mode': 'plan'}
    scope = tool.ToolGateway().open_scope(session=None, tenant_id=1, user_id=2,
        can_manage_rules=True, page_context=context)
    context['assistant_mode'] = 'standard'
    assert '拒绝' in await scope.execute('propose_rules', '{}')
    propose.assert_not_awaited()


@pytest.mark.asyncio
async def test_configuration_request_in_plan_mode_returns_advice_not_draft(monkeypatch):
    from app.ai.agent import assistant_agent
    from app.ai.gateway import model as gateway_model
    from app.ai.gateway import tool
    from app.ai.intent import AssistantIntent, IntentDecision, IntentGateway
    from app.ai.model.chat import ChatEndpoint, ChatOutcome, ToolCallOut
    from app.ai.runtime import AssistantRuntime, ServiceRegistry
    monkeypatch.setattr(gateway_model, 'resolve_chat_endpoints', AsyncMock(
        return_value=[ChatEndpoint('plan:test', 'test', 'http://test', '', 'test', 5)]))
    propose = AsyncMock()
    monkeypatch.setattr(tool, 'propose_rules', propose)
    calls = []
    async def complete(**request):
        calls.append(request)
        assert 'propose_rules' not in {item['function']['name'] for item in request['tools'] or []}
        assert '计划模式' in request['messages'][0]['content']
        if len(calls) == 1:
            # A model can still hallucinate an unadvertised tool; the gateway must deny it.
            return ChatOutcome(tool_calls=[ToolCallOut('bad', 'propose_rules', '{}')])
        if len(calls) == 2:
            assert '拒绝' in request['messages'][-1]['content']
            return ChatOutcome(tool_calls=[ToolCallOut('plan', 'plan_task',
                '{"goal":"只读规则建议","steps":[{"id":"rules","label":"核对规则现状"}]}')])
        if len(calls) == 3:
            return ChatOutcome(tool_calls=[ToolCallOut('blocked', 'update_plan_task',
                '{"task_id":"rules","status":"blocked","summary":"当前测试环境缺少本校规则数据；只能给未执行建议"}')])
        return ChatOutcome(text='建议周三不排数学；退出计划模式后再确认配置。')
    monkeypatch.setattr(gateway_model, 'complete_chat_tools', complete)
    services = ServiceRegistry()
    services.register('intent_gateway', IntentGateway(AsyncMock(return_value=IntentDecision(
        AssistantIntent.CONFIGURATION, .95, 'test'))))
    result = await assistant_agent.handle_assistant_turn(None, 7,
        [{'role': 'user', 'content': '高一规则组周三不要安排数学'}], user_id=2,
        can_manage_rules=True, runtime=AssistantRuntime(services=services),
        page_context={'assistant_mode': 'plan'})
    assert result.plan is None
    assert '建议' in result.text
    propose.assert_not_awaited()
