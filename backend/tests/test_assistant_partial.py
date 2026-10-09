import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.agent.partial import blocked_plan, checked_partial
from app.ai.model.chat import ChatError


def checked_scope():
    return SimpleNamespace(checked_hour_evidence={'scope': {'academic_year': '2026-2027', 'term': '2'},
        'data': {'all_numeric_constraints_valid': True, 'scenarios': [{
            'name': '方案一', 'numeric_constraints_valid': True,
            'subjects': [{'subject': '数学', 'periods': 5, 'week_parity': 'odd'},
                {'subject': '数学', 'periods': 4, 'week_parity': 'even'},
                {'subject': '体育', 'periods': 2, 'week_parity': 'all'},
                {'subject': '音乐', 'periods': 1, 'week_parity': 'all'},
                {'subject': '心理', 'periods': 1, 'week_parity': 'all'}],
            'total_periods_by_week': {'odd': 9, 'even': 8},
            'errors': [{'code': 'UNKNOWN_SUBJECT', 'subject': '心理'}],
        }]}})


def test_partial_retains_checked_parity_and_missing_subject_without_claiming_completion():
    scope = checked_scope()
    original = deepcopy(scope.checked_hour_evidence)
    result = checked_partial(scope, '无法连接模型服务。')
    assert result['model_visible'] is False
    assert '任务未完成' in result['text'] and '数值验算记录，未实施' in result['text']
    assert '| 数学 | 5 | 4 |' in result['text']
    assert '| 合计 | 9 | 8 |' in result['text']
    assert '| 心理 | 1 | 1 |' in result['text'] and '科目目录缺失：心理' in result['text']
    assert '教师与教室冲突' in result['text']
    assert scope.checked_hour_evidence == original


def test_no_partial_from_absent_failed_or_inconsistent_evidence():
    assert checked_partial(SimpleNamespace(), '网络失败') is None
    scope = checked_scope()
    scope.checked_hour_evidence['data']['all_numeric_constraints_valid'] = False
    assert checked_partial(scope, '网络失败') is None
    scope = checked_scope()
    scope.checked_hour_evidence['data']['scenarios'][0]['total_periods_by_week']['odd'] = 99
    assert checked_partial(scope, '网络失败') is None


def test_blocked_snapshot_preserves_finished_evidence_and_does_not_mutate_plan():
    plan = {'goal': '规划', 'steps': [
        {'id': 'query', 'status': 'completed', 'summary': '已查询'},
        {'id': 'output', 'status': 'running', 'summary': ''},
        {'id': 'review', 'status': 'pending', 'summary': ''},
    ]}
    original = deepcopy(plan)
    saved = blocked_plan(plan, '模型连接失败')
    assert [item['status'] for item in saved['steps']] == ['completed', 'blocked', 'blocked']
    assert saved['steps'][0]['summary'] == '已查询'
    assert plan == original


@pytest.mark.asyncio
async def test_loop_failure_preserves_checked_result_without_restarting_or_querying(monkeypatch):
    from app.ai.agent.agent_loop import run_agent_loop
    from app.ai.harness.router import PLANNING_HARNESS
    monkeypatch.setattr('app.ai.agent.agent_loop.build_agent_messages_for_turn', lambda *args, **kwargs: [{'role': 'user', 'content': '规划'}])
    scope = checked_scope()
    scope.task_plan = {'steps': [{'id': 'final', 'status': 'pending'}]}
    scope.definitions = []
    scope.execute = AsyncMock()
    scope.plan = None
    gateway = SimpleNamespace(complete_tools=AsyncMock(side_effect=ChatError('网络失败', 'network')))
    arguments = dict(base_url='http://test', api_key='', model='test', timeout=10,
        on_progress=None, on_trace=None, on_step=None, model_gateway=gateway,
        tool_scope=scope, harness=PLANNING_HARNESS, page_title=None, page_path=None,
        can=None, cannot=None, page_context=None, retrieved='')
    with pytest.raises(ChatError) as error:
        await run_agent_loop([], '', **arguments)
    assert error.value.error_class == 'network'
    assert '| 心理 | 1 | 1 |' in error.value.partial_result['text']
    assert error.value.partial_task_plan['steps'][0]['status'] == 'blocked'
    assert gateway.complete_tools.await_count == 1
    scope.execute.assert_not_awaited()
    gateway.complete_tools.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await run_agent_loop([], '', **arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel_first', [False, True])
async def test_failed_run_keeps_partial_but_a_prior_cancel_wins(monkeypatch, cancel_first):
    from app.ai.runs import service
    state = {'status': 'running', 'result': None}
    row = SimpleNamespace(events=[])
    writes = []

    class Database:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def execute(self, statement):
            if statement.is_select:
                return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: row))
            values = statement.compile().params
            writes.append(values)
            assert values['status_1'] == 'running', 'Late failure must only persist over running status'
            if state['status'] != 'running':
                return SimpleNamespace(rowcount=0)
            state.update({key: value for key, value in values.items() if key in {'status', 'result', 'checkpoint'}})
            return SimpleNamespace(rowcount=1)

        async def commit(self):
            return None

    async def failed_handler(*args, **kwargs):
        if cancel_first:
            state['status'] = 'cancelled'
        error = ChatError('模型连接失败', 'network')
        error.partial_result = checked_partial(checked_scope(), error.message)
        error.partial_task_plan = blocked_plan({'steps': [{'id': 'output', 'status': 'pending'}]}, error.message)
        raise error

    monkeypatch.setattr('app.api.deps.get_user_permission_codes', AsyncMock(return_value=[]))
    monkeypatch.setattr('app.ai.agent.assistant_agent.handle_assistant_turn', failed_handler)
    await service.execute_run('a' * 32, 1, 1, {'messages': [{'role': 'user', 'content': '规划'}]}, sessions=Database)
    assert writes[-1]['status'] == 'failed'
    if cancel_first:
        assert state['status'] == 'cancelled' and state['result'] is None
    else:
        assert state['status'] == 'failed'
        assert '任务未完成' in state['result']['text']
        assert state['checkpoint']['plan']['steps'][0]['status'] == 'blocked'
