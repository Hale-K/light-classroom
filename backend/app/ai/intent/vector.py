"""BGE embeddings and PostgreSQL pgvector based intent classification."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent.models import AiIntentExample
from app.ai.intent.gateway import AssistantIntent, IntentDecision

logger = logging.getLogger(__name__)


class EmbeddingService(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedding:
    """Load the local BGE model lazily so API startup stays fast."""

    def __init__(self, model_path: str):
        self.model_path = model_path
        self._model: Any = None
        self._load_lock = asyncio.Lock()
        self._encode_lock = asyncio.Lock()

    async def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                path = Path(self.model_path)
                if not self.model_path or not path.is_dir():
                    raise RuntimeError("未配置可用的本地向量模型目录")
                from sentence_transformers import SentenceTransformer

                self._model = await asyncio.to_thread(
                    SentenceTransformer,
                    str(path),
                    local_files_only=True,
                )
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = await self._get_model()

        def encode() -> list[list[float]]:
            values = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            return values.tolist()

        async with self._encode_lock:
            return await asyncio.to_thread(encode)


class PostgresIntentClassifier:
    """Find the closest reviewed intent examples using cosine distance."""

    def __init__(
        self,
        embedding: EmbeddingService,
        *,
        minimum_similarity: float = 0.50,
        minimum_margin: float = 0.02,
    ):
        self.embedding = embedding
        self.minimum_similarity = minimum_similarity
        self.minimum_margin = minimum_margin

    async def __call__(
        self,
        session: AsyncSession | None,
        query: str,
        page_path: str | None,
        recent_turns: list[dict],
    ) -> IntentDecision | None:
        if session is None or not query.strip():
            return None
        context = self._context_text(query, page_path, recent_turns)
        try:
            query_vector = (await self.embedding.embed([context]))[0]
            distance = AiIntentExample.embedding.cosine_distance(query_vector).label("distance")
            rows = (
                await session.execute(
                    select(AiIntentExample.intent, distance)
                    .where(
                        AiIntentExample.enabled.is_(True),
                        AiIntentExample.embedding.is_not(None),
                    )
                    .order_by(distance)
                    .limit(20)
                )
            ).all()
        except Exception as exc:
            logger.warning("assistant.intent vector classification unavailable: %s", exc)
            return None

        similarities: dict[AssistantIntent, list[float]] = {}
        for intent_value, raw_distance in rows:
            try:
                kind = AssistantIntent(str(intent_value))
            except ValueError:
                continue
            if kind is AssistantIntent.UNKNOWN:
                continue
            similarity = 1.0 - float(raw_distance)
            similarities.setdefault(kind, []).append(similarity)
        if not similarities:
            return None
        intent_scores = {
            kind: sum(values[:3]) / min(3, len(values))
            for kind, values in similarities.items()
        }
        ranked = sorted(intent_scores.items(), key=lambda item: item[1], reverse=True)
        kind, confidence = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        if confidence < self.minimum_similarity or confidence - runner_up < self.minimum_margin:
            return IntentDecision(
                AssistantIntent.UNKNOWN,
                max(0.0, confidence),
                "pgvector",
                needs_clarification=True,
            )
        return IntentDecision(kind, min(1.0, confidence), "pgvector")

    @staticmethod
    def _context_text(query: str, page_path: str | None, recent_turns: list[dict]) -> str:
        previous = [
            str(item.get("content") or "").strip()[:500]
            for item in recent_turns[-4:-1]
            if item.get("content")
        ]
        parts = [*previous, query.strip()]
        if page_path:
            parts.append(f"当前页面：{page_path}")
        return "\n".join(parts)
