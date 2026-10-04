"""Classify a teacher request before selecting its execution harness.

Intent classification chooses a task strategy only. Authorization remains in
the tool gateway, so a mistaken classification cannot grant extra privileges.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import logging
import re
from typing import Awaitable, Callable, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class AssistantIntent(StrEnum):
    GUIDE = "guide"
    READINESS = "readiness"
    DIAGNOSIS = "diagnosis"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


class AssistantRoute(StrEnum):
    """Execution route selected before a harness is opened."""

    DIRECT = "direct"
    AGENT = "agent"
    SUPERVISOR = "supervisor"
    WORKFLOW = "workflow"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True, slots=True)
class IntentDecision:
    kind: AssistantIntent
    confidence: float
    source: str
    needs_clarification: bool = False
    route: AssistantRoute = AssistantRoute.AGENT

    def trace_data(self) -> dict:
        return {
            "kind": self.kind.value,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "needs_clarification": self.needs_clarification,
            "route": self.route.value,
        }


SemanticClassifier = Callable[
    [AsyncSession | None, str, str | None, list[dict]],
    Awaitable[IntentDecision | None],
]
DecisionClassifier = SemanticClassifier


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

    def __init__(
        self,
        semantic_classifier: SemanticClassifier | None = None,
        *,
        decision_classifier: DecisionClassifier | None = None,
        minimum_decision_confidence: float = 0.70,
    ):
        self._semantic_classifier = semantic_classifier
        self._decision_classifier = decision_classifier
        self._minimum_decision_confidence = minimum_decision_confidence

    _SIMPLE_ARITHMETIC = re.compile(
        r"^\s*\d{1,9}\s*[+\-*/×÷]\s*\d{1,9}\s*(?:=\s*)?[?？]?\s*$"
    )

    @staticmethod
    def _route_for(kind: AssistantIntent, route: AssistantRoute) -> AssistantRoute:
        """把意图规范化为可观测的执行模式；权限仍由 Harness/ToolGateway 控制。"""
        if route is AssistantRoute.DIRECT:
            return route
        if kind in {AssistantIntent.READINESS, AssistantIntent.DIAGNOSIS}:
            return AssistantRoute.SUPERVISOR
        if kind is AssistantIntent.CONFIGURATION:
            return AssistantRoute.HUMAN_REVIEW
        return route

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

        # Avoid loading the embedding model for requests whose complexity is
        # structurally trivial and which never need school data or tools.
        if self._SIMPLE_ARITHMETIC.fullmatch(text):
            return IntentDecision(
                kind=AssistantIntent.GUIDE,
                confidence=1.0,
                source="fast_path",
                route=AssistantRoute.DIRECT,
            )

        # Jev or another bounded decision service is optional. Any unavailable
        # or low-confidence result falls through to the existing pgvector path.
        if self._decision_classifier is not None:
            try:
                decision = await self._decision_classifier(session, query, page_path, turns)
            except Exception as exc:  # decision layer must never block the assistant
                logger.warning("assistant.router decision layer unavailable: %s", exc)
                decision = None
            if decision is not None and decision.confidence >= self._minimum_decision_confidence:
                return IntentDecision(
                    kind=decision.kind,
                    confidence=decision.confidence,
                    source=decision.source or "decision_layer",
                    needs_clarification=decision.needs_clarification,
                    route=self._route_for(decision.kind, decision.route),
                )

        if self._semantic_classifier is not None:
            semantic = await self._semantic_classifier(session, query, page_path, turns)
            if semantic is not None:
                route = self._route_for(semantic.kind, semantic.route)
                return IntentDecision(
                    kind=semantic.kind,
                    confidence=semantic.confidence,
                    source=semantic.source,
                    needs_clarification=semantic.needs_clarification,
                    route=route,
                )

        if text:
            return IntentDecision(
                kind=AssistantIntent.GUIDE,
                confidence=0.55,
                source="safe_fallback",
                route=AssistantRoute.AGENT,
            )
        return IntentDecision(
            kind=AssistantIntent.UNKNOWN,
            confidence=0.0,
            source="empty",
            needs_clarification=True,
        )
