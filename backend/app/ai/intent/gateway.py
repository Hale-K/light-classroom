"""Classify a teacher request before selecting its execution harness.

Intent classification chooses a task strategy only. Authorization remains in
the tool gateway, so a mistaken classification cannot grant extra privileges.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Awaitable, Callable, Protocol


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
    [str, str | None, list[dict]],
    Awaitable[IntentDecision | None],
]


class IntentGatewayService(Protocol):
    async def classify(
        self,
        query: str,
        *,
        page_path: str | None = None,
        recent_turns: list[dict] | None = None,
    ) -> IntentDecision: ...


_PHRASES = MappingProxyType({
    AssistantIntent.CONFIGURATION: (
        "禁排", "连堂", "规则草稿", "新增规则", "添加规则", "创建规则", "修改规则",
        "配置规则", "设置规则", "建立规则",
    ),
    AssistantIntent.DIAGNOSIS: (
        "排课失败", "生成失败", "生成未完成", "重新生成", "不能排", "排不出来",
        "排课冲突", "卡住", "中断", "任务状态", "排课过程", "为什么失败",
    ),
    AssistantIntent.READINESS: (
        "排课准备", "准备情况", "还缺什么", "缺少什么", "核对排课", "检查排课",
        "课时方案", "课位结构", "任教关系", "任教覆盖",
    ),
})


class IntentGateway:
    """Hybrid intent gate with deterministic fallback and optional semantics.

    High-signal business phrases stay deterministic and reviewable. Ambiguous
    language can be delegated to an injected semantic classifier without
    coupling the runtime to a model vendor or embedding library.
    """

    def __init__(self, semantic_classifier: SemanticClassifier | None = None):
        self._semantic_classifier = semantic_classifier

    async def classify(
        self,
        query: str,
        *,
        page_path: str | None = None,
        recent_turns: list[dict] | None = None,
    ) -> IntentDecision:
        text = " ".join((query or "").lower().split())
        turns = list((recent_turns or [])[-6:])

        scores = {
            kind: sum(1 for phrase in phrases if phrase in text)
            for kind, phrases in _PHRASES.items()
        }
        matched_kind, matched_count = max(scores.items(), key=lambda item: item[1])
        if matched_count:
            return IntentDecision(
                kind=matched_kind,
                confidence=min(0.99, 0.86 + 0.04 * (matched_count - 1)),
                source="business_rule",
            )

        path = (page_path or "").lower()
        if "scheduling" in path and any(word in text for word in ("为什么", "怎么回事", "异常")):
            return IntentDecision(
                kind=AssistantIntent.DIAGNOSIS,
                confidence=0.78,
                source="page_context",
            )

        if self._semantic_classifier is not None:
            semantic = await self._semantic_classifier(query, page_path, turns)
            if semantic is not None and semantic.kind is not AssistantIntent.UNKNOWN:
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
