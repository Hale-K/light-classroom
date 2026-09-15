import pytest

from app.ai.knowledge.search import KnowledgeSearchService


class FakeEmbedding:
    async def embed(self, texts):
        assert texts == ["排课规则"]
        return [[0.1, 0.2]]


@pytest.mark.asyncio
async def test_empty_query_does_not_call_database():
    service = KnowledgeSearchService(FakeEmbedding())
    assert await service.search(None, tenant_id=1, knowledge_base_id=2, query=" ") == []
