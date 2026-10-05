"""Subject-only Page Agent pilot; provider credentials never leave the backend."""
import json
import time
import re

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from jose import JWTError
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.model.chat import (
    ChatError, _chat_url, _status_error, complete_chat_tools, resolve_chat_endpoints,
)
from app.ai.page_subjects import SubjectDraft, explicit_subject_draft, validate_subject_draft
from app.api.deps import get_current_tenant, get_current_user, require_management_user
from app.core.security import create_access_token, decode_access_token
from app.db.session import get_session
from app.models.org import Subject

router = APIRouter(prefix='/page-agent', tags=['页面操作助手'])


async def authorize(session, user, tenant_id):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, '学校与当前账号不一致')
    await require_management_user(user=user, session=session)


class PrepareIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    draft: SubjectDraft = Field(default_factory=SubjectDraft)


class IntentIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


@router.post('/intent')
async def classify_page_intent(
    body: IntentIn, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, '学校与当前账号不一致')
    try:
        endpoint = (await resolve_chat_endpoints(session, tenant_id))[0]
        outcome = await complete_chat_tools(
            base_url=endpoint.base_url, api_key=endpoint.api_key, model=endpoint.model,
            timeout=min(endpoint.timeout, 20), max_tokens=80, temperature=0,
            messages=[
                {'role': 'system', 'content': (
                    '判断用户这句话的真实意图，只返回 page_intent 工具结果。'
                    'create_subject 表示明确想在学校课程/科目系统新增一门课程，'
                    '包括只说课程或专业名称、没有使用“科目”一词的表达；'
                    '不要把查询、询问建议、假设讨论、引用他人内容误判为创建。'
                    '其他意图返回 other。只读当前这句话，不补造请求。'
                )},
                {'role': 'user', 'content': body.content},
            ],
            tools=[{'type': 'function', 'function': {
                'name': 'page_intent', 'description': '识别是否发起新增科目页面操作',
                'parameters': {'type': 'object', 'properties': {
                    'intent': {'type': 'string', 'enum': ['create_subject', 'other']},
                }, 'required': ['intent'], 'additionalProperties': False},
            }}],
        )
        calls = [call for call in outcome.tool_calls if call.name == 'page_intent']
        if len(calls) != 1:
            raise HTTPException(503, '暂时无法识别这条操作请求，请重试。')
        result = json.loads(calls[0].arguments)
        intent = result.get('intent') if result.get('intent') in ('create_subject', 'other') else 'other'
    except ChatError as exc:
        raise HTTPException(503, exc.message) from exc
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(503, '暂时无法识别这条操作请求，请重试。') from exc
    if intent == 'create_subject':
        await require_management_user(user=user, session=session)
    return {'code': 0, 'message': 'ok', 'data': {'intent': intent}}


@router.post('/subjects/prepare')
async def prepare_subject(
    body: PrepareIn, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    await authorize(session, user, tenant_id)
    try:
        draft = explicit_subject_draft(body.content, body.draft)
        if draft is None:
            endpoint = (await resolve_chat_endpoints(session, tenant_id))[0]
            outcome = await complete_chat_tools(
                base_url=endpoint.base_url, api_key=endpoint.api_key, model=endpoint.model,
                timeout=endpoint.timeout, max_tokens=700,
                messages=[
                    {'role': 'system', 'content': (
                        '你负责从新增科目请求中提取表单数据，必须调用 subject_form。'
                        '仅提取用户明确给出的内容，合并已有草稿，不猜测科目名称。'
                        'name 是科目名称，course_type 为 subject（学科课）或 activity（活动课），'
                        'evening_study_allowed 为是否允许晚自习。未提供名称用 null；'
                        '课程类型和晚自习资格未明确提供时必须返回 null，禁止使用表单默认值。'
                        '已有草稿中非 null 的字段表示用户已提供，应予保留。一次只处理一个科目；'
                        '要求多个科目时返回 name=null，请用户逐个提供。'
                    )},
                    {'role': 'user', 'content': json.dumps(
                        {'draft': body.draft.model_dump(), 'request': body.content}, ensure_ascii=False,
                    )},
                ],
                tools=[{'type': 'function', 'function': {
                    'name': 'subject_form', 'description': '提取科目表单字段',
                    'parameters': {'type': 'object', 'properties': {
                        'name': {'type': ['string', 'null']},
                        'course_type': {'type': ['string', 'null']},
                        'evening_study_allowed': {'type': ['boolean', 'null']},
                    }, 'required': ['name', 'course_type', 'evening_study_allowed'],
                        'additionalProperties': False},
                }}],
            )
            calls = [call for call in outcome.tool_calls if call.name == 'subject_form']
            if len(calls) != 1:
                raise HTTPException(422, '请一次提供一个科目的名称、课程类型和晚自习资格。')
            draft = SubjectDraft.model_validate_json(calls[0].arguments)
            if draft.name and draft.name not in body.content and draft.name != body.draft.name:
                draft.name = None
        # Do not let model-invented defaults turn an incomplete request into a
        # runnable task. Explicit choices are read from this user message.
        type_match = re.search(r'学科课|活动课', body.content)
        draft.course_type = ({'学科课': 'subject', '活动课': 'activity'}[type_match[0]]
                             if type_match else body.draft.course_type)
        evening_text = body.content.strip().rstrip('。！!')
        if '晚自习' in evening_text or evening_text in ('允许', '不允许'):
            if re.search(r'不允许|不安排|不能|不可以|禁止', evening_text):
                draft.evening_study_allowed = False
            elif re.search(r'允许|可以|能安排', evening_text):
                draft.evening_study_allowed = True
            else:
                draft.evening_study_allowed = body.draft.evening_study_allowed
        else:
            draft.evening_study_allowed = body.draft.evening_study_allowed
    except ChatError as exc:
        raise HTTPException(503, exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(422, '未能识别科目数据，请重新提供名称和课程类型。') from exc
    names = list((await session.execute(select(Subject.name).where(
        Subject.tenant_id == tenant_id,
    ))).scalars().all())
    data = validate_subject_draft(draft, names)
    if data['status'] == 'ready':
        # Scope binds subsequent model calls to this validated task and school/user.
        data['task_token'] = create_access_token(user.id, {
            'scope': 'page-agent-subject', 'tid': tenant_id, 'draft': data['draft'],
            'exp': int(time.time()) + 900,
        })
    return {'code': 0, 'message': 'ok', 'data': data}


class CompletionIn(BaseModel):
    messages: list[dict] = Field(min_length=1, max_length=80)
    tools: list[dict] = Field(default_factory=list, max_length=10)
    tool_choice: str | dict | None = None


@router.post('/chat/completions')
async def page_completion(
    body: CompletionIn, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
    task_token: str = Header(alias='X-Page-Task'),
):
    await authorize(session, user, tenant_id)
    try:
        task = decode_access_token(task_token)
    except JWTError as exc:
        raise HTTPException(403, '页面操作任务已过期，请重新提交。') from exc
    if (task.get('scope') != 'page-agent-subject' or task.get('tid') != tenant_id
            or task.get('sub') != str(user.id)):
        raise HTTPException(403, '页面操作任务不属于当前账号')
    if len(json.dumps(body.model_dump(), ensure_ascii=False)) > 160000:
        raise HTTPException(413, '页面上下文过大，请简化页面后重试')
    try:
        endpoint = (await resolve_chat_endpoints(session, tenant_id))[0]
        payload = {
            'model': endpoint.model, 'messages': [{'role': 'system', 'content':
                '只允许在科目管理页新增一个科目，禁止编辑、删除或操作其他页面。'
                '表单必须严格使用已校验数据：' + json.dumps(task['draft'], ensure_ascii=False)
            }, *body.messages], 'tools': body.tools, 'stream': False, 'max_tokens': 2048,
        }
        if body.tool_choice is not None:
            payload['tool_choice'] = body.tool_choice
        # GLM-5.3 defaults to maximum reasoning effort. This bounded form task
        # needs mild reasoning so each click does not consume the task timeout.
        if endpoint.model.lower() in ('glm-5.3', 'glm-5.3-flash'):
            payload['reasoning_effort'] = 'low'
        async with httpx.AsyncClient(timeout=min(endpoint.timeout, 120)) as client:
            response = await client.post(_chat_url(endpoint.base_url), json=payload,
                                         headers={'Authorization': f'Bearer {endpoint.api_key}'})
        if not response.is_success:
            raise _status_error(response.status_code, response.text[:400])
        return response.json()
    except ChatError as exc:
        raise HTTPException(503, exc.message) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, '页面操作模型暂时不可用，请稍后重试') from exc
