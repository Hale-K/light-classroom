from unittest.mock import AsyncMock, Mock

import pytest

from app.ai.intent import AssistantIntent
from app.ai.intent.vector import PostgresIntentClassifier


class FakeEmbedding:
    async def embed(self, texts):
        assert "它怎么又停了" in texts[0]
        return [[0.1] * 768]


@pytest.mark.asyncio
async def test_pgvector_classifier_uses_best_intent_with_margin():
    result = Mock()
    result.all.return_value = [
        ("diagnosis", 0.12),
        ("diagnosis", 0.14),
        ("guide", 0.28),
    ]
    session = Mock()
    session.execute = AsyncMock(return_value=result)

    decision = await PostgresIntentClassifier(FakeEmbedding())(
        session,
        "它怎么又停了",
        "/scheduling",
        [{"role": "user", "content": "刚才重新生成课表"}],
    )

    assert decision is not None
    assert decision.kind is AssistantIntent.DIAGNOSIS
    assert decision.source == "pgvector"
    assert decision.confidence == pytest.approx(0.87)


@pytest.mark.asyncio
async def test_pgvector_classifier_marks_close_results_as_ambiguous():
    result = Mock()
    result.all.return_value = [("readiness", 0.20), ("diagnosis", 0.21)]
    session = Mock()
    session.execute = AsyncMock(return_value=result)

    decision = await PostgresIntentClassifier(FakeEmbedding())(
        session, "它怎么又停了", "/scheduling", []
    )

    assert decision is not None
    assert decision.kind is AssistantIntent.UNKNOWN
    assert decision.needs_clarification is True
