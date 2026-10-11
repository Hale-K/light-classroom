import json
import pytest
from pydantic import ValidationError
from app.ai.tools.clarification import Clarification, local_clarification, restore_clarification, is_slot_constraint_statement


def test_selected_query_goal_is_not_asked_again():
    card = local_clarification('继续之前的任务，保留已明确的条件。\n接下来希望我帮你完成什么？：查询当前情况')
    assert [question['id'] for question in card['questions']] == ['object']
    assert '已明确目标：查询当前情况' in card['known_conditions']
    assert all('接下来希望' not in question['title'] for question in card['questions'])
from app.ai.gateway.tool import ToolScope
from app.ai.conversations.service import _clean


def test_keep_explicit_slots_and_only_ask_missing_decisions():
    card = local_clarification('我已经确认了课位，但是周一到周六课位1-7节必须排满，但是8-9节可适当排')
    assert '周一到周六课位1-7节必须排满' in ''.join(card['known_conditions'])
    assert '8-9节可适当排' in ''.join(card['known_conditions'])
    assert [q['id'] for q in card['questions']] == ['goal', 'scope']
    assert not any('学期' in q['title'] or '模式' in q['title'] for q in card['questions'])
    assert len(local_clarification('高一课位1-7必排，8-9可选')['questions']) == 1
    assert is_slot_constraint_statement('周一到周六课位1-7节必须排满，8-9节可适当排')
    assert not is_slot_constraint_statement('高一课位1-7必排，请给三个方案')
    assert local_clarification('课位必须排满' + '补充' * 1000)


def test_history_staffing_reference_does_not_require_new_staffing_calculation():
    scope = ToolScope(None, 1, None, False, {})
    scope.configure_request('只核对已保存课时，不设计新方案；历史师资测算不能当成已保存的课时配置。')
    assert not scope._staffing_plan_request
    scope.configure_request('高一1000人，20个班，需要多少老师？')
    assert scope._staffing_plan_request
    scope.configure_request('学校现在有多少老师？')
    assert not scope._staffing_plan_request


def test_invalid_or_duplicate_questions_cannot_be_restored():
    card = local_clarification('安排一下')
    card['questions'].append(card['questions'][0])
    assert restore_clarification(card) is None
    with pytest.raises(ValidationError):
        Clarification.model_validate(card)


@pytest.mark.asyncio
async def test_guidance_is_display_only_and_authorized_in_plan_mode():
    scope = ToolScope(None, 1, None, False, {'assistant_mode': 'plan'},
        allowed_tools=frozenset({'request_clarification'}))
    card = local_clarification('排考怎么安排')
    result = json.loads(await scope.execute('request_clarification', json.dumps(card, ensure_ascii=False)))
    assert result['ok']
    assert scope.clarification == card
    assert scope.plan is None
    assert scope.task_plan is None
    invalid = await scope.execute('request_clarification', '{}')
    assert not json.loads(invalid)['ok']
    scope.task_plan = {'goal': '规划', 'steps': [
        {'id': 'read', 'status': 'completed', 'summary': '已查询'},
        {'id': 'plan', 'status': 'running', 'summary': ''},
    ]}
    await scope.execute('request_clarification', json.dumps(card))
    assert scope.task_plan['steps'][0]['status'] == 'completed'
    assert scope.task_plan['steps'][1]['status'] == 'blocked'


def test_conversation_preserves_valid_card_only_on_assistant_messages():
    card = local_clarification('安排一下')
    rows = _clean([{'role': role, 'content': '内容', 'clarification': card} for role in ['user', 'assistant']])
    assert 'clarification' not in rows[0]
    assert rows[1]['clarification'] == card
    assert 'clarification' not in _clean([{'role': 'assistant', 'content': '内容', 'clarification': {}}])[0]


@pytest.mark.asyncio
async def test_loop_stops_at_guidance_before_remaining_tools_in_same_batch():
    from unittest.mock import AsyncMock
    from app.ai.graph.loop import ReactLoop
    from app.ai.model.chat import ChatOutcome, ToolCallOut
    scope = ToolScope(None, 1, None, False, {}, allowed_tools=frozenset({'request_clarification', 'lookup_school_context'}))
    caller = AsyncMock(return_value=ChatOutcome(text='', tool_calls=[
        ToolCallOut(id='q', name='request_clarification', arguments=json.dumps(local_clarification('安排一下'))),
        ToolCallOut(id='late', name='lookup_school_context', arguments='{}'),
    ]))
    outcome = await ReactLoop(base_url='http://test', api_key='test', model='test', timeout=5,
        messages=[{'role': 'user', 'content': '安排一下'}], tools=scope.definitions, executor=scope.execute,
        caller=caller, stop_when=lambda: scope.clarification is not None).run()
    assert [step.tool for step in outcome.steps] == ['request_clarification']
    assert caller.await_count == 1
