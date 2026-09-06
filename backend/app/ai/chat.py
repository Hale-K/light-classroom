"""OpenAI 兼容对话。优先用租户默认服务商，否则用环境变量 LLM_*。"""
from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.models import AiProvider
from app.core.config import settings


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


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base + "/chat/completions"
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


async def complete_chat(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    messages: list[dict],
) -> str:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": min(settings.llm_max_tokens, 2048),
        "temperature": 0.4,
    }
    try:
        async with httpx.AsyncClient(timeout=min(timeout, 120)) as client:
            resp = await client.post(_chat_url(base_url), headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise ChatError(f"模型请求失败：{exc}") from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        raise ChatError(f"模型服务 HTTP {resp.status_code}：{resp.text[:240]}")
    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ChatError("模型返回格式无法解析") from exc
    if not isinstance(text, str) or not text.strip():
        raise ChatError("模型没有返回文本")
    return text.strip()


SYSTEM = """你是轻课堂教务助手。只根据用户问题和当前页能力说明作答，用简体中文，短句。
可以解释排课、教师档案完成度、学年学期网格、多租户隔离。
不要声称能改课表格子、代点生成求解器、保存系统设置。
若信息不足，让用户点助手里的任务卡片做跳转核对。"""


def build_messages(
    turns: list[dict],
    *,
    page_title: str | None = None,
    page_path: str | None = None,
    can: list[str] | None = None,
    cannot: list[str] | None = None,
) -> list[dict]:
    extra: list[str] = []
    if page_title:
        extra.append(f"当前页：{page_title}（{page_path or ''}）")
    if can:
        extra.append("能做：" + "；".join(can[:8]))
    if cannot:
        extra.append("不能：" + "；".join(cannot[:8]))
    system = SYSTEM + ("\n" + "\n".join(extra) if extra else "")
    return [{"role": "system", "content": system}, *turns]


async def assistant_reply(
    session: AsyncSession,
    tenant_id: int,
    turns: list[dict],
    *,
    page_title: str | None = None,
    page_path: str | None = None,
    can: list[str] | None = None,
    cannot: list[str] | None = None,
) -> str:
    if not turns:
        raise ChatError("请输入内容")
    base, key, model, timeout = await resolve_chat_endpoint(session, tenant_id)
    return await complete_chat(
        base_url=base,
        api_key=key,
        model=model,
        timeout=timeout,
        messages=build_messages(
            turns, page_title=page_title, page_path=page_path, can=can, cannot=cannot,
        ),
    )
