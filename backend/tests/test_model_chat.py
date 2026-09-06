"""模型调用层健壮性：错误分类与脱敏、瞬态重试、坏返回防御。"""
import httpx
import pytest

from app.ai.model import chat
from app.ai.model.chat import ChatError, _post_chat

_MSGS = [{"role": "user", "content": "问"}]


def _call(transport):
    return _post_chat(
        base_url="http://llm.test/v1", api_key="k", model="m", timeout=5,
        messages=_MSGS, temperature=0.2, max_tokens=16, transport=transport,
    )


def _ok_response(text="好"):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}], "usage": {}})


@pytest.mark.asyncio
async def test_non_json_body_raises_parse_error():
    def handler(request):
        return httpx.Response(200, text="<html>gateway error page</html>")

    with pytest.raises(ChatError) as ei:
        await _call(httpx.MockTransport(handler))
    assert ei.value.error_class == "parse"


@pytest.mark.asyncio
async def test_non_object_json_raises_parse_error():
    def handler(request):
        return httpx.Response(200, json=[1, 2, 3])

    with pytest.raises(ChatError) as ei:
        await _call(httpx.MockTransport(handler))
    assert ei.value.error_class == "parse"


@pytest.mark.asyncio
async def test_auth_error_sanitized_without_body_leak(caplog):
    def handler(request):
        return httpx.Response(401, text='{"error":"invalid api key sk-secret123"}')

    with pytest.raises(ChatError) as ei:
        await _call(httpx.MockTransport(handler))
    assert ei.value.error_class == "auth"
    assert "sk-secret123" not in ei.value.message
    assert "sk-secret123" not in caplog.text
    assert "鉴权" in ei.value.message


@pytest.mark.asyncio
async def test_context_overflow_body_classified():
    def handler(request):
        return httpx.Response(400, text='{"error":{"message":"This model\'s maximum context length is 8192 tokens"}}')

    with pytest.raises(ChatError) as ei:
        await _call(httpx.MockTransport(handler))
    assert ei.value.error_class == "context_overflow"


@pytest.mark.asyncio
async def test_plain_bad_request_classified():
    def handler(request):
        return httpx.Response(400, text='{"error":"invalid temperature"}')

    with pytest.raises(ChatError) as ei:
        await _call(httpx.MockTransport(handler))
    assert ei.value.error_class == "bad_request"


@pytest.mark.asyncio
async def test_rate_limit_classified_and_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, text="rate limited")

    with pytest.raises(ChatError) as ei:
        await _call(httpx.MockTransport(handler))
    assert ei.value.error_class == "rate_limit"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_503_retries_once_then_succeeds(monkeypatch):
    monkeypatch.setattr(chat, "_RETRY_BACKOFF_SECONDS", 0)
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, text="upstream boom")
        return _ok_response()

    message = await _call(httpx.MockTransport(handler))
    assert message["content"] == "好"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_503_twice_raises_unavailable(monkeypatch):
    monkeypatch.setattr(chat, "_RETRY_BACKOFF_SECONDS", 0)

    def handler(request):
        return httpx.Response(503, text="upstream boom")

    with pytest.raises(ChatError) as ei:
        await _call(httpx.MockTransport(handler))
    assert ei.value.error_class == "unavailable"


@pytest.mark.asyncio
async def test_connect_error_retries_then_network(monkeypatch):
    monkeypatch.setattr(chat, "_RETRY_BACKOFF_SECONDS", 0)
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ChatError) as ei:
        await _call(httpx.MockTransport(handler))
    assert ei.value.error_class == "network"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_read_timeout_fails_fast_without_retry():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("provider too slow")

    with pytest.raises(ChatError) as ei:
        await _call(httpx.MockTransport(handler))
    assert ei.value.error_class == "network"
    assert len(calls) == 1, "读超时不重试，尽快交给上层按已耗时间决定降级或放弃"
