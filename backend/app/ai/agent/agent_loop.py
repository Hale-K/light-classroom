"""React Agent 的消息构建与工具循环执行。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.ai.gateway import ModelGatewayService
from app.ai.graph.loop import ReactLoop
from app.ai.harness import HarnessProfile
from app.ai.prompt.messages import build_agent_messages
from app.ai.runs.events import TraceCallback
from app.ai.runs.progress import Progress


def build_agent_messages_for_turn(history: list[dict], memory: str, *, page_title: str | None,
                                  page_path: str | None, can: list[str] | None,
                                  cannot: list[str] | None, page_context: dict | None,
                                  harness: HarnessProfile, retrieved: str) -> list[dict]:
    return build_agent_messages(
        history, page_title=page_title, page_path=page_path, can=can, cannot=cannot,
        page_context=page_context, memory_summary=memory,
        harness_instructions=harness.instructions, retrieved=retrieved,
    )


async def run_agent_loop(history: list[dict], memory: str, *, base_url: str, api_key: str,
                         model: str, timeout: int, on_progress: Progress | None,
                         on_trace: TraceCallback | None,
                         on_step: Callable[[int], Awaitable[list[dict]]] | None,
                         model_gateway: ModelGatewayService, tool_scope, harness: HarnessProfile,
                         page_title: str | None, page_path: str | None, can: list[str] | None,
                         cannot: list[str] | None, page_context: dict | None,
                         retrieved: str):
    return await ReactLoop(
        base_url=base_url, api_key=api_key, model=model,
        timeout=min(timeout, harness.step_timeout_seconds),
        messages=build_agent_messages_for_turn(
            history, memory, page_title=page_title, page_path=page_path, can=can,
            cannot=cannot, page_context=page_context, harness=harness, retrieved=retrieved,
        ),
        tools=tool_scope.definitions, executor=tool_scope.execute,
        caller=model_gateway.complete_tools, stop_when=lambda: tool_scope.plan is not None,
        on_progress=on_progress, on_trace=on_trace, on_step=on_step,
        max_steps=harness.max_steps, temperature=harness.temperature,
    ).run()
