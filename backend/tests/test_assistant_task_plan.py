import json
import pytest
from app.ai.tools.task_plan import execute_task_plan
from app.ai.gateway.tool import ToolScope


def test_plan_preserves_evidence_and_requires_summary_for_terminal_states():
    raw, plan = execute_task_plan('plan_task', json.dumps({'goal': '查证与验算', 'steps': [
        {'id': 'basis', 'label': '取得课位'}, {'id': 'verify', 'label': '验算方案'}]}), None)
    assert json.loads(raw)['ok']
    denied, unchanged = execute_task_plan('plan_task', '{}', plan)
    assert not json.loads(denied)['ok'] and unchanged == plan
    denied, _ = execute_task_plan('update_plan_task', '{"task_id":"basis","status":"completed"}', plan)
    assert not json.loads(denied)['ok']
    raw, _ = execute_task_plan('update_plan_task', '{"task_id":"basis","status":"completed","summary":"年级正式课位40"}', plan)
    assert json.loads(raw)['ok'] and plan['steps'][0]['summary'] == '年级正式课位40'


@pytest.mark.asyncio
async def test_unfinished_plan_is_not_published_as_complete_and_blocked_can_end():
    scope = ToolScope(None, 1, 1, False, None,
        allowed_tools=frozenset({'plan_task', 'update_plan_task'}))
    await scope.execute('plan_task', '{"goal":"规划","steps":[{"id":"verify","label":"验算"}]}')
    assert await scope.final_guard('方案已完成')
    await scope.execute('update_plan_task', '{"task_id":"verify","status":"blocked","summary":"年级未保存课位，不能核实容量"}')
    assert await scope.final_guard('需要先保存课位结构') is None


@pytest.mark.asyncio
async def test_numeric_multi_scenarios_need_programmatic_check():
    scope = ToolScope(None, 1, 1, False, None, allowed_tools=frozenset({'plan_task', 'update_plan_task'}))
    await scope.execute('plan_task', '{"goal":"形成课时建议","steps":[{"id":"request","label":"整理需求"}]}')
    await scope.execute('update_plan_task', '{"task_id":"request","status":"completed","summary":"已确认需要多个课时方案；课量数字尚未验算"}')
    answer = '方案一课时\n| 科目 | 节数 |\n| 数学 | 7 |'
    assert '验算' in await scope.final_guard(answer)
    assert await scope.final_guard('请确认要规划的年级') is None
