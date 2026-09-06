"""教务 Agent。对应 Spring AI Alibaba Agent Framework 的 ReactAgent / RoutingAgent（单任务）。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.actions import PROPOSE_RULES_TOOL, RulesProposal, action_view, propose_rules
from app.ai.guide import degraded_reply as _local_degraded_reply
from app.ai.guide import local_reply, rule_jumps
from app.ai.graph.loop import run_tool_loop
from app.ai.model.chat import ChatEndpoint, ChatError, complete_chat, resolve_chat_endpoints
from app.ai.prompt.messages import build_agent_messages, build_messages
from app.ai.resilience import provider_circuits
from app.ai.tools.retrieve import retrieve_skill
from app.ai.tools.school import SCHOOL_TOOLS, execute_school_tool
from app.ai.runs.progress import Progress, report_progress
from app.ai.runs.events import TraceCallback
from app.ai.runtime import AssistantRuntime
from app.utils.answer_cache import answer_cache_key, get_cached_answer, put_cached_answer

logger = logging.getLogger(__name__)

# 工具循环已消耗超过该秒数才失败时，不再走降级路径（降级还要两轮模型调用，必然撞总闸）。
_FALLBACK_MAX_SPENT = 20
# 降级两轮调用的单轮上限：RUN_TIMEOUT(180) − 前序最多 _FALLBACK_MAX_SPENT(20) 对半再留余量，
# 保证降级路径整体不撞总闸被拦腰砍断。
_FALLBACK_STEP_TIMEOUT = 75
# 快速失败后可尝试"只读说明"降级的错误类别（同服务商还活着，只是工具调用不可用）。
_TEXT_ONLY_FALLBACK_ERRORS = {"bad_request", "parse", "empty", "context_overflow", "unavailable"}
# 服务明显活着、只是本轮请求没能完成的类别：保留精确报错抛出，不吞进"服务不可用"的本地文案。
_PRECISE_FAILURE_CLASSES = {"bad_request", "parse", "empty", "context_overflow", "exhausted"}


@dataclass
class TeacherTurn:
    text: str
    think: list[str] = field(default_factory=list)
    choices: list[dict] = field(default_factory=list)
    plan: dict | None = None
    jumps: list[dict] = field(default_factory=list)


def _trim_turns(turns: list[dict], keep: int = 6) -> list[dict]:
    """超长重试用的历史裁剪：保留最近若干条，并从 user 消息起头，方便模型衔接。"""
    tail = list(turns[-keep:])
    while len(tail) > 1 and tail[0].get("role") != "user":
        tail.pop(0)
    return tail


async def agent_reply(
    session: AsyncSession,
    tenant_id: int,
    turns: list[dict],
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
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
) -> TeacherTurn:
    """模型查本校数据或生成一份待确认草稿；草稿成功后直接返回可信卡片。"""

    cache_key = answer_cache_key(
        tenant_id,
        model,
        ([{"role": "assistant", "content": memory_summary[-8000:]}] if memory_summary else []) + turns,
        page_path=page_path,
        can_manage_rules=can_manage_rules,
        page_context=page_context,
    )
    cached = get_cached_answer(cache_key)
    if cached:
        logger.info("assistant.cache hit kind=%s", cached.get("kind"))
        return TeacherTurn(
            text=cached.get("text") or "",
            think=[*(cached.get("think") or []), "回答缓存命中，未重跑模型"],
            jumps=cached.get("jumps") or [],
        )

    plan = None
    async def executor(name: str, arguments: str) -> str:
        nonlocal plan
        if name == "propose_rules":
            if not can_manage_rules or user_id is None:
                return "当前账号没有排课配置权限，请由教务管理员确认配置。"
            if plan is not None:
                return "本轮已经生成草稿，请先让老师核对，下一轮再修改。"
            try:
                from app.ai.tools.school import _term
                year, term = await _term(session, tenant_id) if page_context else (None, None)
                if page_context and ((page_context.get("academic_year") and page_context["academic_year"] != year) or (page_context.get("term") and page_context["term"] != term)):
                    return "当前页面与学校当前学期不同。规则草稿暂只支持学校当前学期，请先切换页面或到规则工作台手动配置，不能改到另一个学期。"
                proposal = RulesProposal.model_validate_json(arguments)
                action = await propose_rules(session, tenant_id, user_id, proposal)
                plan = action_view(action)
                return "草稿已准备，尚未保存规则：\n" + plan["summary"]
            except ValueError as exc:
                return "草稿未生成，请澄清：" + str(exc)[:700]
        return await execute_school_tool(name, arguments, session=session, tenant_id=tenant_id, page_context=page_context)

    agent_tools = [*SCHOOL_TOOLS, *([PROPOSE_RULES_TOOL] if can_manage_rules else [])]

    def agent_messages(history: list[dict], memory: str) -> list[dict]:
        return build_agent_messages(
            history,
            page_title=page_title,
            page_path=page_path,
            can=can,
            cannot=cannot,
            page_context=page_context,
            memory_summary=memory,
        )

    async def run_loop(history: list[dict], memory: str):
        return await run_tool_loop(
            base_url=base_url,
            api_key=api_key,
            model=model,
            # 单步上限 90 秒：慢服务商生成草稿 JSON 可能超过 45 秒，中途砍掉只会报废整轮；
            # 总时长由 runs 的 RUN_TIMEOUT 兜底。
            timeout=min(timeout, 90),
            messages=agent_messages(history, memory),
            tools=agent_tools,
            executor=executor,
            stop_when=lambda: plan is not None,
            on_progress=on_progress,
            on_trace=on_trace,
        )

    try:
        outcome = await run_loop(turns, memory_summary)
    except ChatError as exc:
        if exc.error_class != "context_overflow":
            raise
        # 上下文超长：压掉早期历史和长摘要重试一次，仍超长才放行给降级路径。
        trimmed = _trim_turns(turns)
        logger.warning("assistant.agent overflow retry turns=%d->%d", len(turns), len(trimmed))
        await report_progress(on_progress, "model", "对话较长，正在压缩上下文重试")
        outcome = await run_loop(trimmed, memory_summary[:1500])
    logger.info("assistant.agent tools=%s", ",".join(s.tool for s in outcome.steps) or "-")
    last_user = next((str(t.get("content") or "") for t in reversed(turns) if t.get("role") == "user"), "")
    guide = runtime.service("ui_guide") if runtime else None
    jumps = [] if plan else (guide.rule_jumps(last_user, outcome.text, page_path) if guide else rule_jumps(last_user, outcome.text, page_path))
    step_lines = [f"{step.tool}：{step.detail}" for step in outcome.steps]
    if plan is None:
        kind = put_cached_answer(
            cache_key,
            text=outcome.text,
            think=step_lines,
            jumps=jumps,
            tools=[step.tool for step in outcome.steps],
        )
        logger.info("assistant.cache store=%s", kind or "skip")
    return TeacherTurn(
        text="规则草稿已准备，请核对下方内容后确认。" if plan else outcome.text,
        think=step_lines,
        plan=plan,
        jumps=jumps,
    )


async def handle_teacher_turn(
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
) -> TeacherTurn:
    if not turns:
        raise ChatError("请输入内容")
    last = turns[-1]
    if len(turns) == 1 and last.get("role") == "user":
        guide = runtime.service("ui_guide") if runtime else None
        fixed = (guide.local_reply(str(last.get("content") or ""), page_path) if guide else local_reply(str(last.get("content") or ""), page_path))
        if fixed:
            logger.info("assistant.turn local id=%s", message_id or "-")
            return TeacherTurn(text=fixed)
    logger.info("assistant.turn llm id=%s", message_id or "-")
    query = ""
    for item in reversed(turns):
        if item.get("role") == "user":
            query = str(item.get("content") or "")
            break
    await report_progress(on_progress, "detecting", "正在检查本校模型服务和备用通道")
    # 未配置服务商保持抛错：配置指引必须到达管理员；本地说明模式只留给"配了但全挂"。
    endpoints = await resolve_chat_endpoints(session, tenant_id)
    # 故障转移共享本轮总预算（runs 的 RUN_TIMEOUT）：逐 endpoint 各自计时会让
    # 慢服务商把 180 秒总闸撞爆，整轮报废成 timed_out。
    from app.ai.runs.service import RUN_TIMEOUT
    runtime = runtime or AssistantRuntime(on_progress=on_progress, on_trace=on_trace, circuits=provider_circuits)
    await runtime.emit("turn.agent_started", {"agent": "teacher"})


    async def text_only_fallback(endpoint: ChatEndpoint, budget: int) -> TeacherTurn:
        await report_progress(
            on_progress,
            "degraded",
            f"{endpoint.name} 的工具调用不可用，正在切换到只读说明模式",
        )
        fallback_timeout = min(endpoint.timeout, _FALLBACK_STEP_TIMEOUT, budget)
        retrieved = await retrieve_skill(
            query,
            base_url=endpoint.base_url,
            api_key=endpoint.api_key,
            model=endpoint.model,
            timeout=fallback_timeout,
        )

        def fallback_messages(history: list[dict]) -> list[dict]:
            return build_messages(
                history,
                page_title=page_title,
                page_path=page_path,
                can=can,
                cannot=cannot,
                retrieved=retrieved,
                page_context=page_context,
                memory_summary=memory_summary,
            )

        try:
            text = await complete_chat(
                base_url=endpoint.base_url,
                api_key=endpoint.api_key,
                model=endpoint.model,
                timeout=fallback_timeout,
                messages=fallback_messages(turns),
            )
        except ChatError as exc:
            if exc.error_class != "context_overflow":
                raise
            text = await complete_chat(
                base_url=endpoint.base_url,
                api_key=endpoint.api_key,
                model=endpoint.model,
                timeout=fallback_timeout,
                messages=fallback_messages(_trim_turns(turns)),
            )
        return TeacherTurn(
            text="当前模型工具调用不可用，本轮仅提供说明，未生成可执行草稿。\n" + text,
            think=[f"优雅降级：{endpoint.name} 已切换到只读说明模式"],
            jumps=rule_jumps(query, text, page_path),
        )

    async def invoke(endpoint: ChatEndpoint) -> TeacherTurn:
        return await agent_reply(
            session, tenant_id, turns,
            base_url=endpoint.base_url, api_key=endpoint.api_key, model=endpoint.model,
            timeout=endpoint.timeout, page_title=page_title, page_path=page_path,
            can=can, cannot=cannot, user_id=user_id, can_manage_rules=can_manage_rules,
            on_progress=on_progress, page_context=page_context, memory_summary=memory_summary, on_trace=on_trace, runtime=runtime,
        )

    routed = await runtime.service("model_router").route(
        endpoints,
        total_budget_seconds=RUN_TIMEOUT,
        invoke=invoke,
        on_progress=on_progress,
        on_trace=on_trace,
        message_id=message_id,
        clock=time.monotonic,
    )
    if routed.value is not None:
        turn = routed.value
        if routed.used_backup and routed.endpoint is not None:
            turn.think.append(f"故障恢复：已切换至备用模型「{routed.endpoint.name}」")
        return turn

    last_error = routed.last_error
    trail = routed.trail
    if last_error is not None and (
        routed.spent_seconds <= _FALLBACK_MAX_SPENT
        and last_error.error_class in _TEXT_ONLY_FALLBACK_ERRORS
        and routed.endpoint is None
        and endpoints
    ):
        # 只读说明只在快速失败时尝试，防止两轮额外模型调用耗尽任务总预算。
        try:
            if on_trace:
                await on_trace("provider.degraded", {"provider": endpoints[-1].name, "mode": "text_only", "error_class": last_error.error_class})
            turn = await text_only_fallback(endpoints[-1], max(10, int((RUN_TIMEOUT - routed.spent_seconds) // 2)))
            provider_circuits.record_success(endpoints[-1].key)
            return turn
        except ChatError as fallback_error:
            last_error = fallback_error
            trail.append(f"{endpoints[-1].name}只读说明仍失败({fallback_error.error_class})")

    if routed.budget_exhausted:
        raise ChatError("本轮处理时间已用尽，请稍后重试或把要求拆成几条；未执行规则写入", "timeout")
    if last_error is not None and last_error.error_class in _PRECISE_FAILURE_CLASSES:
        # 服务其实活着，只是本轮请求没完成：保留精确报错，"服务不可用"文案反而误导。
        raise last_error
    logger.warning(
        "assistant.agent degraded id=%s class=%s",
        message_id or "-",
        last_error.error_class if last_error else "isolated",
    )
    await report_progress(on_progress, "degraded", "所有模型通道暂不可用，已切换到本地教务说明模式")
    note = "；".join(trail) if trail else "模型通道不可用"
    return TeacherTurn(
        text=_local_degraded_reply(query, page_path),
        think=[f"故障降级：{note}；本轮未执行任何写操作"],
    )
