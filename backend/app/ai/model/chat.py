"""ChatModel：对应 Spring AI Alibaba 的 ChatClient / DashScope ChatModel。"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.model.store import AiProvider
from app.core.config import settings
from app.core.secret_store import decrypt_secret

logger = logging.getLogger(__name__)


def _normalize_chat_base(provider_type: str | None, base_url: str) -> str:
    """将服务商管理里的地址规范化为聊天接口使用的 Base URL。

    Ollama 的模型探测走 /api/tags，但 OpenAI 兼容聊天接口位于 /v1 下。
    允许管理页面继续填写官方默认地址 http://127.0.0.1:11434。
    """
    base = base_url.strip().rstrip("/")
    if (provider_type or "").upper() == "OLLAMA" and not base.endswith("/v1"):
        return f"{base}/v1"
    return base


class ChatError(Exception):
    """模型调用失败。message 面向用户（不含服务商原始报文），
    error_class 供恢复与降级决策、日志分类使用。"""

    def __init__(self, message: str, error_class: str = "unknown"):
        super().__init__(message)
        self.message = message
        self.error_class = error_class


@dataclass(frozen=True)
class ChatEndpoint:
    key: str
    name: str
    base_url: str
    api_key: str
    model: str
    timeout: int


async def resolve_chat_endpoints(session: AsyncSession, tenant_id: int) -> list[ChatEndpoint]:
    stmt = (
        select(AiProvider)
        .where(
            AiProvider.tenant_id == tenant_id,
            AiProvider.status == 1,
            AiProvider.provider_type != "JEV",
        )
        .order_by(AiProvider.is_default.desc(), AiProvider.sort, AiProvider.id)
    )
    rows = (await session.execute(stmt)).scalars().all()
    endpoints = [
        ChatEndpoint(
            key=f"{tenant_id}:{row.id}",
            name=row.name,
            base_url=_normalize_chat_base(row.provider_type, row.base_url),
            api_key=decrypt_secret(row.api_key),
            model=row.chat_model.strip(),
            timeout=row.timeout_seconds if row.timeout_seconds and row.timeout_seconds > 0 else 60,
        )
        for row in rows
        if (row.base_url or "").strip() and (row.chat_model or "").strip()
    ]
    if (settings.llm_base_url or "").strip() and (settings.llm_api_key or "").strip():
        env_endpoint = ChatEndpoint(
            key=f"{tenant_id}:env",
            name="系统备用模型",
            base_url=settings.llm_base_url.strip(),
            api_key=settings.llm_api_key.strip(),
            model=settings.llm_model,
            timeout=60,
        )
        if not any(
            item.base_url == env_endpoint.base_url and item.model == env_endpoint.model
            for item in endpoints
        ):
            endpoints.append(env_endpoint)
    if endpoints:
        return endpoints
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


# 上下文超长的判别关键词：各家用语不一，取并集小写匹配（识别后由上层裁剪历史重试）。
_CONTEXT_OVERFLOW_MARKS = (
    "context length", "maximum context", "input length", "length of the messages",
    "too long", "上下文长度", "输入过长", "输入长度",
)
# 网关类 5xx 幂等可重试；500 多为服务商内部错误，重试意义小但无害，一并纳入。
_RETRY_STATUS = {500, 502, 503, 504}
_RETRY_BACKOFF_SECONDS = 1.0


def _status_error(status: int, body: str) -> ChatError:
    """把服务商 HTTP 错误映射成面向用户的脱敏文案；原始报文只进日志。"""
    if status == 400 and any(mark in body.lower() for mark in _CONTEXT_OVERFLOW_MARKS):
        return ChatError("对话内容超出模型上下文长度。", "context_overflow")
    mapped = {
        400: ("模型服务拒绝了本次请求，请换一种问法重试。", "bad_request"),
        401: ("模型服务商鉴权失败，请管理员检查服务商配置。", "auth"),
        402: ("模型服务额度不足，请管理员检查服务商账户。", "quota"),
        403: ("模型服务商拒绝访问，请管理员检查服务商配置。", "auth"),
        404: ("模型服务地址或模型名不可用，请管理员检查服务商配置。", "config"),
        429: ("模型服务限流中，请稍后重试。", "rate_limit"),
    }.get(status)
    if mapped:
        return ChatError(*mapped)
    if status >= 500:
        return ChatError("模型服务暂时不可用，请稍后重试。", "unavailable")
    return ChatError("模型服务返回异常状态，请稍后重试。", "bad_request")


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
    transport: httpx.AsyncTransport | None = None,
) -> dict:
    """发一轮对话，返回 OpenAI 兼容的 message 字典。

    连接失败与网关类 5xx 幂等，退避后重试一次；读超时不重试，
    尽快把失败交给上层按已耗时间决定走降级还是放弃。
    """
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
    resp: httpx.Response | None = None
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=min(timeout, 120), transport=transport) as client:
                resp = await client.post(_chat_url(base_url), headers=headers, json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if attempt == 1:
                logger.warning("assistant.llm connect fail retry model=%s err=%s", model, exc)
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                continue
            raise ChatError("无法连接模型服务，请检查网络或服务商地址。", "network") from exc
        except httpx.HTTPError as exc:
            raise ChatError("模型请求失败，请稍后重试。", "network") from exc
        if resp.status_code in _RETRY_STATUS and attempt == 1:
            logger.warning("assistant.llm http %s retry model=%s", resp.status_code, model)
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
            continue
        break
    assert resp is not None
    if resp.status_code < 200 or resp.status_code >= 300:
        body = resp.text[:400]
        logger.warning(
            "assistant.llm http_fail status=%s model=%s body_chars=%s",
            resp.status_code,
            model,
            len(body),
        )
        raise _status_error(resp.status_code, body)
    try:
        data = resp.json()
    except ValueError as exc:
        raise ChatError("模型返回格式无法解析，请重试。", "parse") from exc
    if not isinstance(data, dict):
        raise ChatError("模型返回格式无法解析，请重试。", "parse")
    usage = data.get("usage") or {}
    logger.info(
        "assistant.llm model=%s ms=%d completion_tokens=%s",
        model, int((time.monotonic() - started) * 1000), usage.get("completion_tokens"),
    )
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ChatError("模型返回格式无法解析，请重试。", "parse") from exc
    if not isinstance(message, dict):
        raise ChatError("模型返回格式无法解析，请重试。", "parse")
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
        raise ChatError("模型没有返回文本，请重试。", "empty")
    return text


async def stream_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    messages: list[dict],
    temperature: float = 0.4,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """流式逐段产出模型回复。

    长输出场景（如整份课件 HTML）整体耗时远超单次读超时，
    走 SSE 后每个数据块都会刷新读计时，连接不会被中断。
    """
    headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    started = time.monotonic()
    total = 0
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0, read=max(timeout, 120.0))
        ) as client:
            async with client.stream("POST", _chat_url(base_url), headers=headers, json=payload) as resp:
                if resp.status_code < 200 or resp.status_code >= 300:
                    body = (await resp.aread()).decode("utf-8", "ignore")[:400]
                    logger.warning("assistant.llm stream http_fail status=%s body=%s", resp.status_code, body)
                    raise _status_error(resp.status_code, body)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        delta = json.loads(data)["choices"][0].get("delta") or {}
                    except (ValueError, KeyError, IndexError, TypeError):
                        continue
                    piece = delta.get("content")
                    if isinstance(piece, str) and piece:
                        total += len(piece)
                        yield piece
    except httpx.HTTPError as exc:
        raise ChatError("模型请求失败，请稍后重试。", "network") from exc
    logger.info(
        "assistant.llm stream model=%s ms=%d chars=%d",
        model, int((time.monotonic() - started) * 1000), total,
    )
    if not total:
        raise ChatError("模型没有返回文本，请重试。", "empty")


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
        raise ChatError("模型没有返回文本，请重试。", "empty")
    return ChatOutcome(text=text)
