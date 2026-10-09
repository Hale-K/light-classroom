from unittest.mock import AsyncMock

import pytest

from app.ai.agent import assistant_agent
from app.ai.intent import AssistantIntent, ExecutionMode, IntentDecision, IntentGateway
from app.ai.intent.vector import PostgresIntentClassifier
from app.ai.runtime import AssistantRuntime, ServiceRegistry
from app.ai.supervisor.contracts import (
    SupervisorTask, SupervisorResultStatus, normalize_supervisor_result,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['你好我现在有一些排课问题', '我有排课问题', '排课有问题', '排课出问题了', '我想咨询一下排课', '排课方面有点问题'])
async def test_generic_problem_asks_for_symptom_before_readiness(query):
    classifier = AsyncMock(return_value=IntentDecision(AssistantIntent.READINESS, .95, 'test'))
    services = ServiceRegistry()
    services.register('intent_gateway', IntentGateway(classifier))
    result = await assistant_agent.handle_assistant_turn(
        None, 1, [{'role': 'user', 'content': query}],
        runtime=AssistantRuntime(services=services),
    )
    assert '具体' in result.text
    assert '清单' not in result.text
    classifier.assert_not_awaited()


@pytest.mark.asyncio
async def test_basic_joint_preview_question_does_not_start_a_long_task():
    classifier = AsyncMock(side_effect=AssertionError('local consultation needs no classifier'))
    services = ServiceRegistry()
    services.register('intent_gateway', IntentGateway(classifier))
    result = await assistant_agent.handle_assistant_turn(None, 1,
        [{'role': 'user', 'content': '联合排课预览会保存吗？'}],
        runtime=AssistantRuntime(services=services))
    assert '不会' in result.text
    assert '确认保存' in result.text
    classifier.assert_not_awaited()


@pytest.mark.asyncio
async def test_classifier_timeout_has_a_bounded_fallback():
    import asyncio
    async def slow(*args):
        await asyncio.sleep(10)
    gateway = IntentGateway(slow, classification_timeout_seconds=.01)
    decision = await gateway.classify(None, '怎么查看课表')
    assert decision.kind is AssistantIntent.GUIDE
    assert decision.source == 'safe_fallback'


@pytest.mark.asyncio
async def test_uncertain_intent_does_not_open_model_or_tools(monkeypatch):
    classifier = AsyncMock(return_value=IntentDecision(
        AssistantIntent.UNKNOWN, .52, 'test', needs_clarification=True,
    ))
    reply = AsyncMock(side_effect=AssertionError('must clarify first'))
    monkeypatch.setattr(assistant_agent, 'agent_reply', reply)
    services = ServiceRegistry()
    services.register('intent_gateway', IntentGateway(classifier))
    result = await assistant_agent.handle_assistant_turn(
        None, 1, [{'role': 'user', 'content': '这个怎么处理'}],
        runtime=AssistantRuntime(services=services),
    )
    assert '具体' in result.text
    reply.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['当前页面内容有什么', '页面中什么内容', '这个界面是干什么的'])
async def test_page_description_questions_route_to_agent_without_classifier(query):
    classifier = AsyncMock(side_effect=AssertionError('page questions need no classifier'))
    decision = await IntentGateway(classifier).classify(None, query)
    from app.ai.intent import AssistantRoute
    assert decision.kind is AssistantIntent.GUIDE
    assert decision.source == 'fast_path'
    assert decision.route is AssistantRoute.AGENT
    assert not decision.needs_clarification
    classifier.assert_not_awaited()


@pytest.mark.asyncio
async def test_business_rule_question_still_uses_classifier():
    classifier = AsyncMock(return_value=IntentDecision(AssistantIntent.CONFIGURATION, .95, 'test'))
    decision = await IntentGateway(classifier).classify(None, '规则内容怎么修改')
    assert decision.kind is AssistantIntent.CONFIGURATION
    classifier.assert_awaited_once()


async def _turn_reaches_model_with_uncertain_intent(monkeypatch, page_context):
    from app.ai.gateway import model as gateway_model
    from app.ai.model.chat import ChatEndpoint, ChatOutcome
    monkeypatch.setattr(gateway_model, 'resolve_chat_endpoints', AsyncMock(
        return_value=[ChatEndpoint('clarify:test', 'test', 'http://test', '', 'test', 5)]))
    complete = AsyncMock(return_value=ChatOutcome(text='这是本轮模型回答。'))
    monkeypatch.setattr(gateway_model, 'complete_chat_tools', complete)
    classifier = AsyncMock(return_value=IntentDecision(
        AssistantIntent.UNKNOWN, .5, 'test', needs_clarification=True))
    services = ServiceRegistry()
    services.register('intent_gateway', IntentGateway(classifier))
    return await assistant_agent.handle_assistant_turn(
        None, 1, [{'role': 'user', 'content': '分析一下文档中的内容'}],
        runtime=AssistantRuntime(services=services), page_context=page_context), complete


@pytest.mark.asyncio
async def test_material_turn_is_not_dead_ended_by_uncertain_intent(monkeypatch):
    result, complete = await _turn_reaches_model_with_uncertain_intent(monkeypatch, {
        'reference_materials': [{'id': 'a', 'name': 'doc.pdf', 'text': '轻课堂使用说明'}],
    })
    assert '具体想处理什么问题' not in result.text
    complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_plan_mode_turn_is_not_dead_ended_by_uncertain_intent(monkeypatch):
    result, complete = await _turn_reaches_model_with_uncertain_intent(monkeypatch, {'assistant_mode': 'plan'})
    assert '具体想处理什么问题' not in result.text
    complete.assert_awaited_once()


def test_assistant_checklist_does_not_contaminate_intent_embedding():
    context = PostgresIntentClassifier._context_text('它怎么又停了', None, [
        {'role': 'user', 'content': '联合排课失败'},
        {'role': 'assistant', 'content': '学校基础准备清单 填写班级课时'},
        {'role': 'user', 'content': '它怎么又停了'},
    ])
    assert '联合排课失败' in context
    assert '基础准备清单' not in context


def test_tool_failure_is_not_reported_as_success():
    task = SupervisorTask('rules', '规则', '', frozenset({'lookup_rules'}))
    result = normalize_supervisor_result(task, {
        'ok': False, 'status': 'error', 'message': '无法读取规则',
    })
    assert result.status is SupervisorResultStatus.FAILED
    assert result.error == '无法读取规则'


@pytest.mark.asyncio
async def test_supervisor_executes_all_tools_and_keeps_partial_evidence():
    from app.ai.supervisor.executor import execute_task_tools

    task = SupervisorTask('status', '状态', '', frozenset({'lookup_generation_status', 'lookup_generation_log'}))
    scope = type('Scope', (), {})()
    scope.execute = AsyncMock(side_effect=[
        '{"ok":false,"status":"error","message":"日志读取失败"}',
        '{"ok":true,"status":"success","message":"任务失败","facts":["已有失败任务"]}',
    ])
    result = await execute_task_tools(task, scope, task.allowed_tools)
    assert [call.args[0] for call in scope.execute.await_args_list] == sorted(task.allowed_tools)
    assert result.status is SupervisorResultStatus.FAILED
    assert '已有失败任务' in result.facts
    assert '日志读取失败' in result.summary


@pytest.mark.asyncio
async def test_schedule_setup_uses_selected_class_context(monkeypatch):
    from app.ai.tools import school
    lookup = AsyncMock(return_value='指定班级已有配置')
    monkeypatch.setattr(school, 'lookup_schedule_setup', lookup)
    await school.execute_school_tool('lookup_schedule_setup', '{}', session=None,
        tenant_id=1, page_context={'class_id': 12, 'academic_year': '2026-2027', 'term': '2'})
    assert lookup.await_args.kwargs['class_id'] == 12


@pytest.mark.asyncio
async def test_tool_hint_survives_classification():
    classifier = AsyncMock(return_value=IntentDecision(AssistantIntent.GUIDE, .9, 'test',
        tool_hints=frozenset({'lookup_teachers'})))
    decision = await IntentGateway(classifier).classify(None, '数学教师任课情况')
    assert decision.tool_hints == frozenset({'lookup_teachers'})


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', [AssistantIntent.READINESS, AssistantIntent.DIAGNOSIS])
async def test_focused_read_query_does_not_start_comprehensive_checks(kind):
    from app.ai.intent import AssistantRoute
    from app.ai.harness import HarnessRouter
    classifier = AsyncMock(return_value=IntentDecision(kind, .95, 'test',
        tool_hints=frozenset({'lookup_teachers'}), execution_mode=ExecutionMode.QUERY))
    decision = await IntentGateway(classifier).classify(None, '政治老师的任课情况')
    assert decision.route is AssistantRoute.AGENT
    assert decision.effective_mode is ExecutionMode.QUERY
    assert HarnessRouter().select(decision).allowed_tools == HarnessRouter().profiles['query'].allowed_tools
    assert decision.kind is kind


@pytest.mark.asyncio
async def test_explicit_comprehensive_check_is_not_narrowed_by_one_tool_hint():
    from app.ai.intent import AssistantRoute
    classifier = AsyncMock(return_value=IntentDecision(AssistantIntent.READINESS, .95, 'test',
        tool_hints=frozenset({'lookup_teachers'})))
    decision = await IntentGateway(classifier).classify(None, '帮我全面检查排课准备情况')
    assert decision.route is AssistantRoute.AGENT


@pytest.mark.asyncio
async def test_low_similarity_does_not_launch_diagnosis():
    classifier = AsyncMock(return_value=IntentDecision(AssistantIntent.DIAGNOSIS, .55, 'pgvector'))
    decision = await IntentGateway(classifier).classify(None, '这个地方不太对')
    assert decision.needs_clarification


@pytest.mark.asyncio
async def test_classifiers_share_one_deadline():
    import asyncio
    semantic = AsyncMock(return_value=IntentDecision(AssistantIntent.READINESS, .95, 'pgvector'))
    async def slow(*args):
        await asyncio.sleep(10)
    decision = await IntentGateway(semantic, decision_classifier=slow,
        classification_timeout_seconds=.01).classify(None, '怎么查看课表')
    assert decision.source == 'safe_fallback'
    semantic.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_diagnosis_keeps_comprehensive_evidence():
    from app.ai.intent import AssistantRoute
    classifier = AsyncMock(return_value=IntentDecision(AssistantIntent.DIAGNOSIS, .95, 'test',
        tool_hints=frozenset({'lookup_generation_status'})))
    decision = await IntentGateway(classifier).classify(None, '排课失败，帮我诊断原因')
    assert decision.route is AssistantRoute.AGENT


@pytest.mark.asyncio
async def test_decision_requesting_clarification_is_not_overridden_by_vector():
    classifier = AsyncMock(return_value=IntentDecision(AssistantIntent.UNKNOWN, .5, 'jev',
        needs_clarification=True))
    vector = AsyncMock(return_value=IntentDecision(AssistantIntent.READINESS, .95, 'pgvector'))
    decision = await IntentGateway(vector, decision_classifier=classifier).classify(None, '这个怎么弄')
    assert decision.needs_clarification
    vector.assert_not_awaited()


@pytest.mark.asyncio
async def test_configuration_with_one_tool_stays_planning_and_requires_confirmed_write():
    from app.ai.intent import AssistantRoute
    from app.ai.harness import HarnessRouter
    classifier = AsyncMock(return_value=IntentDecision(AssistantIntent.CONFIGURATION, .95, 'test',
        tool_hints=frozenset({'lookup_rules'})))
    decision = await IntentGateway(classifier).classify(None, '修改教师禁排规则')
    assert decision.effective_mode is ExecutionMode.PLANNING
    assert decision.write_requested is True
    assert decision.route is AssistantRoute.AGENT
    profile = HarnessRouter().select(decision)
    assert profile.name == 'planning'
    assert 'propose_rules' in profile.allowed_tools
    assert '实际写入仍需独立确认' in profile.instructions


@pytest.mark.asyncio
async def test_cancelled_classifier_reuses_inflight_embedding_load(monkeypatch, tmp_path):
    import asyncio
    import builtins
    import time
    from types import SimpleNamespace
    from app.ai.intent.vector import SentenceTransformerEmbedding
    real_import = builtins.__import__
    loads = []
    model_object = object()
    def load(*args, **kwargs):
        loads.append(True)
        time.sleep(.05)
        return model_object
    def fake_import(name, *args, **kwargs):
        if name == 'sentence_transformers':
            return SimpleNamespace(SentenceTransformer=load)
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', fake_import)
    embedding = SentenceTransformerEmbedding(str(tmp_path))
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(embedding._get_model(), timeout=.005)
    assert await embedding._get_model() is model_object
    assert len(loads) == 1
