"""React Agent 的消息构建与工具循环执行。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
import asyncio
from urllib.parse import urlsplit

from app.ai.gateway import ModelGatewayService
from app.ai.graph.loop import AgentOutcome, ReactLoop
from app.ai.harness import HarnessProfile
from app.ai.prompt.messages import build_agent_messages
from app.ai.runs.events import TraceCallback
from app.ai.runs.progress import Progress, report_progress
from app.ai.model.chat import ChatEndpoint, ChatError
from app.ai.agent.partial import blocked_plan, checked_partial


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
                         retrieved: str, max_tokens: int = 16384,
                         provider_endpoints: list[ChatEndpoint] | None = None):
    turn_started = asyncio.get_running_loop().time()
    preferred_provider_key = None

    async def routed_trace(kind, data):
        nonlocal preferred_provider_key
        if kind == 'provider.selected':
            preferred_provider_key = data.get('provider_key')
        if on_trace:
            await on_trace(kind, data)

    async def complete_tools(**request):
        # GLM-5.3 forces thinking; routine guidance uses its supported low
        # effort rather than disabling thinking or reducing output tokens.
        if (harness.name in {"guide", "direct", "plan", "configuration", "query", "planning"}
                and model.lower() in {"glm-5.3", "glm-5.3-flash", "glm-5.3-flashx"}
                and urlsplit(base_url).hostname in {"open.bigmodel.cn", "api.z.ai"}):
            request["reasoning_effort"] = "low"
        if provider_endpoints:
            return await model_gateway.complete_tools_routed(
                endpoints=provider_endpoints, preferred_provider_key=preferred_provider_key,
                on_progress=on_progress, on_trace=routed_trace, **request)
        return await model_gateway.complete_tools(**request, max_tokens=max_tokens)

    messages = build_agent_messages_for_turn(
        history, memory, page_title=page_title, page_path=page_path, can=can,
        cannot=cannot, page_context=page_context, harness=harness, retrieved=retrieved,
    )
    remaining = harness.turn_timeout_seconds - (asyncio.get_running_loop().time() - turn_started)
    if remaining <= 0:
        raise ChatError('本轮任务时间已用尽，已停止执行。', 'timeout')

    async def consume_steering(step):
        incoming = await on_step(step) if on_step else []
        users = [item for item in incoming if item.get('role') == 'user']
        if users:
            tool_scope.configure_request(str(users[-1].get('content') or ''))
            configure_history = getattr(tool_scope, 'configure_planning_history', None)
            if callable(configure_history):
                configure_history(messages + incoming)
        return incoming

    loop = ReactLoop(
        base_url=base_url, api_key=api_key, model=model,
        timeout=harness.step_timeout_seconds if provider_endpoints else min(timeout, harness.step_timeout_seconds),
        messages=messages,
        tools=tool_scope.definitions, executor=tool_scope.execute,
        caller=complete_tools, stop_when=lambda: (getattr(tool_scope, "clarification", None) is not None or tool_scope.plan is not None or (
            harness.name == 'query' and getattr(tool_scope, 'permission_denied', False) is True)),
        on_progress=on_progress, on_trace=on_trace, on_step=consume_steering if on_step else None,
        max_steps=harness.max_steps, temperature=harness.temperature,
        cycle_timeout_seconds=harness.step_timeout_seconds,
        turn_timeout_seconds=remaining,
        trace_iterations=True,
        final_guard=getattr(tool_scope, 'final_guard', None),
    )
    try:
        outcome = await loop.run()
        if harness.name == 'query' and getattr(tool_scope, 'permission_denied', False) is True:
            return AgentOutcome(
                text='本次查询被拒绝：当前账号缺少教务管理权限，无法查询学校级学生名单、任课或课表数据。'
                     '聊天中自称管理员不会改变账号权限。请联系本校管理员核对当前账号。',
                steps=outcome.steps)
        return outcome
    except ChatError as exc:
        # Preserve only program-checked evidence, not a model's rejected answer.
        # No new request, query or unbudgeted cleanup is performed here.
        exc.partial_result = checked_partial(tool_scope, exc.message)
        exc.partial_task_plan = blocked_plan(getattr(tool_scope, 'task_plan', None), exc.message)
        raise
