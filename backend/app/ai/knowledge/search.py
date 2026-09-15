"""Tenant-safe semantic search over knowledge chunks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.knowledge.models import KnowledgeChunk, KnowledgeDocument


class QueryEmbedding(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class KnowledgeSearchHit:
    chunk_id: int
    document_id: int
    content: str
    source_locator: str
    file_name: str
    similarity: float


class KnowledgeSearchService:
    """Search only enabled, tenant-owned chunks with a bounded result set."""

    def __init__(self, embedding: QueryEmbedding, *, minimum_similarity: float = 0.35):
        self.embedding = embedding
        self.minimum_similarity = minimum_similarity

    async def search(
        self,
        session: AsyncSession,
        *,
        tenant_id: int,
        knowledge_base_id: int,
        query: str,
        top_k: int = 5,
        max_chars: int = 6000,
    ) -> list[KnowledgeSearchHit]:
        query = query.strip()
        if not query:
            return []
        top_k = max(1, min(top_k, 20))
        max_chars = max(500, min(max_chars, 20_000))
        vector = (await self.embedding.embed([query]))[0]
        distance = KnowledgeChunk.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(KnowledgeChunk, KnowledgeDocument.file_name, distance)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.tenant_id == tenant_id,
                KnowledgeChunk.knowledge_base_id == knowledge_base_id,
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.knowledge_base_id == knowledge_base_id,
                KnowledgeDocument.status == "ready",
                KnowledgeChunk.embedding.is_not(None),
            )
            .order_by(distance)
            .limit(top_k)
        )
        rows = (await session.exec(stmt)).all()
        hits: list[KnowledgeSearchHit] = []
        used = 0
        for chunk, file_name, raw_distance in rows:
            similarity = 1.0 - float(raw_distance)
            if similarity < self.minimum_similarity:
                continue
            content = str(chunk.content or "")
            if used >= max_chars:
                break
            content = content[: max_chars - used]
            used += len(content)
            hits.append(KnowledgeSearchHit(
                chunk_id=int(chunk.id), document_id=int(chunk.document_id),
                content=content, source_locator=chunk.source_locator,
                file_name=str(file_name), similarity=similarity,
            ))
        return hits
