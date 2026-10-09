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

from app.ai.intent.gateway import AssistantIntent, AssistantRoute, ExecutionMode, IntentDecision
from app.ai.model.store import AiProvider
from app.core.secret_store import decrypt_secret

logger = logging.getLogger(__name__)

JEV_TIMEOUT_SECONDS = 3.0

JEV_TOOL_HINTS = {
    "teachers": frozenset({"lookup_teachers"}),
    "schedule_setup": frozenset({"lookup_schedule_setup"}),
    "rules": frozenset({"lookup_rules"}),
    "generation_status": frozenset({"lookup_generation_status"}),
    "playbook": frozenset({"lookup_playbook"}),
    "walk_classes": frozenset({"lookup_walk_classes"}),
    "generation_log": frozenset({"lookup_generation_log"}),
    "subject_capacity": frozenset({"lookup_subject_capacity"}),
    "remaining_capacity": frozenset({"lookup_remaining_capacity"}),
    "slot_role_capacity": frozenset({"lookup_slot_role_capacity"}),
}


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
                    "instructions": "只选择 query 或 planning。以最新消息为准，历史用于理解省略和承接。普通问答、解释、单项查询选择 query；需要多步骤取证、全量汇总诊断、多方案比较、规划或执行选择 planning。只查询也可能复杂，问候前缀不覆盖后面的任务。行政班和走班是业务环境，不是语义模式。设置三套课时方案是规划建议，不表示修改数据库。指代不清时降低置信度，由助手先澄清。",
                    "criteria": {
                        "query": "普通问答/查询：解释功能、寒暄、单项学校数据和分页；如何修改规则属于说明",
                        "planning": "复杂规划/执行：多套方案、多步骤分析、全面审计、复杂排课诊断或实际修改请求；第二套方案的调整承接规划",
                    },
                },
                "tool": {
                    "type": "choice",
                    "instructions": "选择回答这个问题最主要需要的查询工具；如果需要多个工具或无需工具，选择 all。",
                    "criteria": {
                        "teachers": "查询教师名册、行政任课关系或班主任；走班人数与工作量用 walk_classes",
                        "walk_classes": "核对走班班数、班额、学生人数、固定任课、配置课时、已排课节及同科教师人数工作量",
                        "generation_log": "读取已有任务求解阶段和失败过程原文",
                        "subject_capacity": "验算科目课时需求与限排课位、教师并行容量",
                        "remaining_capacity": "核对班级课时需求与剩余课位",
                        "slot_role_capacity": "验算要求班主任等指定角色授课的硬规则是否有足够课时",
                        "schedule_setup": "查询课时、课位、班级或排课准备状态",
                        "rules": "查询已有排课规则或规则组",
                        "generation_status": "查询课表生成任务是否运行、失败或完成",
                        "playbook": "查询排课操作手册或页面使用步骤",
                        "all": "问题需要多个工具，或当前无法只选一个工具",
                    },
                },
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
            tool_answer = (body.get("answers") or {}).get("tool") or {}
            tool_choice = str(tool_answer.get("choice") or "all").strip().lower()
            tool_hints = JEV_TOOL_HINTS.get(tool_choice, frozenset())
            try:
                mode = ExecutionMode(choice)
                kind = AssistantIntent.GUIDE
            except ValueError:
                # Accept cached responses from the old classifier during rollout;
                # topic labels are normalized to the same two execution modes.
                try:
                    kind = AssistantIntent(choice)
                    mode = IntentDecision(kind, confidence, 'jev').effective_mode
                except ValueError:
                    logger.warning("assistant.router decision invalid provider=jev choice=%s", choice[:40])
                    return None
            if kind is AssistantIntent.UNKNOWN:
                return IntentDecision(kind, confidence, "jev", needs_clarification=True, tool_hints=tool_hints)
            logger.info(
                "assistant.router decision result provider=jev kind=%s confidence=%.3f",
                kind.value,
                confidence,
            )
            route = {
                AssistantIntent.GUIDE: AssistantRoute.AGENT,
                AssistantIntent.READINESS: AssistantRoute.AGENT,
                AssistantIntent.DIAGNOSIS: AssistantRoute.AGENT,
                AssistantIntent.CONFIGURATION: AssistantRoute.HUMAN_REVIEW,
            }.get(kind, AssistantRoute.AGENT)
            logger.info(
                "assistant.router tools provider=jev choice=%s selected=%s",
                tool_choice,
                ",".join(sorted(tool_hints)) or "all",
            )
            return IntentDecision(
                kind,
                max(0.0, min(1.0, confidence)),
                "jev",
                route=route,
                tool_hints=tool_hints,
                execution_mode=mode,
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.warning("assistant.router decision unavailable provider=jev error=%s", type(exc).__name__)
            return None
