import pytest

from app.ai.knowledge.ingest import chunk_text, content_hash, parse_document


def test_text_document_and_hash_are_deterministic():
    data = "# 规则\n\n请提前配置课位。".encode()
    parsed = parse_document("rules.md", data)
    assert parsed.text.startswith("# 规则")
    assert content_hash(data) == content_hash(data)


def test_chunking_preserves_heading_and_overlap():
    chunks = chunk_text("# 规则\n\n" + "甲" * 30, max_chars=40, overlap=5)
    assert len(chunks) > 1
    assert all(locator == "# 规则" for _, locator in chunks)
    body_chunks = chunk_text("甲" * 50, max_chars=20, overlap=5)
    assert body_chunks[0][0][-5:] == body_chunks[1][0][:5]


def test_unsupported_document_is_rejected():
    with pytest.raises(ValueError, match="仅支持"):
        parse_document("archive.zip", b"x")
