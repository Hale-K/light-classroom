import builtins
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.ai.intent import AssistantIntent
from app.ai.intent.vector import PostgresIntentClassifier, SentenceTransformerEmbedding


class FakeEmbedding:
    async def embed(self, texts):
        assert "它怎么又停了" in texts[0]
        return [[0.1] * 768]


@pytest.mark.asyncio
async def test_sentence_transformer_import_and_load_run_off_event_loop(monkeypatch, tmp_path):
    main_thread = threading.get_ident()
    import_threads: list[int] = []
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sentence_transformers":
            import_threads.append(threading.get_ident())
            return SimpleNamespace(SentenceTransformer=lambda *_args, **_kwargs: object())
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    model = await SentenceTransformerEmbedding(str(tmp_path))._get_model()

    assert model is not None
    assert import_threads
    assert all(thread_id != main_thread for thread_id in import_threads)


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
