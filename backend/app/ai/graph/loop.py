"""Graph：最小工具循环（对应 Spring AI Alibaba Graph 的单节点 StateGraph）。

模型返回 tool_calls 就执行并把结果以 role=tool 喂回去，直到它给出文本回答。
最后一步不传工具表，强制收口成文本；步数封顶，防死循环也防 token 失控。
执行器异常不外抛，转成工具结果文本让模型自行调整。
"""
from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.ai.model.chat import ChatError, ChatOutcome, complete_chat_tools
from app.ai.runs.progress import Progress, TOOL_LABELS, report_progress
from app.ai.runs.events import TraceCallback

logger = logging.getLogger(__name__)

MAX_STEPS = 4
_TOOL_TEXT_CAP = 4000
_DETAIL_CAP = 40


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


async def _run_react_loop(loop: ReactLoop) -> AgentOutcome:
    call = loop.caller or _default_caller
    convo = list(loop.messages)
    steps: list[AgentStep] = []
    for index in range(loop.max_steps):
        final = index == loop.max_steps - 1
        if loop.on_step:
            convo.extend(await loop.on_step(index + 1))
        await report_progress(loop.on_progress, "model", "正在等待模型理解需求" if index == 0 else "正在等待模型整理查询结果")
        if loop.on_trace:
            await loop.on_trace("model.request", {
                "step": index + 1, "final": final,
                "messages": deepcopy(convo), "tools_enabled": not final,
            })
        outcome = await call(
            base_url=loop.base_url, api_key=loop.api_key, model=loop.model,
            timeout=loop.timeout, messages=convo,
            tools=None if final else loop.tools, temperature=loop.temperature,
        )
        if loop.on_trace:
            await loop.on_trace("model.response", {
                "step": index + 1, "content": outcome.text or "",
                "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in outcome.tool_calls],
            })
        if final and outcome.tool_calls:
            logger.warning("assistant.loop final step tool_calls ignored model=%s names=%s", loop.model, [tc.name for tc in outcome.tool_calls])
            if not (outcome.text or "").strip():
                raise ChatError("模型没有返回文本，请重试。", "empty")
            return AgentOutcome(text=outcome.text, steps=steps)
        if not outcome.tool_calls:
            return AgentOutcome(text=outcome.text, steps=steps)
        convo.append(_assistant_msg(outcome))
        for tc in outcome.tool_calls:
            allowed_names = {str(item.get("function", {}).get("name")) for item in loop.tools}
            if tc.name not in allowed_names:
                logger.warning("assistant.loop blocked_unknown_tool name=%s", tc.name)
                message = "当前账号没有排课配置权限，已拒绝执行。" if tc.name == "propose_rules" else "工具未被授权，已拒绝执行。"
                convo.append({"role": "tool", "tool_call_id": tc.id, "content": message})
                continue
            await report_progress(loop.on_progress, "tool", TOOL_LABELS.get(tc.name, "正在处理模型请求的查询"))
            if loop.on_trace:
                await loop.on_trace("tool.call", {"step": index + 1, "id": tc.id, "name": tc.name, "arguments": tc.arguments})
            try:
                result = await loop.executor(tc.name, tc.arguments)
            except Exception:
                logger.exception("assistant.loop executor fail tool=%s", tc.name)
                result = f"工具 {tc.name} 执行失败。"
            result = (result or "").strip() or "工具没有返回内容。"
            if loop.on_trace:
                await loop.on_trace("tool.result", {"step": index + 1, "id": tc.id, "name": tc.name, "content": result[:_TOOL_TEXT_CAP]})
            await report_progress(loop.on_progress, "observed", "已收到工具返回，正在核对结果")
            steps.append(AgentStep(tool=tc.name, detail=_brief(result)))
            convo.append({"role": "tool", "tool_call_id": tc.id, "content": result[:_TOOL_TEXT_CAP]})
            if loop.stop_when and loop.stop_when():
                return AgentOutcome(text="", steps=steps)
    raise ChatError("模型多轮调用未能完成回答，请重试或把要求拆成几条。", "exhausted")
