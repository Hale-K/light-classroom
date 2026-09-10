"""Classify a teacher request before selecting its execution harness.

Intent classification chooses a task strategy only. Authorization remains in
the tool gateway, so a mistaken classification cannot grant extra privileges.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Awaitable, Callable, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class AssistantIntent(StrEnum):
    GUIDE = "guide"
    READINESS = "readiness"
    DIAGNOSIS = "diagnosis"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class IntentDecision:
    kind: AssistantIntent
    confidence: float
    source: str
    needs_clarification: bool = False

    def trace_data(self) -> dict:
        return {
            "kind": self.kind.value,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "needs_clarification": self.needs_clarification,
        }


SemanticClassifier = Callable[
    [AsyncSession | None, str, str | None, list[dict]],
    Awaitable[IntentDecision | None],
]


class IntentGatewayService(Protocol):
    async def classify(
        self,
        session: AsyncSession | None,
        query: str,
        *,
        page_path: str | None = None,
        recent_turns: list[dict] | None = None,
    ) -> IntentDecision: ...


class IntentGateway:
    """Semantic intent gate with a safe guide fallback."""

    def __init__(self, semantic_classifier: SemanticClassifier | None = None):
        self._semantic_classifier = semantic_classifier

    async def classify(
        self,
        session: AsyncSession | None,
        query: str,
        *,
        page_path: str | None = None,
        recent_turns: list[dict] | None = None,
    ) -> IntentDecision:
        text = " ".join((query or "").split())
        turns = list((recent_turns or [])[-6:])

        if self._semantic_classifier is not None:
            semantic = await self._semantic_classifier(session, query, page_path, turns)
            if semantic is not None:
                return semantic

        if text:
            return IntentDecision(
                kind=AssistantIntent.GUIDE,
                confidence=0.55,
                source="safe_fallback",
            )
        return IntentDecision(
            kind=AssistantIntent.UNKNOWN,
            confidence=0.0,
            source="empty",
            needs_clarification=True,
        )
