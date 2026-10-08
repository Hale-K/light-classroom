"""轻课堂助手对话。"""
from __future__ import annotations

from typing import Literal

import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from pydantic import BaseModel, Field, model_validator
from app.ai.attachments import MAX_FILE_BYTES, MAX_TEXT_CHARS, MAX_CONTEXT_CHARS, parse_attachment
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.actions import decide_action
from app.ai.gateway.assistant import AssistantRequest, assistant_gateway
from app.api.deps import get_current_tenant, get_current_user, get_user_permission_codes
from app.db.session import get_session
from app.models.enums import BaseUserRole
from app.ai.runs.models import AiRun
from app.ai.runs.service import run_view

router = APIRouter(prefix="/assistant", tags=["轻课堂助手"])


class ChatTurn(BaseModel):
    role: str
    content: str
    model_visible: bool = True


class ReferenceMaterial(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    truncated: bool = False
    original_chars: int | None = Field(default=None, ge=0)
    analysis: str = Field(default='', max_length=4000)


class PageContext(BaseModel):
    assistant_mode: Literal['standard', 'plan'] = 'standard'
    reference_materials: list[ReferenceMaterial] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def limit_materials(self):
        if sum(len(item.text) for item in self.reference_materials) > MAX_CONTEXT_CHARS:
            raise ValueError('附件内容合计超过 24000 字，请减少附件')
        return self

    knowledge_base_id: int | None = Field(default=None, ge=1)
    academic_year: str | None = Field(default=None, max_length=20)
    term: str | None = Field(default=None, max_length=20)
    class_id: int | None = Field(default=None, ge=1)
    class_name: str | None = Field(default=None, max_length=100)
    rule_group_id: str | None = Field(default=None, max_length=80)
    rule_group_name: str | None = Field(default=None, max_length=100)
    job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class ChatIn(BaseModel):
    messages: list[ChatTurn] = Field(min_length=1, max_length=24)
    page_title: str | None = None
    page_path: str | None = None
    page_context: PageContext = Field(default_factory=PageContext)
    can: list[str] = Field(default_factory=list)
    cannot: list[str] = Field(default_factory=list)
    message_id: str | None = None


class ConversationIn(BaseModel):
    messages: list[ChatTurn] = Field(default_factory=list, max_length=60)


@router.post('/attachments/read', summary='读取本轮助手附件，不写入文件中心或知识库')
async def read_assistant_attachment(
    file: UploadFile = File(...), user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    try:
        if user.tenant_id != tenant_id:
            raise HTTPException(403, '学校与当前账号不一致')
        data = await file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, '每个附件不能超过 5 MB')
        try:
            material = await asyncio.to_thread(parse_attachment, file.filename or '', data)
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise HTTPException(422, str(exc)) from None
            raise HTTPException(422, '文档无法读取，请检查格式或换用 TXT、CSV') from None
        return {'code': 0, 'message': 'ok', 'data': material}
    finally:
        await file.close()


def _assistant_request(body: ChatIn) -> AssistantRequest:
    return AssistantRequest(
        messages=[item.model_dump() for item in body.messages],
        page_title=body.page_title,
        page_path=body.page_path,
        page_context=body.page_context.model_dump(exclude_none=True),
        can=body.can,
        cannot=body.cannot,
        message_id=body.message_id,
    )


@router.get("/conversation", summary="读取当前用户的助手会话")
async def read_assistant_conversation(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, "学校与当前账号不一致")
    data = await assistant_gateway.read_conversation(session, tenant_id, user.id)
    return {"code": 0, "message": "ok", "data": data}


@router.put("/conversation", summary="同步当前用户的助手会话")
async def save_assistant_conversation(
    body: ConversationIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, "学校与当前账号不一致")
    messages = [item.model_dump() for item in body.messages]
    data = await assistant_gateway.save_conversation(session, tenant_id, user.id, messages)
    return {"code": 0, "message": "ok", "data": data}


@router.delete("/conversation", summary="开始新的助手会话")
async def clear_assistant_conversation(
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, "学校与当前账号不一致")
    data = await assistant_gateway.clear_conversation(session, tenant_id, user.id)
    return {"code": 0, "message": "ok", "data": data}


class ActionDecision(BaseModel):
    decision: Literal["confirm", "cancel"]


class RunIn(ChatIn):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class SteerIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


@router.post("/runs", summary="提交可恢复查看的助手任务")
async def start_assistant_run(
    body: RunIn, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, "学校与当前账号不一致")
    data = await assistant_gateway.start_run(
        session, tenant_id, user.id, body.request_id, _assistant_request(body),
    )
    return {"code": 0, "message": "ok", "data": data}


@router.get("/runs/{run_id}", summary="查看助手真实进展和结果")
async def read_assistant_run(
    run_id: str, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    data = await assistant_gateway.read_run(session, tenant_id, user.id, run_id)
    return {"code": 0, "message": "ok", "data": data}


@router.post("/runs/{run_id}/steer", summary="调整运行中助手任务的方向")
async def steer_assistant_run(
    run_id: str, body: SteerIn, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, "学校与当前账号不一致")
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "调整内容不能为空")
    data = await assistant_gateway.steer(session, tenant_id, user.id, run_id, content)
    return {"code": 0, "message": "ok", "data": data}


@router.get("/runs/{run_id}/stream", summary="通过 SSE 实时订阅助手任务")
async def stream_assistant_run(
    run_id: str, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, "学校与当前账号不一致")
    current_user_id = user.id

    async def events():
        cursor = 0
        while True:
            run = (await session.execute(select(AiRun).where(
                AiRun.id == run_id, AiRun.tenant_id == tenant_id, AiRun.user_id == current_user_id,
            ).execution_options(populate_existing=True))).scalars().first()
            if run is None:
                yield "event: error\ndata: {\"message\":\"未找到本账号的助手任务\"}\n\n"
                return
            view = run_view(run)
            # End the read transaction before sleeping so every open SSE stream does
            # not reserve a PostgreSQL connection for the lifetime of the task.
            await session.rollback()
            items = view["events"]
            for event in items[cursor:]:
                yield f"id: {cursor + 1}\nevent: run.event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                cursor += 1
            status_view = {
                k: view[k] for k in (
                    "id", "status", "phase", "message", "result", "elapsed_seconds",
                    "phase_elapsed_seconds", "heartbeat_at", "events",
                    "execution",
                )
            }
            yield f"event: run.status\ndata: {json.dumps(status_view, ensure_ascii=False)}\n\n"
            if view["status"] not in {"queued", "running"}:
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@router.get("/runs/{run_id}/trace", summary="查看助手诊断轨迹（学校管理员）")
async def read_assistant_run_trace(
    run_id: str, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, "学校与当前账号不一致")
    if user.role != BaseUserRole.director:
        raise HTTPException(403, "仅学校管理员可查看助手诊断轨迹")
    from app.ai.runs.service import get_run_trace
    return {"code": 0, "message": "ok", "data": await get_run_trace(session, run_id, tenant_id)}


@router.post("/runs/{run_id}/cancel", summary="取消助手处理，不取消已提交的排课生成任务")
async def cancel_assistant_run(
    run_id: str, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    data = await assistant_gateway.read_run(session, tenant_id, user.id, run_id, cancel=True)
    return {"code": 0, "message": "ok", "data": data}


@router.post("/actions/{action_id}", summary="确认或取消助手规则草稿")
async def assistant_action(
    action_id: str,
    body: ActionDecision,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, "学校与当前账号不一致")
    if body.decision == "confirm":
        permissions = await get_user_permission_codes(session, user.id)
        if "scheduling:assign" not in permissions:
            raise HTTPException(403, "需要排课配置权限，请联系教务管理员")
    data = await decide_action(session, tenant_id, user.id, action_id, body.decision)
    return {"code": 0, "message": "ok", "data": data}
