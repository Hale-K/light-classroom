"""轻课堂助手对话。"""
from __future__ import annotations

import logging
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.agent.teacher import handle_teacher_turn
from app.ai.actions import decide_action
from app.ai.model.chat import ChatError
from app.api.deps import get_current_tenant, get_current_user, get_user_permission_codes
from app.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["轻课堂助手"])


class ChatTurn(BaseModel):
    role: str
    content: str


class PageContext(BaseModel):
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


@router.post("/chat", summary="助手对话")
async def assistant_chat(
    body: ChatIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, "学校与当前账号不一致")
    turns: list[dict] = []
    for item in body.messages[-20:]:
        role = item.role if item.role in ("user", "assistant") else "user"
        text = (item.content or "").strip()[:4000]
        if text:
            turns.append({"role": role, "content": text})
    try:
        logger.info(
            "assistant.chat start id=%s tenant=%s user=%s path=%s turns=%s",
            body.message_id or "-",
            tenant_id,
            getattr(user, "id", None),
            body.page_path,
            len(turns),
        )
        permissions = await get_user_permission_codes(session, user.id)
        async with asyncio.timeout(100):
            turn = await handle_teacher_turn(
                session,
                tenant_id,
                turns,
                page_title=body.page_title,
                page_path=body.page_path,
                can=body.can,
                cannot=body.cannot,
                message_id=body.message_id,
                user_id=user.id,
                can_manage_rules="scheduling:assign" in permissions,
                page_context=body.page_context.model_dump(exclude_none=True),
            )
    except TimeoutError as exc:
        raise HTTPException(504, "本轮处理超时，请重试或把要求拆成几条；未执行规则写入") from exc
    except ChatError as exc:
        logger.warning("assistant.chat fail id=%s err=%s", body.message_id or "-", exc.message)
        raise HTTPException(status_code=400, detail=exc.message) from exc
    logger.info("assistant.chat done id=%s chars=%s", body.message_id or "-", len(turn.text))
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "text": turn.text,
            "message_id": body.message_id,
            "think": turn.think,
            "choices": turn.choices,
            "plan": turn.plan,
        },
    }


class ActionDecision(BaseModel):
    decision: Literal["confirm", "cancel"]


class RunIn(ChatIn):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")


@router.post("/runs", summary="提交可恢复查看的助手任务")
async def start_assistant_run(
    body: RunIn, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    from app.ai.runs import create_run, spawn_run
    if user.tenant_id != tenant_id:
        raise HTTPException(403, "学校与当前账号不一致")
    payload = body.model_dump(exclude={"request_id"})
    data, created = await create_run(session, body.request_id, tenant_id, user.id, payload)
    if created:
        spawn_run(body.request_id, tenant_id, user.id, payload)
    return {"code": 0, "message": "ok", "data": data}


@router.get("/runs/{run_id}", summary="查看助手真实进展和结果")
async def read_assistant_run(
    run_id: str, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    from app.ai.runs import get_run
    data = await get_run(session, run_id, tenant_id, user.id)
    return {"code": 0, "message": "ok", "data": data}


@router.post("/runs/{run_id}/cancel", summary="取消助手处理，不取消已提交的排课生成任务")
async def cancel_assistant_run(
    run_id: str, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    from app.ai.runs import get_run
    data = await get_run(session, run_id, tenant_id, user.id, cancel=True)
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
