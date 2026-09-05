from app.ai.model.chat import _message_text


def test_message_text_reads_reasoning_when_content_empty():
    assert (
        _message_text({"content": "", "reasoning_content": "  排课先填课时  "})
        == "排课先填课时"
    )


def test_message_text_reads_content_parts():
    assert _message_text({"content": [{"type": "text", "text": "步骤一"}]}) == "步骤一"
