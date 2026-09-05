"""ChatModel：对应 Spring AI Alibaba 的 ChatClient / DashScope ChatModel。"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.model.store import AiProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


class ChatError(Exception):
    def __init__(self, message: str):
        self.message = message


async def resolve_chat_endpoint(session: AsyncSession, tenant_id: int) -> tuple[str, str, str, int]:
    stmt = (
        select(AiProvider)
        .where(AiProvider.tenant_id == tenant_id, AiProvider.status == 1)
        .order_by(AiProvider.is_default.desc(), AiProvider.sort, AiProvider.id)
    )
    row = (await session.execute(stmt)).scalars().first()
    if row and (row.base_url or "").strip() and (row.chat_model or "").strip():
        timeout = row.timeout_seconds if row.timeout_seconds and row.timeout_seconds > 0 else 60
        return row.base_url.strip(), (row.api_key or "").strip(), row.chat_model.strip(), timeout
    if (settings.llm_base_url or "").strip() and (settings.llm_api_key or "").strip():
        return settings.llm_base_url.strip(), settings.llm_api_key.strip(), settings.llm_model, 60
    raise ChatError("请先在「服务商管理」启用一条带对话模型的服务商，或在后端配置 LLM_API_KEY")


def _message_text(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        bits: list[str] = []
        for part in content:
            if isinstance(part, str):
                bits.append(part)
            elif isinstance(part, dict):
                bits.append(str(part.get("text") or ""))
        joined = "".join(bits).strip()
        if joined:
            return joined
    for key in ("reasoning_content", "reasoning"):
        extra = message.get(key)
        if isinstance(extra, str) and extra.strip():
            return extra.strip()
    return ""


@dataclass
class ToolCallOut:
    """模型要求的一次工具调用。arguments 是未经解析的 JSON 文本。"""

    id: str
    name: str
    arguments: str


@dataclass
class ChatOutcome:
    text: str = ""
    tool_calls: list[ToolCallOut] = field(default_factory=list)


def parse_tool_calls(message: object) -> list[ToolCallOut]:
    """从 OpenAI 兼容返回里取 tool_calls；没有就返回空列表。"""
    if not isinstance(message, dict):
        return []
    raw = message.get("tool_calls")
    if not isinstance(raw, list):
        return []
    out: list[ToolCallOut] = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        fn = item.get("function")
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        out.append(
            ToolCallOut(
                id=str(item.get("id") or f"call_{len(out)}"),
                name=name,
                arguments=str(fn.get("arguments") or "") or "{}",
            )
        )
    return out


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


async def _post_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    messages: list[dict],
    temperature: float,
    max_tokens: int | None,
    tools: list[dict] | None = None,
) -> dict:
    """发一轮对话，返回 OpenAI 兼容的 message 字典。"""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens if max_tokens is not None else min(settings.llm_max_tokens, 2048),
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=min(timeout, 120)) as client:
            resp = await client.post(_chat_url(base_url), headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise ChatError(f"模型请求失败：{exc}") from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        raise ChatError(f"模型服务 HTTP {resp.status_code}：{resp.text[:240]}")
    data = resp.json()
    usage = data.get("usage") or {}
    logger.info(
        "assistant.llm model=%s ms=%d completion_tokens=%s",
        model, int((time.monotonic() - started) * 1000), usage.get("completion_tokens"),
    )
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ChatError("模型返回格式无法解析") from exc
    if not isinstance(message, dict):
        raise ChatError("模型返回格式无法解析")
    return message


async def complete_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    messages: list[dict],
    temperature: float = 0.4,
    max_tokens: int | None = None,
) -> str:
    message = await _post_chat(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    text = _message_text(message)
    if not text:
        raise ChatError("模型没有返回文本")
    return text


async def complete_chat_tools(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> ChatOutcome:
    """带工具表的对话。文本与 tool_calls 都可能为空之外的情形抛 ChatError。"""
    message = await _post_chat(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
    )
    calls = parse_tool_calls(message)
    if calls:
        return ChatOutcome(text=_message_text(message), tool_calls=calls)
    text = _message_text(message)
    if not text:
        raise ChatError("模型没有返回文本")
    return ChatOutcome(text=text)
