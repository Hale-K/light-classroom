"""单个模型端点的 Agent 调用适配。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.agent.models import AssistantTurn
from app.ai.harness import HarnessProfile
from app.ai.model.chat import ChatEndpoint
from app.ai.runs.events import TraceCallback
from app.ai.runs.progress import Progress
from app.ai.runtime import AssistantRuntime


async def invoke_agent(
    endpoint: ChatEndpoint, *, session: AsyncSession, tenant_id: int,
    turns: list[dict], page_title: str | None, page_path: str | None,
    user_id: int | None, can_manage_rules: bool, can: list[str] | None,
    cannot: list[str] | None, on_progress: Progress | None,
    page_context: dict | None, memory_summary: str,
    on_trace: TraceCallback | None, runtime: AssistantRuntime,
    on_step: Callable[[int], Awaitable[list[dict]]] | None,
    harness: HarnessProfile, retrieved: str,
    provider_endpoints: list[ChatEndpoint] | None = None,
) -> AssistantTurn:
    # 延迟导入避免入口模块与调用适配器形成循环依赖。
    from app.ai.agent.assistant_agent import agent_reply

    return await agent_reply(
        session, tenant_id, turns, base_url=endpoint.base_url,
        api_key=endpoint.api_key, model=endpoint.model, timeout=endpoint.timeout,
        max_tokens=endpoint.max_output_tokens,
        page_title=page_title, page_path=page_path, can=can, cannot=cannot,
        user_id=user_id, can_manage_rules=can_manage_rules,
        on_progress=on_progress, page_context=page_context,
        memory_summary=memory_summary, on_trace=on_trace, runtime=runtime,
        on_step=on_step, harness=harness, retrieved=retrieved,
        provider_endpoints=provider_endpoints,
    )
