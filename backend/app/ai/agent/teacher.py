"""教务 Agent。对应 Spring AI Alibaba Agent Framework 的 ReactAgent / RoutingAgent（单任务）。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.advisor.clarify import clarify
from app.ai.actions import PROPOSE_RULES_TOOL, RulesProposal, action_view, propose_rules
from app.ai.graph.loop import run_tool_loop
from app.ai.model.chat import ChatEndpoint, ChatError, complete_chat, resolve_chat_endpoints
from app.ai.prompt.messages import GREET_REPLY, build_agent_messages, build_messages
from app.ai.resilience import provider_circuits
from app.ai.tools.retrieve import retrieve_skill
from app.ai.tools.school import SCHOOL_TOOLS, execute_school_tool
from app.ai.runs.progress import Progress, report_progress
from app.utils.answer_cache import answer_cache_key, get_cached_answer, put_cached_answer

logger = logging.getLogger(__name__)

_GREET = {"你好", "您好", "hi", "hello", "在吗", "在么", "嗨"}
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


_RULE_JUMP_PATH = "/scheduling?tab=rules"


def rule_jumps(query: str, text: str, page_path: str | None) -> list[dict]:
    """回答在讲规则配置、而当前页不在规则组时，给一个跳转按钮。"""
    if page_path and "tab=rules" in page_path:
        return []
    joined = f"{query or ''}\n{text or ''}"
    if "规则" not in joined:
        return []
    if not any(word in text for word in ("规则组", "组件", "禁排", "连堂", "课位", "班主任")):
        return []
    return [{"label": "去规则组", "path": _RULE_JUMP_PATH}]


def local_reply(text: str, page_path: str | None = None) -> str | None:
    q = (text or "").strip().rstrip("！!。.~～")
    if q.lower() in _GREET:
        return GREET_REPLY
    if page_path and any(word in q for word in ("下一步", "接下来", "该干什么", "该做什么", "先做什么")):
        return None
    hit = clarify(text or "")
    if hit:
        return hit.text
    return None


def _trim_turns(turns: list[dict], keep: int = 6) -> list[dict]:
    """超长重试用的历史裁剪：保留最近若干条，并从 user 消息起头，方便模型衔接。"""
    tail = list(turns[-keep:])
    while len(tail) > 1 and tail[0].get("role") != "user":
        tail.pop(0)
    return tail


def _local_degraded_reply(query: str, page_path: str | None) -> str:
    """所有模型通道都不可用时的本地兜底文案：按页面给一段教务指引，明确本轮无写入。"""
    joined = f"{query} {page_path or ''}"
    if "排课" in joined or "/scheduling" in joined:
        guidance = "请依次核对学年学期、课位结构、班级课时、任教关系和排课规则；数据齐全后再生成课表。"
    elif "学生" in joined or "/students" in joined:
        guidance = "请先维护学生档案，再完成行政班分配；批量处理前可先下载模板核对字段。"
    elif "教师" in joined or "/teachers" in joined:
        guidance = "请先核对教师账号和教师档案，再到任教关系中确认教师、班级与科目的对应。"
    elif "空间" in joined or "校区" in joined or "/facilities" in joined:
        guidance = "请先建立校区、楼宇、楼层和场室，再配置资源分配规则与班级划分。"
    elif "设置" in joined or "/settings" in joined:
        guidance = "请先核对当前学年、学期、层次和年级，再继续配置人员、空间与班级。"
    else:
        guidance = "你可以继续维护学生、教师、空间资源和排课基础数据；涉及保存或执行的操作请等待模型服务恢复。"
    return (
        "模型服务暂时不可用，助手已进入本地说明模式。"
        f"{guidance}\n\n本轮未执行任何写入，已保留当前页面和对话，你可以稍后直接重试。"
    )


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
    jumps = [] if plan else rule_jumps(last_user, outcome.text, page_path)
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
) -> TeacherTurn:
    if not turns:
        raise ChatError("请输入内容")
    last = turns[-1]
    if len(turns) == 1 and last.get("role") == "user":
        fixed = local_reply(str(last.get("content") or ""), page_path)
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

    turn_started = time.monotonic()

    def spent_total() -> float:
        return time.monotonic() - turn_started

    def remaining_budget() -> float:
        return RUN_TIMEOUT - spent_total()

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

    last_error: ChatError | None = None
    trail: list[str] = []
    budget_exhausted = False
    for index, endpoint in enumerate(endpoints):
        is_last = index == len(endpoints) - 1
        if not provider_circuits.is_available(endpoint.key):
            logger.warning("assistant.provider isolated id=%s provider=%s", message_id or "-", endpoint.name)
            await report_progress(on_progress, "isolated", f"{endpoint.name} 正在隔离期，已跳过该服务")
            trail.append(f"{endpoint.name}隔离期跳过")
            continue
        if remaining_budget() < 30:
            # 剩余预算做不完一轮有意义的处理，不再起新 endpoint，避免整轮被总闸报废。
            budget_exhausted = True
            break
        try:
            turn = await agent_reply(
                session,
                tenant_id,
                turns,
                base_url=endpoint.base_url,
                api_key=endpoint.api_key,
                model=endpoint.model,
                timeout=endpoint.timeout,
                page_title=page_title,
                page_path=page_path,
                can=can,
                cannot=cannot,
                user_id=user_id,
                can_manage_rules=can_manage_rules,
                on_progress=on_progress,
                page_context=page_context,
                memory_summary=memory_summary,
            )
        except ChatError as exc:
            can_try_text_only = (
                is_last
                and spent_total() <= _FALLBACK_MAX_SPENT
                and exc.error_class in _TEXT_ONLY_FALLBACK_ERRORS
            )
            if can_try_text_only:
                try:
                    turn = await text_only_fallback(endpoint, max(10, int(remaining_budget() // 2)))
                except ChatError as fallback_error:
                    exc = fallback_error
                    trail.append(f"{endpoint.name}只读说明仍失败({fallback_error.error_class})")
                else:
                    provider_circuits.record_success(endpoint.key)
                    return turn
            last_error = exc
            state = provider_circuits.record_failure(endpoint.key, exc.error_class)
            trail.append(f"{endpoint.name}({exc.error_class})")
            logger.warning(
                "assistant.provider fail id=%s provider=%s class=%s failures=%s isolated=%s",
                message_id or "-",
                endpoint.name,
                exc.error_class,
                state.failures,
                state.isolated,
            )
            if state.isolated:
                await report_progress(on_progress, "isolated", f"{endpoint.name} 连续异常，已临时隔离")
            if not is_last:
                await report_progress(on_progress, "recovering", "当前模型未响应，正在切换备用模型继续处理")
            continue
        provider_circuits.record_success(endpoint.key)
        if index > 0:
            turn.think.append(f"故障恢复：已切换至备用模型「{endpoint.name}」")
        return turn

    if budget_exhausted:
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
