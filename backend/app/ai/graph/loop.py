"""Graph：最小工具循环（对应 Spring AI Alibaba Graph 的单节点 StateGraph）。

模型返回 tool_calls 就执行并把结果以 role=tool 喂回去，直到它给出文本回答。
最后一步不传工具表，强制收口成文本；步数封顶，防死循环也防 token 失控。
执行器异常不外抛，转成工具结果文本让模型自行调整。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.ai.model.chat import ChatError, ChatOutcome, complete_chat_tools
from app.ai.progress import Progress, TOOL_LABELS, report_progress

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


async def run_tool_loop(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    messages: list[dict],
    tools: list[dict],
    executor: Callable[[str, str], Awaitable[str]],
    max_steps: int = MAX_STEPS,
    temperature: float = 0.2,
    caller: Callable[..., Awaitable[ChatOutcome]] | None = None,
    stop_when: Callable[[], bool] | None = None,
    on_progress: Progress | None = None,
) -> AgentOutcome:
    """跑工具循环。caller 参数仅供测试注入假模型，生产走 complete_chat_tools。"""
    call = caller or _default_caller
    convo = list(messages)
    steps: list[AgentStep] = []
    for index in range(max_steps):
        await report_progress(on_progress, "model", "正在等待模型理解需求" if index == 0 else "正在等待模型整理查询结果")
        outcome = await call(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            messages=convo,
            tools=None if index == max_steps - 1 else tools,
            temperature=temperature,
        )
        if not outcome.tool_calls:
            return AgentOutcome(text=outcome.text, steps=steps)
        convo.append(_assistant_msg(outcome))
        for tc in outcome.tool_calls:
            await report_progress(on_progress, "tool", TOOL_LABELS.get(tc.name, "正在处理模型请求的查询"))
            try:
                result = await executor(tc.name, tc.arguments)
            except Exception:
                logger.exception("assistant.loop executor fail tool=%s", tc.name)
                result = f"工具 {tc.name} 执行失败。"
            result = (result or "").strip() or "工具没有返回内容。"
            await report_progress(on_progress, "observed", "已收到工具返回，正在核对结果")
            steps.append(AgentStep(tool=tc.name, detail=_brief(result)))
            convo.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result[:_TOOL_TEXT_CAP]}
            )
            if stop_when and stop_when():
                return AgentOutcome(text="", steps=steps)
    raise ChatError("模型没有给出回答")
