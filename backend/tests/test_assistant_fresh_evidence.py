import json
from unittest.mock import AsyncMock

import pytest

from app.ai.gateway.tool import ToolScope


@pytest.mark.asyncio
async def test_repeated_personal_timetable_question_requires_current_authorized_query(monkeypatch):
    scope = ToolScope(object(), 1, 1, True, {})
    scope.configure_request('只查询学生个人保存课表，有几条？')
    answer = '已查询，共6条记录。'
    assert '历史回复' in await scope.final_guard(answer)
    monkeypatch.setattr('app.ai.gateway.tool.evidence.authorized', AsyncMock(return_value=True))
    query = AsyncMock(return_value=json.dumps({'ok': True, 'data': {'total': 6}}))
    monkeypatch.setattr('app.ai.gateway.tool.execute_school_tool', query)
    await scope.execute('lookup_timetable', '{}')
    assert await scope.final_guard(answer) is None
    query.assert_awaited_once()


@pytest.mark.asyncio
async def test_permission_failure_can_explain_blocker_but_cannot_claim_old_counts(monkeypatch):
    scope = ToolScope(object(), 1, 1, False, {})
    scope.configure_request('查询个人课表')
    monkeypatch.setattr('app.ai.gateway.tool.evidence.authorized', AsyncMock(return_value=False))
    result = json.loads(await scope.execute('lookup_timetable', '{}'))
    assert result['code'] == 'FORBIDDEN'
    assert await scope.final_guard('当前账号没有查询权限，请由教务管理员查询。') is None
    assert await scope.final_guard('已查询，当前账号没有权限，但上次共6条。')


@pytest.mark.asyncio
async def test_denied_query_cannot_reuse_invented_navigation_from_history(monkeypatch):
    scope = ToolScope(object(), 1, 1, False, {})
    scope.configure_request('查询学生选科和入班明细')
    monkeypatch.setattr('app.ai.gateway.tool.evidence.authorized', AsyncMock(return_value=False))
    await scope.execute('lookup_student_choices', '{}')
    assert await scope.final_guard('没有权限，可在排课菜单的学生选科页面查看明细。')
    assert await scope.final_guard('没有权限，请在设置账号管理页面核对角色。')
    assert await scope.final_guard('当前账号缺少教务管理权限，请联系本校管理员核对账号。') is None


@pytest.mark.asyncio
async def test_query_stops_after_actual_permission_denial_without_another_model_request(monkeypatch):
    from types import SimpleNamespace
    from app.ai.agent.agent_loop import run_agent_loop
    from app.ai.harness.router import QUERY_HARNESS
    from app.ai.model.chat import ChatOutcome, ToolCallOut

    scope = ToolScope(object(), 1, 1, False, {})
    scope.configure_request('查询学生选科和入班明细')
    monkeypatch.setattr('app.ai.gateway.tool.evidence.authorized', AsyncMock(return_value=False))
    monkeypatch.setattr(ToolScope, 'environment', AsyncMock(return_value={'ok': True, 'data': {}}))
    gateway = SimpleNamespace(complete_tools=AsyncMock(return_value=ChatOutcome(tool_calls=[
        ToolCallOut(id='denied', name='lookup_student_choices', arguments='{}')])))
    outcome = await run_agent_loop([{'role': 'user', 'content': '查询学生选科'}], '',
        base_url='http://test', api_key='', model='test', timeout=10,
        on_progress=None, on_trace=None, on_step=None, model_gateway=gateway,
        tool_scope=scope, harness=QUERY_HARNESS, page_title=None, page_path=None,
        can=None, cannot=None, page_context=None, retrieved='')
    gateway.complete_tools.assert_awaited_once()
    assert '缺少教务管理权限' in outcome.text and '菜单' not in outcome.text
    assert len(outcome.steps) == 1


@pytest.mark.asyncio
async def test_lookup_failure_can_request_full_identity_without_repeating_same_failed_query(monkeypatch):
    scope = ToolScope(object(), 1, 1, True, {})
    scope.configure_request('查个人保存课表')
    monkeypatch.setattr('app.ai.gateway.tool.evidence.authorized', AsyncMock(return_value=True))
    monkeypatch.setattr('app.ai.gateway.tool.execute_school_tool', AsyncMock(return_value=json.dumps({'ok': False, 'code': 'MISSING_SCOPE'})))
    await scope.execute('lookup_timetable', '{}')
    assert await scope.final_guard('姓名未唯一匹配，请补充完整姓名或学号。') is None
