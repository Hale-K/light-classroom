"""Jev-backed bounded intent decision layer.

Jev is deliberately used only as a classifier. It never receives tool
permissions and it cannot execute business actions; low confidence or any
provider failure falls through to the local pgvector classifier.
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.intent.gateway import AssistantIntent, AssistantRoute, IntentDecision
from app.ai.model.store import AiProvider
from app.core.secret_store import decrypt_secret

logger = logging.getLogger(__name__)

JEV_TIMEOUT_SECONDS = 3.0


class JevDecisionClassifier:
    """Classify one user request through the configured tenant Jev provider."""

    async def __call__(
        self,
        session: AsyncSession | None,
        query: str,
        page_path: str | None,
        recent_turns: list[dict],
    ) -> IntentDecision | None:
        if session is None or not query.strip():
            return None
        tenant_id = session.info.get("tenant_id")
        if tenant_id is None:
            return None

        try:
            row = (
                await session.execute(
                    select(AiProvider)
                    .where(
                        AiProvider.tenant_id == tenant_id,
                        AiProvider.provider_type == "JEV",
                        AiProvider.status == 1,
                        AiProvider.chat_model.is_not(None),
                    )
                    .order_by(AiProvider.is_default.desc(), AiProvider.sort, AiProvider.id)
                    .limit(1)
                )
            )
        except Exception as exc:
            logger.warning("assistant.router decision unavailable provider=jev lookup_error=%s", type(exc).__name__)
            return None
        provider = row.scalars().first()
        if provider is None:
            return None

        api_key = decrypt_secret(provider.api_key)
        if not api_key:
            logger.info("assistant.router jev skipped reason=missing_api_key")
            return None

        base_url = provider.base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        payload = {
            "state": {
                "query": query.strip(),
                "page_path": page_path or "",
                "recent_turns": [
                    {"role": item.get("role"), "content": str(item.get("content") or "")[:500]}
                    for item in recent_turns[-4:]
                ],
            },
            "model": provider.chat_model.strip(),
            "questions": {
                "intent": {
                    "type": "choice",
                    "instructions": "选择最适合处理这条教务助手请求的意图。",
                    "criteria": {
                        "guide": "普通问答、使用说明、简单寒暄，不需要读取学校业务数据",
                        "readiness": "检查排课前置条件、教师、教室、班级、规则等是否准备完成",
                        "diagnosis": "诊断排课问题、课表冲突、资源不足或异常原因",
                        "configuration": "创建或修改排课规则、人员、空间、课表等业务配置",
                        "unknown": "无法可靠归类或需要用户补充信息",
                    },
                }
            },
        }

        logger.info("assistant.router decision provider=jev model=%s", provider.chat_model)
        try:
            async with httpx.AsyncClient(timeout=JEV_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{base_url}/systemone",
                    headers={"Accept": "application/json", "Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
            response.raise_for_status()
            body = response.json()
            answer = (body.get("answers") or {}).get("intent") or {}
            choice = str(answer.get("choice") or "").strip().lower()
            confidence = float(answer.get("confidence") or 0.0)
            try:
                kind = AssistantIntent(choice)
            except ValueError:
                logger.warning("assistant.router decision invalid provider=jev choice=%s", choice[:40])
                return None
            if kind is AssistantIntent.UNKNOWN:
                return IntentDecision(kind, confidence, "jev", needs_clarification=True)
            logger.info(
                "assistant.router decision result provider=jev kind=%s confidence=%.3f",
                kind.value,
                confidence,
            )
            route = {
                AssistantIntent.GUIDE: AssistantRoute.AGENT,
                AssistantIntent.READINESS: AssistantRoute.SUPERVISOR,
                AssistantIntent.DIAGNOSIS: AssistantRoute.SUPERVISOR,
                AssistantIntent.CONFIGURATION: AssistantRoute.HUMAN_REVIEW,
            }.get(kind, AssistantRoute.AGENT)
            return IntentDecision(kind, max(0.0, min(1.0, confidence)), "jev", route=route)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning("assistant.router decision unavailable provider=jev error=%s", type(exc).__name__)
            return None
