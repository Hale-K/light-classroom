"""教务 Agent。对应 Spring AI Alibaba Agent Framework 的 ReactAgent / RoutingAgent（单任务）。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.advisor.clarify import clarify
from app.ai.actions import PROPOSE_RULES_TOOL, RulesProposal, action_view, propose_rules
from app.ai.graph.loop import run_tool_loop
from app.ai.model.chat import ChatError, complete_chat, resolve_chat_endpoint
from app.ai.prompt.messages import GREET_REPLY, build_agent_messages, build_messages
from app.ai.tools.retrieve import retrieve_skill
from app.ai.tools.school import SCHOOL_TOOLS, execute_school_tool
from app.ai.runs.progress import Progress, report_progress
from app.utils.answer_cache import answer_cache_key, get_cached_answer, put_cached_answer

logger = logging.getLogger(__name__)

_GREET = {"你好", "您好", "hi", "hello", "在吗", "在么", "嗨"}
# 工具循环已消耗超过该秒数才失败时，不再走降级路径（降级还要两轮模型调用，必然撞总闸）。
_FALLBACK_MAX_SPENT = 20


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


def local_reply(text: str) -> str | None:
    q = (text or "").strip().rstrip("！!。.~～")
    if q.lower() in _GREET:
        return GREET_REPLY
    hit = clarify(text or "")
    if hit:
        return hit.text
    return None


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
) -> TeacherTurn:
    """模型查本校数据或生成一份待确认草稿；草稿成功后直接返回可信卡片。"""

    cache_key = answer_cache_key(
        tenant_id,
        model,
        turns,
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

    outcome = await run_tool_loop(
        base_url=base_url,
        api_key=api_key,
        model=model,
        # 单步上限 90 秒：慢服务商生成草稿 JSON 可能超过 45 秒，中途砍掉只会报废整轮；
        # 总时长由 runs 的 RUN_TIMEOUT 兜底。
        timeout=min(timeout, 90),
        messages=build_agent_messages(
            turns,
            page_title=page_title,
            page_path=page_path,
            can=can,
            cannot=cannot,
            page_context=page_context,
        ),
        tools=[*SCHOOL_TOOLS, *([PROPOSE_RULES_TOOL] if can_manage_rules else [])],
        executor=executor,
        stop_when=lambda: plan is not None,
        on_progress=on_progress,
    )
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
) -> TeacherTurn:
    if not turns:
        raise ChatError("请输入内容")
    last = turns[-1]
    if len(turns) == 1 and last.get("role") == "user":
        fixed = local_reply(str(last.get("content") or ""))
        if fixed:
            logger.info("assistant.turn local id=%s", message_id or "-")
            return TeacherTurn(text=fixed)
    logger.info("assistant.turn llm id=%s", message_id or "-")
    await report_progress(on_progress, "preparing", "正在读取本校模型配置")
    base, key, model, timeout = await resolve_chat_endpoint(session, tenant_id)
    started = time.monotonic()
    query = ""
    for item in reversed(turns):
        if item.get("role") == "user":
            query = str(item.get("content") or "")
            break
    try:
        return await agent_reply(
            session,
            tenant_id,
            turns,
            base_url=base,
            api_key=key,
            model=model,
            timeout=timeout,
            page_title=page_title,
            page_path=page_path,
            can=can,
            cannot=cannot,
            user_id=user_id,
            can_manage_rules=can_manage_rules,
            on_progress=on_progress,
            page_context=page_context,
        )
    except ChatError as exc:
        spent = time.monotonic() - started
        if spent > _FALLBACK_MAX_SPENT:
            logger.warning("assistant.agent giveup id=%s spent=%.0fs err=%s", message_id or "-", spent, exc.message)
            raise ChatError("模型多轮调用未能在时限内完成，请重试或把要求拆成几条；未执行规则写入") from exc
        logger.warning("assistant.agent fallback id=%s spent=%.0fs err=%s", message_id or "-", spent, exc.message)
    # 降级路径：租户模型不支持工具调用（或快速失败）时，沿用目录路由 + 直接补全。
    await report_progress(on_progress, "fallback", "工具调用未完成，正在尝试操作说明问答；本轮尚未执行规则写入")
    retrieved = await retrieve_skill(
        query, base_url=base, api_key=key, model=model, timeout=timeout,
    )
    text = await complete_chat(
        base_url=base,
        api_key=key,
        model=model,
        timeout=timeout,
        messages=build_messages(
            turns,
            page_title=page_title,
            page_path=page_path,
            can=can,
            cannot=cannot,
            retrieved=retrieved,
            page_context=page_context,
        ),
    )
    return TeacherTurn(
        text="当前模型工具调用不可用，本轮仅提供说明，未生成可执行草稿。\n" + text,
        jumps=rule_jumps(query, text, page_path),
    )
