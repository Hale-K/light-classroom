"""模型工具调用失败后的只读降级策略。"""
from __future__ import annotations

from app.ai.agent.models import AssistantTurn
from app.ai.guide import rule_jumps
from app.ai.model.chat import ChatEndpoint, ChatError
from app.ai.prompt.messages import build_messages
from app.ai.runs.progress import Progress, report_progress
from app.ai.tools.retrieve import retrieve_skill


async def text_only_fallback(endpoint: ChatEndpoint, budget: int, *, query: str,
                             turns: list[dict], page_title: str | None,
                             page_path: str | None, can: list[str] | None,
                             cannot: list[str] | None, page_context: dict | None,
                             memory_summary: str, on_progress: Progress | None,
                             model_gateway) -> AssistantTurn:
    await report_progress(on_progress, "degraded", f"{endpoint.name} 的工具调用不可用，正在切换到只读说明模式")
    timeout = min(endpoint.timeout, 75, budget)
    retrieved = await retrieve_skill(query, base_url=endpoint.base_url,
        api_key=endpoint.api_key, model=endpoint.model, timeout=timeout,
        complete=model_gateway.complete)

    def messages(history: list[dict]) -> list[dict]:
        return build_messages(history, page_title=page_title, page_path=page_path,
            can=can, cannot=cannot, retrieved=retrieved,
            page_context=page_context, memory_summary=memory_summary)

    try:
        text = await model_gateway.complete(base_url=endpoint.base_url,
            api_key=endpoint.api_key, model=endpoint.model, timeout=timeout,
            messages=messages(turns))
    except ChatError as exc:
        if exc.error_class != "context_overflow":
            raise
        text = await model_gateway.complete(base_url=endpoint.base_url,
            api_key=endpoint.api_key, model=endpoint.model, timeout=timeout,
            messages=messages(turns[-6:]))
    return AssistantTurn(
        text="当前模型工具调用不可用，本轮仅提供说明，未生成可执行草稿。\n" + text,
        think=[f"优雅降级：{endpoint.name} 已切换到只读说明模式"],
        jumps=rule_jumps(query, text, page_path), model_visible=False)
