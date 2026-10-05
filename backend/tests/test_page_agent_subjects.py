from types import SimpleNamespace
import json

import httpx
import pytest
from fastapi import HTTPException

from app.api.v1 import page_agent
from app.ai.model.chat import ChatOutcome, ToolCallOut

from app.ai.page_subjects import SubjectDraft, validate_subject_draft


def test_missing_name_requires_followup():
    result = validate_subject_draft(SubjectDraft(), [])
    assert result['status'] == 'needs_input'
    assert result['missing'] == ['name', 'course_type', 'evening_study_allowed']


def test_name_alone_cannot_start_page_agent():
    result = validate_subject_draft(SubjectDraft(name='  心理  '), [])
    assert result['status'] == 'needs_input'
    assert result['missing'] == ['course_type', 'evening_study_allowed']
    assert result['draft'] == {'name': '心理', 'course_type': None, 'evening_study_allowed': None}


def test_explicit_false_is_complete_but_missing_evening_is_not():
    assert validate_subject_draft(SubjectDraft(name='心理', course_type='subject'), [])['missing'] == ['evening_study_allowed']
    assert validate_subject_draft(SubjectDraft(name='心理', course_type='subject', evening_study_allowed=False), [])['status'] == 'ready'


def test_duplicate_does_not_execute():
    assert validate_subject_draft(SubjectDraft(name='数学', course_type='subject', evening_study_allowed=False), ['数学'])['status'] == 'exists'


def test_long_name_is_rejected_before_navigation():
    result = validate_subject_draft(SubjectDraft(name='科' * 21), [])
    assert result['status'] == 'needs_input'


def test_unknown_course_type_is_not_silently_defaulted():
    result = validate_subject_draft(SubjectDraft(name='心理', course_type='未知'), [])
    assert result['status'] == 'needs_input'


def test_explicit_evening_setting_is_preserved():
    result = validate_subject_draft(SubjectDraft(name='心理', evening_study_allowed=True), [])
    assert result['draft']['evening_study_allowed'] is True


class SubjectSession:
    def __init__(self, names):
        self.names = names

    async def execute(self, statement):
        return self

    def scalars(self):
        return self

    def all(self):
        return self.names


@pytest.mark.asyncio
async def test_prepare_merges_followup_and_issues_scoped_task(monkeypatch):
    async def endpoints(*args):
        return [SimpleNamespace(base_url='http://fixture/v1', api_key='secret', model='fixture', timeout=1)]

    async def complete(**kwargs):
        assert '心理' in kwargs['messages'][-1]['content']
        return ChatOutcome(tool_calls=[ToolCallOut('1', 'subject_form',
            '{"name":"心理","course_type":"activity","evening_study_allowed":true}')])

    monkeypatch.setattr(page_agent, 'resolve_chat_endpoints', endpoints)
    monkeypatch.setattr(page_agent, 'complete_chat_tools', complete)
    result = await page_agent.prepare_subject(
        page_agent.PrepareIn(content='心理', draft=SubjectDraft(course_type='activity', evening_study_allowed=True)),
        session=SubjectSession([]), user=SimpleNamespace(id=7, tenant_id=3, role='director'), tenant_id=3,
    )
    data = result['data']
    assert data['status'] == 'ready'
    task = page_agent.decode_access_token(data['task_token'])
    assert task['scope'] == 'page-agent-subject'
    assert task['tid'] == 3
    assert task['draft']['course_type'] == 'activity'
    assert 'secret' not in str(data)


@pytest.mark.asyncio
async def test_model_defaults_cannot_complete_missing_user_choices(monkeypatch):
    async def endpoints(*args):
        return [SimpleNamespace(base_url='http://fixture/v1', api_key='secret', model='fixture', timeout=1)]

    async def complete(**kwargs):
        return ChatOutcome(tool_calls=[ToolCallOut('1', 'subject_form',
            '{"name":"心理","course_type":"subject","evening_study_allowed":false}')])

    monkeypatch.setattr(page_agent, 'resolve_chat_endpoints', endpoints)
    monkeypatch.setattr(page_agent, 'complete_chat_tools', complete)
    session = SubjectSession([])
    user = SimpleNamespace(id=7, tenant_id=3, role='director')
    first = (await page_agent.prepare_subject(page_agent.PrepareIn(content='心理'), session, user, 3))['data']
    assert first['missing'] == ['course_type', 'evening_study_allowed']
    assert 'task_token' not in first
    second = (await page_agent.prepare_subject(page_agent.PrepareIn(
        content='学科课', draft=SubjectDraft(**first['draft'])), session, user, 3))['data']
    assert second['missing'] == ['evening_study_allowed']
    assert 'task_token' not in second
    third = (await page_agent.prepare_subject(page_agent.PrepareIn(
        content='不允许晚自习', draft=SubjectDraft(**second['draft'])), session, user, 3))['data']
    assert third['status'] == 'ready'
    assert third['draft']['evening_study_allowed'] is False
    assert 'task_token' in third


@pytest.mark.asyncio
async def test_teacher_blocks_model_and_navigation(monkeypatch):
    from app.services.org import staff_roles

    async def roles(*args):
        return []

    monkeypatch.setattr(staff_roles, "get_staff_role_codes", roles)
    with pytest.raises(HTTPException) as error:
        await page_agent.prepare_subject(page_agent.PrepareIn(content='创建心理科目'),
            session=SubjectSession([]), user=SimpleNamespace(id=7, tenant_id=3, role='teacher'), tenant_id=3)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_proxy_rejects_task_from_other_school(monkeypatch):
    token = page_agent.create_access_token(7, {'scope': 'page-agent-subject', 'tid': 4})
    with pytest.raises(HTTPException) as error:
        await page_agent.page_completion(page_agent.CompletionIn(messages=[{'role': 'user', 'content': 'test'}]),
            session=SubjectSession([]), user=SimpleNamespace(id=7, tenant_id=3, role='director'), tenant_id=3, task_token=token)
    assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['configured', 'glm-5.3-flash'])
async def test_proxy_uses_server_credentials_and_preserves_tool_response(monkeypatch, model):
    async def endpoints(*args):
        return [SimpleNamespace(base_url='http://provider/v1', api_key='server-secret', model=model, timeout=1)]

    reply = {'choices': [{'finish_reason': 'tool_calls', 'message': {
        'role': 'assistant', 'tool_calls': [{'id': '1', 'type': 'function',
        'function': {'name': 'AgentOutput', 'arguments': '{}'}}],
    }}]}

    def provider(request):
        assert request.url == 'http://provider/v1/chat/completions'
        assert request.headers['Authorization'] == 'Bearer server-secret'
        payload = json.loads(request.content)
        assert payload['model'] == model
        if model == 'glm-5.3-flash':
            assert payload['reasoning_effort'] == 'low'
        else:
            assert 'reasoning_effort' not in payload
        assert payload['tool_choice']['function']['name'] == 'AgentOutput'
        assert payload['stream'] is False
        assert '心理' in payload['messages'][0]['content']
        return httpx.Response(200, json=reply)

    client_class = httpx.AsyncClient
    monkeypatch.setattr(page_agent, 'resolve_chat_endpoints', endpoints)
    monkeypatch.setattr(page_agent.httpx, 'AsyncClient',
        lambda **kwargs: client_class(transport=httpx.MockTransport(provider), **kwargs))
    token = page_agent.create_access_token(7, {'scope': 'page-agent-subject', 'tid': 3,
        'draft': {'name': '心理', 'course_type': 'subject', 'evening_study_allowed': False}})
    result = await page_agent.page_completion(page_agent.CompletionIn(
        messages=[{'role': 'user', 'content': '页面数据'}],
        tools=[{'type': 'function', 'function': {'name': 'AgentOutput'}}],
        tool_choice={'type': 'function', 'function': {'name': 'AgentOutput'}}),
        session=SubjectSession([]), user=SimpleNamespace(id=7, tenant_id=3, role='director'), tenant_id=3, task_token=token)
    assert result == reply
    assert 'server-secret' not in json.dumps(result)


@pytest.mark.asyncio
async def test_academic_director_can_prepare_without_scheduling_permission(monkeypatch):
    from app.services.org import staff_roles

    async def roles(*args):
        return ['academic_director']

    monkeypatch.setattr(staff_roles, 'get_staff_role_codes', roles)
    await page_agent.authorize(SubjectSession([]), SimpleNamespace(id=7, tenant_id=3, role='teacher'), 3)


@pytest.mark.asyncio
async def test_director_cannot_operate_other_school():
    with pytest.raises(HTTPException) as error:
        await page_agent.authorize(SubjectSession([]), SimpleNamespace(id=7, tenant_id=3, role='director'), 4)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_explicit_name_and_followup_skip_model(monkeypatch):
    async def unexpected_model(*args, **kwargs):
        pytest.fail('Explicit form input must not call the model')

    monkeypatch.setattr(page_agent, 'resolve_chat_endpoints', unexpected_model)
    monkeypatch.setattr(page_agent, 'complete_chat_tools', unexpected_model)
    session = SubjectSession([])
    user = SimpleNamespace(id=7, tenant_id=3, role='director')
    first = (await page_agent.prepare_subject(page_agent.PrepareIn(
        content='帮我新增一个校本科目，名称叫“人工智能基础”。'), session, user, 3))['data']
    assert first['draft']['name'] == '人工智能基础'
    assert first['missing'] == ['course_type', 'evening_study_allowed']
    second = (await page_agent.prepare_subject(page_agent.PrepareIn(
        content='课程类型是活动课，不允许晚自习。', draft=SubjectDraft(**first['draft'])),
        session, user, 3))['data']
    assert second['status'] == 'ready'
    assert second['draft']['evening_study_allowed'] is False
