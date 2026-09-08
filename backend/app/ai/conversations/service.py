"""Store the active assistant conversation and compact its older tail."""
from datetime import datetime

from sqlalchemy import delete, select
import tiktoken

from app.ai.conversations.models import AiConversation
from app.ai.conversations.projector import is_model_visible, project_summary

MAX_MESSAGES = 40
MAX_SUMMARY_CHARS = 8000
MAX_CONTENT_CHARS = 8000
CHAT_CONTEXT_CHARS = 4000
CHAT_CONTEXT_TOKENS = 1200


def count_tokens(text: str, model: str = "deepseek-chat") -> int:
    """Count model-compatible tokens before putting user content into context."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text or ""))


def compact_for_chat(content: str, limit: int = CHAT_CONTEXT_CHARS, token_limit: int = CHAT_CONTEXT_TOKENS) -> str:
    """Extractive compression for oversized live requests; never sends the full payload to the LLM."""
    text = " ".join((content or "").split())
    if len(text) <= limit and count_tokens(text) <= token_limit:
        return text
    # Keep the beginning and conclusion, plus sentence-sized evidence from the middle.
    parts = [p.strip() for p in __import__("re").split(r"(?<=[。！？.!?；;])", text) if p.strip()]
    if len(parts) <= 2:
        return text[:limit // 2] + "\n[内容过长，已压缩]\n" + text[-limit // 2:]
    head = "".join(parts[: max(1, len(parts) // 3)])
    tail = "".join(parts[-max(1, len(parts) // 4):])
    middle = "".join(parts[max(1, len(parts) // 3): max(1, len(parts) // 3) + 3])
    result = head[: limit // 2] + "\n[中间内容已压缩，保留关键片段]\n" + middle + tail
    result = result[:limit]
    while count_tokens(result) > token_limit and len(result) > 400:
        result = result[: int(len(result) * 0.85)]
    return result


def _clean(messages: list[dict]) -> list[dict]:
    clean: list[dict] = []
    for item in messages[-60:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()[:MAX_CONTENT_CHARS]
        if role not in ("user", "assistant") or not content:
            continue
        clean.append({
            "role": role,
            "content": content,
            "model_visible": is_model_visible(item),
        })
    return clean


def _overlap(existing: list[dict], incoming: list[dict]) -> int:
    """Find the shared boundary when a client sends a rolling history window."""
    for size in range(min(len(existing), len(incoming)), 0, -1):
        if existing[-size:] == incoming[:size]:
            return size
    return 0


def _summary_line(item: dict) -> str:
    speaker = "老师" if item["role"] == "user" else "助手"
    content = " ".join(item["content"].split())
    return f"{speaker}：{content[:500]}"


def _merge(row: AiConversation, incoming: list[dict]) -> None:
    current = _clean(row.messages or [])
    fresh = _clean(incoming)
    overlap = _overlap(current, fresh)
    merged = current + fresh[overlap:]
    # A freshly loaded client may send only a suffix of the server history.
    if fresh and len(fresh) <= len(current) and current[-len(fresh):] == fresh:
        merged = current
    dropped = merged[:-MAX_MESSAGES]
    if dropped:
        addition = "\n".join(_summary_line(item) for item in dropped if item["model_visible"])
        row.summary = project_summary(
            "\n".join(part for part in (row.summary, addition) if part)
        )[-MAX_SUMMARY_CHARS:]
    row.messages = merged[-MAX_MESSAGES:]
    row.updated_at = datetime.utcnow()


def conversation_view(row: AiConversation | None) -> dict:
    if row is None:
        return {"messages": [], "summary": "", "updated_at": None}
    return {
        "messages": _clean(row.messages or []),
        "summary": project_summary(row.summary or "")[-MAX_SUMMARY_CHARS:],
        "updated_at": row.updated_at.isoformat() + "Z",
    }


async def get_conversation(session, tenant_id: int, user_id: int) -> AiConversation | None:
    return (await session.execute(select(AiConversation).where(
        AiConversation.tenant_id == tenant_id,
        AiConversation.user_id == user_id,
    ))).scalars().first()


async def sync_conversation(session, tenant_id: int, user_id: int, messages: list[dict]) -> AiConversation:
    row = await get_conversation(session, tenant_id, user_id)
    if row is None:
        row = AiConversation(tenant_id=tenant_id, user_id=user_id)
        session.add(row)
    _merge(row, messages)
    await session.flush()
    return row


async def delete_conversation(session, tenant_id: int, user_id: int) -> None:
    await session.execute(delete(AiConversation).where(
        AiConversation.tenant_id == tenant_id,
        AiConversation.user_id == user_id,
    ))
