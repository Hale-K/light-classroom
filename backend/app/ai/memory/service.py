"""MVP structured memory: deterministic extraction, update, and retrieval."""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select

from app.ai.memory.models import AiMemory

_PATTERNS = (
    ("constraint", "user", "allergic_to", 100, re.compile(r"(?:我|本人)(?:对|对...)?([^，。；;、 ]{1,30})过敏")),
    ("preference", "user", "prefers", 60, re.compile(r"(?:我|本人)(?:喜欢|偏好|爱吃|更喜欢)([^，。；;]{1,40})")),
    ("identity", "user", "name", 80, re.compile(r"(?:我叫|我的名字是)([^，。；;]{1,40})")),
)


def extract_candidates(messages: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    for item in messages:
        if item.get("role") != "user":
            continue
        content = str(item.get("content") or "").strip()
        for kind, subject, predicate, importance, pattern in _PATTERNS:
            match = pattern.search(content)
            if match:
                value = match.group(1).strip(" ：:，,。；;的")
                if value:
                    candidates.append({
                        "type": kind, "subject": subject, "predicate": predicate,
                        "value": value, "importance": importance, "confidence": 0.9,
                        "source_message": content[:4000],
                    })
    return candidates


async def remember_messages(session, tenant_id: int, user_id: int, messages: list[dict]) -> list[AiMemory]:
    saved: list[AiMemory] = []
    for candidate in extract_candidates(messages):
        query = select(AiMemory).where(
            AiMemory.tenant_id == tenant_id, AiMemory.user_id == user_id,
            AiMemory.type == candidate["type"], AiMemory.subject == candidate["subject"],
            AiMemory.predicate == candidate["predicate"], AiMemory.status == "active",
        )
        existing = (await session.execute(query)).scalars().first()
        if existing and existing.value == candidate["value"]:
            existing.updated_at = datetime.utcnow()
            saved.append(existing)
            continue
        if existing:
            existing.status = "superseded"
            session.add(existing)
        memory = AiMemory(tenant_id=tenant_id, user_id=user_id, **candidate)
        session.add(memory)
        saved.append(memory)
    await session.flush()
    return saved


async def memory_context(session, tenant_id: int, user_id: int, query_text: str = "") -> str:
    memories = (await session.execute(select(AiMemory).where(
        AiMemory.tenant_id == tenant_id, AiMemory.user_id == user_id,
        AiMemory.status == "active",
    ).order_by(AiMemory.importance.desc(), AiMemory.updated_at.desc()).limit(20))).scalars().all()
    if query_text:
        words = set(query_text.lower().split())
        relevant = [m for m in memories if m.importance >= 90 or any(w in m.value.lower() for w in words)]
        memories = relevant or memories[:5]
    lines = [f"- {m.predicate}: {m.value}" for m in memories]
    return "\n".join(lines)
