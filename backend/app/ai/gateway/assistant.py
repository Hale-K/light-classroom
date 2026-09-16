"""Application boundary for assistant conversations, turns, and durable runs."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.agent.assistant_agent import AssistantTurn, handle_assistant_turn
from app.ai.conversations import (
    compact_for_chat,
    conversation_view,
    delete_conversation,
    get_conversation,
    project_messages,
    project_state,
    project_summary,
    sync_conversation,
)
from app.ai.memory import memory_context, remember_messages
from app.ai.runs import create_run, get_run, spawn_run, steer_run
from app.ai.runs.service import RUN_TIMEOUT

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AssistantRequest:
    """Transport-independent input accepted by the assistant application boundary."""

    messages: list[dict]
    page_title: str | None = None
    page_path: str | None = None
    page_context: dict = field(default_factory=dict)
    can: list[str] = field(default_factory=list)
    cannot: list[str] = field(default_factory=list)
    message_id: str | None = None


class AssistantGateway:
    """Coordinates assistant use cases without exposing HTTP models to the runtime."""

    @staticmethod
    def _project_turns(messages: list[dict]) -> list[dict]:
        candidates: list[dict] = []
        for item in messages[-24:]:
            content = compact_for_chat(str(item.get("content") or ""))
            if not content:
                continue
            candidates.append({
                "role": item.get("role") if item.get("role") in ("user", "assistant") else "user",
                "content": content,
                "model_visible": item.get("model_visible", True),
            })
        return project_messages(candidates, limit=20, token_budget=6000)

    async def read_conversation(self, session: AsyncSession, tenant_id: int, user_id: int) -> dict:
        return conversation_view(await get_conversation(session, tenant_id, user_id))

    async def save_conversation(
        self, session: AsyncSession, tenant_id: int, user_id: int, messages: list[dict],
    ) -> dict:
        row = await sync_conversation(session, tenant_id, user_id, messages)
        return conversation_view(row)

    async def clear_conversation(self, session: AsyncSession, tenant_id: int, user_id: int) -> dict:
        await delete_conversation(session, tenant_id, user_id)
        return {"cleared": True}

    async def chat(
        self,
        session: AsyncSession,
        tenant_id: int,
        user_id: int,
        request: AssistantRequest,
        *,
        can_manage_rules: bool,
    ) -> AssistantTurn:
        turns = self._project_turns(request.messages)
        logger.info(
            "assistant.gateway chat.start id=%s tenant=%s user=%s path=%s turns=%s",
            request.message_id or "-", tenant_id, user_id, request.page_path, len(turns),
        )
        async with asyncio.timeout(RUN_TIMEOUT):
            result = await handle_assistant_turn(
                session,
                tenant_id,
                turns,
                page_title=request.page_title,
                page_path=request.page_path,
                can=request.can,
                cannot=request.cannot,
                message_id=request.message_id,
                user_id=user_id,
                can_manage_rules=can_manage_rules,
                page_context=request.page_context,
            )
        logger.info(
            "assistant.gateway chat.done id=%s chars=%s",
            request.message_id or "-", len(result.text),
        )
        return result

    async def start_run(
        self,
        session: AsyncSession,
        tenant_id: int,
        user_id: int,
        request_id: str,
        request: AssistantRequest,
    ) -> dict:
        await remember_messages(session, tenant_id, user_id, request.messages)
        payload = {
            "messages": request.messages,
            "page_title": request.page_title,
            "page_path": request.page_path,
            "page_context": request.page_context,
            "can": request.can,
            "cannot": request.cannot,
            "message_id": request.message_id,
        }
        conversation = await get_conversation(session, tenant_id, user_id)
        payload["memory_summary"] = project_summary(conversation.summary if conversation else "")
        latest_query = str(request.messages[-1].get("content") or "") if request.messages else ""
        long_term = await memory_context(session, tenant_id, user_id, latest_query)
        if long_term:
            payload["memory_summary"] = "\n".join(filter(None, [
                payload["memory_summary"], "长期用户记忆：", long_term,
            ]))
        payload["context_state"] = project_state(request.messages)
        state = payload["context_state"]
        if state["latest_request"] or state["confirmed"]:
            payload["memory_summary"] = "\n".join(filter(None, [
                payload["memory_summary"],
                "会话状态：",
                f"最新请求：{state['latest_request']}",
                f"已确认：{'、'.join(state['confirmed']) or '无'}",
            ]))
        data, created = await create_run(session, request_id, tenant_id, user_id, payload)
        if created:
            spawn_run(request_id, tenant_id, user_id, payload)
        return data

    async def read_run(
        self, session: AsyncSession, tenant_id: int, user_id: int, run_id: str,
        *, cancel: bool = False,
    ) -> dict:
        return await get_run(session, run_id, tenant_id, user_id, cancel=cancel)

    async def steer(
        self, session: AsyncSession, tenant_id: int, user_id: int, run_id: str, content: str,
    ) -> dict:
        return await steer_run(session, run_id, tenant_id, user_id, content)


assistant_gateway = AssistantGateway()
