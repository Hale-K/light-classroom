"""Two execution meanings, tested independently of any live model provider."""
from unittest.mock import AsyncMock

import pytest

from app.ai.harness import HarnessRouter
from app.ai.intent import AssistantIntent, ExecutionMode, IntentDecision, IntentGateway


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [
    '你好', '1+1=?', '当前是什么课表模式？', '高一1班数学老师是谁？',
    '我想查询甲老师的任课情况', '继续下一页', '规则怎么修改？',
])
async def test_ordinary_questions_and_focused_queries_have_query_semantics(query):
    classify = AsyncMock(return_value=IntentDecision(
        AssistantIntent.GUIDE, .95, 'test', execution_mode=ExecutionMode.QUERY))
    decision = await IntentGateway(classify).classify(None, query)
    assert decision.effective_mode is ExecutionMode.QUERY
    assert decision.trace_data()['execution_mode'] == 'query'
    assert HarnessRouter().select(decision).name == 'query'


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [
    '你好，请根据当前课位给我三个课时方案',
    '设置3个方案，比较各科课时和剩余课位',
    '只查询全校所有班级的任课和课表冲突并汇总问题',
    '全面检查排课准备情况并分析缺少哪些数据',
    '从当前课位结构看星期一到星期五，第一到第7节课必须满课，第八和第九节可排可不排；'
    '根据语数外物化生政史的高考分数占比，体育2节音乐1节心理1节，设置3个方案吧',
])
async def test_explicit_complex_goals_override_a_weak_query_topic(query):
    # A topic classifier may mistake "只查询" for a focused query. Structural
    # goals still require planning rather than granting arbitrary write access.
    classify = AsyncMock(return_value=IntentDecision(
        AssistantIntent.GUIDE, .95, 'test', execution_mode=ExecutionMode.QUERY))
    decision = await IntentGateway(classify).classify(None, query)
    assert decision.effective_mode is ExecutionMode.PLANNING
    assert decision.trace_data()['execution_mode'] == 'planning'
    profile = HarnessRouter().select(decision)
    assert profile.name == 'planning'
    assert 'propose_rules' not in profile.allowed_tools


@pytest.mark.asyncio
async def test_semantic_planning_decision_is_kept_for_an_unfamiliar_expression():
    classify = AsyncMock(return_value=IntentDecision(
        AssistantIntent.GUIDE, .95, 'test', execution_mode=ExecutionMode.PLANNING))
    decision = await IntentGateway(classify).classify(None, '把这些证据组织成完整结论')
    assert decision.effective_mode is ExecutionMode.PLANNING


def test_execution_profiles_are_two_choices_and_write_intent_is_independent():
    assert set(HarnessRouter().profiles) == {'query', 'planning'}
    decision = IntentDecision(AssistantIntent.GUIDE, 1, 'test',
        execution_mode=ExecutionMode.PLANNING, write_requested=False)
    assert decision.trace_data()['execution_mode'] == 'planning'
    assert decision.trace_data()['write_requested'] is False
    assert 'propose_rules' not in HarnessRouter().select(decision).allowed_tools


@pytest.mark.asyncio
async def test_a_short_change_to_the_second_scenario_inherits_planning_context():
    classify = AsyncMock(return_value=IntentDecision(
        AssistantIntent.GUIDE, .95, 'test', execution_mode=ExecutionMode.QUERY))
    query = '第二套把体育改3节'
    decision = await IntentGateway(classify).classify(None, query, recent_turns=[
        {'role': 'user', 'content': '给我三个课时方案'},
        {'role': 'assistant', 'content': '已给出方案一、二、三，均未保存。'},
        {'role': 'user', 'content': query},
    ])
    assert decision.effective_mode is ExecutionMode.PLANNING
    assert decision.write_requested is False


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [
    '请修改高一排课规则', '把规则修改为周三禁排数学',
])
async def test_an_explicit_rule_edit_uses_planning_and_a_separate_write_request(query):
    classify = AsyncMock(return_value=IntentDecision(
        AssistantIntent.GUIDE, .95, 'test', execution_mode=ExecutionMode.QUERY))
    decision = await IntentGateway(classify).classify(None, query)
    assert decision.effective_mode is ExecutionMode.PLANNING
    assert decision.write_requested is True


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [
    '给我三个修改规则的方案，只做建议',
    '按当前课位设置3个方案，不保存、不修改数据',
    '如果修改课时配置，会影响哪些班级？',
])
async def test_simulation_and_explicit_readonly_language_never_request_writing(query):
    classify = AsyncMock(return_value=IntentDecision(
        AssistantIntent.GUIDE, .95, 'test', execution_mode=ExecutionMode.PLANNING))
    decision = await IntentGateway(classify).classify(None, query)
    assert decision.effective_mode is ExecutionMode.PLANNING
    assert decision.write_requested is False


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['不要规划，只查课时', '规划模式是什么',
    '当前学校的课表模式、学年学期和高考模式分别是什么？请查询并用表格回答。',
    '本条仅查询：查完整姓名「学生甲」的2026-2027第二学期高一个人保存课表，包含行政课和走班课；用星期、节次、科目、周次四列表格列出全部记录和总条数。'])
async def test_negated_planning_and_mode_explanations_are_focused_queries(query):
    classify = AsyncMock(return_value=IntentDecision(
        AssistantIntent.GUIDE, .95, 'test', execution_mode=ExecutionMode.PLANNING))
    decision = await IntentGateway(classify).classify(None, query)
    assert decision.effective_mode is ExecutionMode.QUERY
    assert decision.write_requested is False


@pytest.mark.parametrize('kind, expected', [
    (AssistantIntent.GUIDE, ExecutionMode.QUERY),
    (AssistantIntent.READINESS, ExecutionMode.PLANNING),
    (AssistantIntent.DIAGNOSIS, ExecutionMode.PLANNING),
    (AssistantIntent.CONFIGURATION, ExecutionMode.PLANNING),
])
def test_legacy_topic_tags_map_into_two_execution_meanings(kind, expected):
    decision = IntentDecision(kind, 1, 'legacy')
    assert decision.effective_mode is expected
    assert decision.trace_data()['execution_mode'] == expected.value
