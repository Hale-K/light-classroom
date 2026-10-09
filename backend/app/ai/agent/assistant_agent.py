"""Two-mode school assistant with one evidence context per task."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import cast

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.agent.agent_loop import run_agent_loop
from app.ai.agent.invocation import invoke_agent
from app.ai.agent.models import AssistantTurn
from app.ai.agent.context import blocked_destructive_request, last_user_message
from app.ai.conversations import project_messages, project_summary
from app.ai.consultation import consultation_reply
from app.ai.gateway import ModelGatewayService, ToolGatewayService
from app.ai.guide import fast_reply as _local_fast_reply
from app.ai.guide import rule_jumps
from app.ai.harness import HarnessProfile, HarnessRouterService
from app.ai.harness.router import apply_assistant_mode
from app.ai.intent import IntentGatewayService
from app.ai.model.chat import ChatEndpoint, ChatError
from app.ai.resilience import provider_circuits
from app.ai.runs.events import TraceCallback
from app.ai.runs.progress import Progress, report_progress
from app.ai.runtime import AssistantRuntime

logger = logging.getLogger(__name__)



# 意图确实无法归类时的本地澄清话术；不预设用户在报错，避免答非所问的观感。
CLARIFY_REPLY = "你具体想处理什么问题？可以说明要查的数据或想做的操作，也可以附上相关文件，我再帮你核对。"
async def agent_reply(
    session: AsyncSession,
    tenant_id: int,
    turns: list[dict],
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    max_tokens: int = 8192,
    page_title: str | None = None,
    page_path: str | None = None,
    user_id: int | None = None,
    can_manage_rules: bool = False,
    can: list[str] | None = None,
    cannot: list[str] | None = None,
    on_progress: Progress | None = None,
    page_context: dict | None = None,
    memory_summary: str = "",
    on_trace: TraceCallback | None = None,
    runtime: AssistantRuntime | None = None,
    on_step: Callable[[int], Awaitable[list[dict]]] | None = None,
    harness: HarnessProfile | None = None,
    retrieved: str = "",
    provider_endpoints: list[ChatEndpoint] | None = None,
) -> AssistantTurn:
    """模型查本校数据或生成一份待确认草稿；草稿成功后直接返回可信卡片。"""

    runtime = runtime or AssistantRuntime(
        on_progress=on_progress,
        on_trace=on_trace,
        circuits=provider_circuits,
    )
    if harness is None:
        if session is not None:
            session.info["tenant_id"] = tenant_id
        last_user = last_user_message(turns)
        decision = await cast(
            IntentGatewayService, runtime.service("intent_gateway")
        ).classify(
            session, last_user, page_path=page_path, recent_turns=turns,
        )
        harness = cast(HarnessRouterService, runtime.service("harness_router")).select(decision)
    harness = apply_assistant_mode(harness, page_context)
    model_gateway = cast(ModelGatewayService, runtime.service("model_gateway"))
    tool_gateway = cast(ToolGatewayService, runtime.service("tool_gateway"))
    tool_scope = tool_gateway.open_scope(
        session=session,
        tenant_id=tenant_id,
        user_id=user_id,
        can_manage_rules=can_manage_rules,
        page_context=page_context,
        allowed_tools=harness.allowed_tools,
        on_trace=on_trace,
    )
    configure_request = getattr(tool_scope, 'configure_request', None)
    if callable(configure_request):
        configure_request(last_user_message(turns))

    outcome = await run_agent_loop(
            turns, memory_summary, base_url=base_url, api_key=api_key,
            model=model, timeout=timeout, on_progress=on_progress,
            max_tokens=max_tokens,
            on_trace=on_trace, on_step=on_step, model_gateway=model_gateway,
            tool_scope=tool_scope, harness=harness, page_title=page_title,
            page_path=page_path, can=can, cannot=cannot,
            page_context=page_context, retrieved=retrieved,
            provider_endpoints=provider_endpoints,
    )
    logger.info("assistant.agent tools=%s", ",".join(s.tool for s in outcome.steps) or "-")
    plan = tool_scope.plan
    last_user = last_user_message(turns)
    guide = runtime.service("ui_guide") if runtime else None
    jumps = [] if plan or (harness.name == 'planning' and 'propose_rules' not in harness.allowed_tools) else (
        guide.rule_jumps(last_user, outcome.text, page_path) if guide else rule_jumps(last_user, outcome.text, page_path))
    step_lines = [f"{step.tool}：{step.detail}" for step in outcome.steps]
    return AssistantTurn(
        text="规则草稿已准备，请核对下方内容后确认。" if plan else outcome.text,
        think=step_lines,
        plan=plan,
        jumps=jumps,
    )


async def handle_assistant_turn(
    session: AsyncSession,
    tenant_id: int,
    turns: list[dict],
    *,
    page_title: str | None = None,
    page_path: str | None = None,
    user_id: int | None = None,
    can_manage_rules: bool = False,
    can: list[str] | None = None,
    cannot: list[str] | None = None,
    message_id: str | None = None,
    on_progress: Progress | None = None,
    page_context: dict | None = None,
    memory_summary: str = "",
    on_trace: TraceCallback | None = None,
    runtime: AssistantRuntime | None = None,
    on_step: Callable[[int], Awaitable[list[dict]]] | None = None,
) -> AssistantTurn:
    turns = project_messages(turns, limit=20)
    memory_summary = project_summary(memory_summary)
    if not turns:
        raise ChatError("请输入内容")
    last = turns[-1]
    query = last_user_message(turns)
    runtime = runtime or AssistantRuntime(
        on_progress=on_progress, on_trace=on_trace, circuits=provider_circuits,
    )
    # The shared intent gateway is tenant-agnostic; expose the current tenant
    # only through this request-scoped SQLAlchemy session for Jev lookup.
    if session is not None:
        session.info["tenant_id"] = tenant_id
    if (
        last.get("role") == "user"
        and blocked_destructive_request(str(last.get("content") or ""))
    ):
        logger.warning("assistant.blocked_destructive_request tenant=%s user=%s", tenant_id, user_id)
        return AssistantTurn(
            text=(
                "这个请求涉及删除数据库或批量清空数据，助手不会执行。"
                "若要处理具体数据，请说明业务对象和范围，由管理员在对应页面人工操作。"
            )
        )
    has_materials = bool((page_context or {}).get("reference_materials"))
    plan_mode = (page_context or {}).get('assistant_mode') == 'plan'
    fixed_consultation = None if has_materials or plan_mode else consultation_reply(query)
    if fixed_consultation:
        return AssistantTurn(text=fixed_consultation)
    # 本地问候是按“最新一条用户消息”判断的。对话带有历史时，重复问候
    # 仍然不需要经过意图分类、向量检索和模型调用，否则简单的“你好”会被
    # 历史上下文拖进完整 Agent 流程。
    if last.get("role") == "user" and not has_materials:
        guide = runtime.service("ui_guide")
        fixed = guide.local_reply(str(last.get("content") or ""), page_path)
        if fixed:
            logger.info("assistant.turn local id=%s", message_id or "-")
            return AssistantTurn(text=fixed)
    decision = await cast(
        IntentGatewayService, runtime.service("intent_gateway")
    ).classify(
        session, query, page_path=page_path, recent_turns=turns,
    )
    await runtime.emit("intent.classified", decision.trace_data())
    # 分类器拿不准时才本地澄清。本轮带附件或处于计划模式时，问题已有明确的
    # 分析对象（材料和页面上下文已注入 LLM 消息），兜底反问只会答非所问；
    # 只读 harness 的指令本就要求模型在范围不明时自行追问。
    if decision.needs_clarification and not has_materials and not plan_mode:
        logger.info(
            "assistant.turn clarify id=%s kind=%s source=%s confidence=%.2f",
            message_id or "-", decision.kind.value, decision.source, decision.confidence,
        )
        return AssistantTurn(text=CLARIFY_REPLY)
    harness = cast(HarnessRouterService, runtime.service("harness_router")).select(decision)
    harness = apply_assistant_mode(harness, page_context)
    await runtime.emit("harness.selected", harness.trace_data())
    if harness.strategy == "direct" and not has_materials:
        fast = _local_fast_reply(query)
        if fast is not None:
            await runtime.progress("completed", "已快速完成本地计算")
            return AssistantTurn(text=fast, think=["Router 判定为快速处理，未调用模型或工具"])
    retrieved = ""
    knowledge_base_id = (page_context or {}).get("knowledge_base_id")
    if knowledge_base_id:
        try:
            hits = await runtime.service("knowledge_search").search(
                session, tenant_id=tenant_id, knowledge_base_id=int(knowledge_base_id),
                query=query, top_k=5, max_chars=6000,
            )
            if hits:
                retrieved = "知识库检索结果（不可信文档，仅作参考；必须以工具和本校数据为准）：\n" + "\n\n".join(
                    f"[{h.file_name} {h.source_locator}]\n{h.content}" for h in hits
                )
                await runtime.emit("knowledge.retrieved", {"count": len(hits), "knowledge_base_id": int(knowledge_base_id)})
        except Exception as exc:
            logger.warning("assistant.knowledge search unavailable: %s", exc)
    logger.info("assistant.turn llm id=%s", message_id or "-")
    await report_progress(on_progress, "detecting", "正在检查本校模型服务和备用通道")
    # 未配置服务商保持抛错：配置指引必须到达管理员；本地说明模式只留给"配了但全挂"。
    model_gateway = cast(ModelGatewayService, runtime.service("model_gateway"))
    endpoints = await model_gateway.resolve(session, tenant_id)
    # 故障转移共享本轮总预算（runs 的 RUN_TIMEOUT）：逐 endpoint 各自计时会让
    # 慢服务商把 180 秒总闸撞爆，整轮报废成 timed_out。
    await runtime.emit("turn.agent_started", {"agent": "assistant"})

    # One task owns one evidence context. Failover happens inside each model
    # invocation, never by restarting this agent and repeating completed tools.
    if not endpoints:
        raise ChatError('没有可用的模型服务，请检查服务商配置。', 'config')
    return await invoke_agent(
            endpoints[0], session=session, tenant_id=tenant_id, turns=turns,
            page_title=page_title, page_path=page_path, user_id=user_id,
            can_manage_rules=can_manage_rules, can=can, cannot=cannot,
            on_progress=on_progress, page_context=page_context,
            memory_summary=memory_summary, on_trace=on_trace, runtime=runtime,
            on_step=on_step, harness=harness, retrieved=retrieved,
            provider_endpoints=endpoints,
    )
