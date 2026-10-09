from app.ai.model.chat import _message_text


def test_message_text_never_uses_reasoning_as_answer():
    assert (
        _message_text({"content": "", "reasoning_content": "  排课先填课时  "})
        == ""
    )


def test_message_text_reads_content_parts():
    assert _message_text({"content": [{"type": "text", "text": "步骤一"}]}) == "步骤一"


def test_message_text_excludes_thinking_blocks_and_non_text_parts():
    assert _message_text({"content": "<think>private analysis</think>正式回答"}) == "正式回答"
    assert _message_text({"content": "<think>unfinished private analysis"}) == ""
    assert _message_text({"content": [
        {"type": "reasoning", "text": "private analysis"},
        {"type": "text", "text": "正式回答"},
    ]}) == "正式回答"


def test_unavailable_notice_does_not_pretend_to_diagnose_school():
    from app.ai.guide import degraded_reply
    notice = degraded_reply('帮我设置课时', '/scheduling')
    assert '本次请求未完成' in notice
    assert '核对学年' not in notice
    assert '本地说明' not in notice
