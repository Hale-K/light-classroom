"""轻课堂助手对话。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.chat import ChatError, assistant_reply
from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session

router = APIRouter(prefix="/assistant", tags=["轻课堂助手"])


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    messages: list[ChatTurn] = Field(min_length=1, max_length=24)
    page_title: str | None = None
    page_path: str | None = None
    can: list[str] = Field(default_factory=list)
    cannot: list[str] = Field(default_factory=list)


@router.post("/chat", summary="助手对话")
async def assistant_chat(
    body: ChatIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    turns: list[dict] = []
    for item in body.messages[-20:]:
        role = item.role if item.role in ("user", "assistant") else "user"
        text = (item.content or "").strip()[:4000]
        if text:
            turns.append({"role": role, "content": text})
    try:
        reply = await assistant_reply(
            session,
            tenant_id,
            turns,
            page_title=body.page_title,
            page_path=body.page_path,
            can=body.can,
            cannot=body.cannot,
        )
    except ChatError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return {"code": 0, "message": "ok", "data": {"text": reply}}
