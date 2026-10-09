"""Graph：最小工具循环（对应 Spring AI Alibaba Graph 的单节点 StateGraph）。

模型返回 tool_calls 就执行并把结果以 role=tool 喂回去，直到它给出文本回答。
最后一步不传工具表，强制收口成文本；步数封顶，防死循环也防 token 失控。
执行器异常不外抛，转成工具结果文本让模型自行调整。
"""
from __future__ import annotations

import logging
import json
import re
import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.ai.model.chat import ChatError, ChatOutcome, complete_chat_tools
from app.ai.runs.progress import Progress, TOOL_LABELS, report_progress
from app.ai.runs.events import TraceCallback
from app.ai.tools.markdown import hour_table_error
from app.ai.tools.answer_layout import normalize_answer_markdown, answer_layout_error

logger = logging.getLogger(__name__)

MAX_STEPS = 4
_TOOL_TEXT_CAP = 4000
_PAGED_EVIDENCE_TOOLS = frozenset({
    'lookup_student_choices', 'lookup_teaching_assignments',
    'lookup_timetable', 'lookup_schedule_conflicts',
    'lookup_planning_basis', 'validate_hour_scenarios', 'plan_task', 'update_plan_task',
})
_DETAIL_CAP = 40
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LEAK_RETRY_INSTRUCTION = (
    "不要展示分析推理过程。请用简体中文直接给出面向老师的最终回答："
    "能给方案就给完整方案并注明假设，信息不足就把缺少的信息一次性问全。"
)


@dataclass
class AgentStep:
    tool: str
    detail: str


@dataclass
class AgentOutcome:
    text: str
    steps: list[AgentStep] = field(default_factory=list)


@dataclass
class ReactLoop:
    """轻量 ReactLoop：一次 Turn 内按 Step 驱动模型、工具和 Inbox。"""

    base_url: str
    api_key: str
    model: str
    timeout: int
    messages: list[dict]
    tools: list[dict]
    executor: Callable[[str, str], Awaitable[str]]
    max_steps: int = MAX_STEPS
    temperature: float = 0.2
    caller: Callable[..., Awaitable[ChatOutcome]] | None = None
    stop_when: Callable[[], bool] | None = None
    on_progress: Progress | None = None
    on_trace: TraceCallback | None = None
    on_step: Callable[[int], Awaitable[list[dict]]] | None = None
    cycle_timeout_seconds: float = 120
    turn_timeout_seconds: float = 600
    trace_iterations: bool = False
    final_guard: Callable[[str], Awaitable[str | None]] | None = None

    async def run(self) -> AgentOutcome:
        """执行一个 Turn；每个 Step 开始前先消费 steer/inject。"""
        return await _run_react_loop(self)


async def _default_caller(**kwargs) -> ChatOutcome:
    return await complete_chat_tools(**kwargs)


def _assistant_msg(outcome: ChatOutcome) -> dict:
    return {
        "role": "assistant",
        "content": outcome.text or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in outcome.tool_calls
        ],
    }


def _brief(result: str) -> str:
    lines = (result or "").strip().splitlines()
    return lines[0][:_DETAIL_CAP] if lines else ""


def _is_reasoning_leak(convo: list[dict], text: str) -> bool:
    """中文会话的长回复以英文为主：一次有限重答，不能兜底展示它。

    这只是输出语言校验，不作为意图分类；少量班级/科目引用不能绕过校验。
    """
    stripped = (text or "").strip()
    sample = stripped[:1000]
    letters = sum(char.isalpha() for char in sample)
    if len(stripped) < 80 or len(_CJK_RE.findall(sample)) >= max(1, letters * 0.1):
        return False
    for item in reversed(convo):
        if item.get("role") == "system":
            break
        if item.get("role") == "user" and _CJK_RE.search(str(item.get("content") or "")):
            return True
    return False


async def _final_text(loop: ReactLoop, call, convo: list[dict], outcome: ChatOutcome) -> str:
    text = normalize_answer_markdown(outcome.text or '')
    numeric_error = hour_table_error(text) or answer_layout_error(text)
    if not _is_reasoning_leak(convo, text) and not numeric_error:
        return text
    logger.warning("assistant.loop answer_validation_retry model=%s numeric=%s", loop.model, bool(numeric_error))
    await report_progress(loop.on_progress, 'model', '正在核对课时合计' if numeric_error else '正在整理正式答复')
    try:
        retry = await call(
            base_url=loop.base_url, api_key=loop.api_key, model=loop.model,
            timeout=loop.timeout,
            messages=[
                *convo,
                {"role": "assistant", "content": text[:2000]},
                {"role": "user", "content": numeric_error or _LEAK_RETRY_INSTRUCTION},
            ],
            tools=None, temperature=loop.temperature,
        )
    except ChatError:
        raise
    retry_text = normalize_answer_markdown(retry.text or '')
    if not retry_text or retry.tool_calls or _is_reasoning_leak(convo, retry_text) or hour_table_error(retry_text) or answer_layout_error(retry_text):
        raise ChatError("模型未返回可用的正式回答，请重试。", "invalid_answer")
    return retry_text


async def _run_react_loop(loop: ReactLoop) -> AgentOutcome:
    convo = list(loop.messages)
    steps: list[AgentStep] = []
    event_loop = asyncio.get_running_loop()
    turn_deadline = event_loop.time() + min(600, max(.001, loop.turn_timeout_seconds))
    for index in range(loop.max_steps):
        remaining = turn_deadline - event_loop.time()
        if remaining <= 0:
            raise ChatError("本轮任务时间已用尽，已停止执行；已完成步骤仍可查看。", "timeout")
        cycle_budget = min(120, max(.001, loop.cycle_timeout_seconds), remaining)
        cycle_deadline = event_loop.time() + cycle_budget
        call_impl = loop.caller or _default_caller

        async def call(**request):
            # All HTTP retries and fallback endpoints share what remains of this
            # cycle. Output repair also uses this same call boundary.
            request['timeout'] = min(request['timeout'], max(.001, cycle_deadline - event_loop.time()))
            return await call_impl(**request)

        try:
            async with asyncio.timeout_at(cycle_deadline):
                if loop.on_trace and loop.trace_iterations:
                    await loop.on_trace('loop.started', {'step': index + 1, 'budget_seconds': cycle_budget})
                result = await _run_iteration(loop, call, convo, steps, index)
                if loop.on_trace and loop.trace_iterations:
                    await loop.on_trace('loop.completed', {'step': index + 1, 'finished': result is not None})
        except TimeoutError as exc:
            task_limit = remaining <= min(120, max(.001, loop.cycle_timeout_seconds))
            # The expired cycle cannot await more work. The owning run records
            # the failure and keeps the last completed checkpoint.
            message = ("本轮任务时间已用尽，已停止执行；已完成步骤仍可查看。" if task_limit
                       else "当前执行循环已达到时间上限，任务已停止；已完成步骤仍可查看，请核对后重试。")
            raise ChatError(message, 'timeout') from exc
        if result is not None:
            return result
    raise ChatError("模型多轮调用未能完成回答，请重试或把要求拆成几条。", "exhausted")


async def _run_iteration(loop: ReactLoop, call, convo: list[dict], steps: list[AgentStep], index: int) -> AgentOutcome | None:
    """A full bounded cycle: inbox, model, every requested tool, and answer repair."""
    final = index == loop.max_steps - 1
    if loop.on_step:
        incoming = await loop.on_step(index + 1)
        convo.extend({k: v for k, v in item.items() if k != "_wake"} for item in incoming)
    await report_progress(loop.on_progress, "model", "正在理解你的要求" if index == 0 else "正在根据查询结果整理答复")
    if loop.on_trace:
        await loop.on_trace("model.request", {
            "step": index + 1, "final": final,
            "messages": deepcopy(convo), "tools_enabled": not final,
        })
    outcome = await call(base_url=loop.base_url, api_key=loop.api_key, model=loop.model,
                         timeout=loop.timeout, messages=convo,
                         tools=None if final else loop.tools, temperature=loop.temperature)
    if loop.on_trace:
        await loop.on_trace("model.response", {
            "step": index + 1, "content": outcome.text or "",
            "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in outcome.tool_calls],
        })
    if final and outcome.tool_calls:
        logger.warning("assistant.loop final step tool_calls ignored model=%s names=%s", loop.model, [tc.name for tc in outcome.tool_calls])
        if not (outcome.text or "").strip():
            raise ChatError("模型没有返回文本，请重试。", "empty")
        return await _finish_answer(loop, call, convo, steps, outcome, final=final)
    if not outcome.tool_calls:
        if loop.on_step and not final:
            incoming = await loop.on_step(index + 1)
            if any(bool(item.get("_wake")) for item in incoming):
                if (outcome.text or "").strip():
                    convo.append({"role": "assistant", "content": outcome.text})
                convo.extend({k: v for k, v in item.items() if k != "_wake"} for item in incoming)
                return None
        return await _finish_answer(loop, call, convo, steps, outcome, final=final)
    convo.append(_assistant_msg(outcome))
    allowed_names = {str(item.get("function", {}).get("name")) for item in loop.tools}
    for tc in outcome.tool_calls:
        if tc.name not in allowed_names:
            logger.warning("assistant.loop blocked_unknown_tool name=%s", tc.name)
            message = "当前账号没有排课配置权限，已拒绝执行。" if tc.name == "propose_rules" else "工具未被授权，已拒绝执行。"
            convo.append({"role": "tool", "tool_call_id": tc.id, "content": message})
            continue
        await report_progress(loop.on_progress, "tool", TOOL_LABELS.get(tc.name, "正在处理模型请求的查询"))
        if loop.on_trace:
            await loop.on_trace("tool.call", {"step": index + 1, "id": tc.id, "name": tc.name, "arguments": tc.arguments})
        try:
            result = ("请在查询完成后单独调用输出整理工具。" if tc.name == "format_markdown" and len(outcome.tool_calls) != 1
                      else await loop.executor(tc.name, tc.arguments))
        except Exception:
            logger.exception("assistant.loop executor fail tool=%s", tc.name)
            result = f"工具 {tc.name} 执行失败。"
        result = (result or "").strip() or "工具没有返回内容。"
        if loop.on_trace:
            await loop.on_trace("tool.result", {"step": index + 1, "id": tc.id, "name": tc.name, "content": result[:_TOOL_TEXT_CAP]})
            if tc.name in {'plan_task', 'update_plan_task'}:
                try:
                    payload = json.loads(result)
                    plan = payload.get('data', {}).get('plan') if payload.get('ok') is True else None
                except (ValueError, AttributeError):
                    plan = None
                if isinstance(plan, dict):
                    await loop.on_trace('planning.updated', {'plan': plan})
        await report_progress(loop.on_progress, "observed", "已收到工具返回，正在核对结果")
        steps.append(AgentStep(tool=tc.name, detail="回答格式已处理" if tc.name == "format_markdown" else _brief(result)))
        model_result = result if tc.name in _PAGED_EVIDENCE_TOOLS else result[:_TOOL_TEXT_CAP]
        convo.append({"role": "tool", "tool_call_id": tc.id, "content": model_result})
        if tc.name == "format_markdown" and len(outcome.tool_calls) == 1:
            try:
                formatted = json.loads(result)
                markdown = formatted.get("data", {}).get("markdown") if formatted.get("ok") is True else None
            except (ValueError, AttributeError):
                markdown = None
            if isinstance(markdown, str) and markdown.strip():
                if loop.on_step and not final:
                    incoming = await loop.on_step(index + 1)
                    convo.extend({k: v for k, v in item.items() if k != "_wake"} for item in incoming)
                    if any(bool(item.get("_wake")) for item in incoming):
                        return None
                return await _finish_answer(loop, call, convo, steps, ChatOutcome(text=markdown), final=final)
        if loop.stop_when and loop.stop_when():
            return AgentOutcome(text="", steps=steps)
    return None


async def _finish_answer(loop: ReactLoop, call, convo: list[dict], steps: list[AgentStep],
                         outcome: ChatOutcome, *, final: bool) -> AgentOutcome | None:
    text = await _final_text(loop, call, convo, outcome)
    instruction = await loop.final_guard(text) if loop.final_guard else None
    if not instruction:
        return AgentOutcome(text=text, steps=steps)
    if final:
        raise ChatError('任务步骤或方案校验尚未完成，本轮未交付未经核实的完整结论；请查看已完成步骤。', 'invalid_answer')
    # The correction is server-generated validation, not a new user demand.
    # Let the next bounded cycle perform the missing work instead of secretly
    # adding another unbudgeted model call to this one.
    convo.append({'role': 'assistant', 'content': text[:8000]})
    convo.append({'role': 'system', 'content': f'交付前校验未通过，请继续本轮任务：{instruction[:2000]}'})
    await report_progress(loop.on_progress, 'observed', '正在核对计划步骤和方案校验')
    if loop.on_trace:
        await loop.on_trace('answer.guard_rejected', {'reason': instruction[:500]})
    return None
