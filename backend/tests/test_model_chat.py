"""模型调用层健壮性：错误分类与脱敏、瞬态重试、坏返回防御。"""
import httpx
import pytest

from app.ai.model import chat
from app.ai.model.chat import ChatError, _post_chat

_MSGS = [{"role": "user", "content": "问"}]


@pytest.mark.asyncio
async def test_configured_provider_does_not_add_environment_backup(monkeypatch):
    from types import SimpleNamespace

    provider = SimpleNamespace(id=7, name='GLM', provider_type='ZHIPU',
        base_url='https://open.bigmodel.cn/api/paas/v4', chat_model='glm-test',
        api_key='test-key', timeout_seconds=60, max_output_tokens=16384)

    class Session:
        async def execute(self, statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [provider]))

    monkeypatch.setattr(chat, 'decrypt_secret', lambda value: value)
    monkeypatch.setattr(chat.settings, 'llm_base_url', 'http://127.0.0.1:11434/v1')
    monkeypatch.setattr(chat.settings, 'llm_api_key', 'unused-local-key')
    endpoints = await chat.resolve_chat_endpoints(Session(), 1)
    assert [(item.name, item.model) for item in endpoints] == [('GLM', 'glm-test')]


@pytest.mark.asyncio
async def test_single_provider_failure_never_announces_backup():
    from app.ai.model.routing import ModelProviderRouter
    from app.ai.resilience import ProviderCircuitBreaker

    progress, calls = [], []
    endpoint = chat.ChatEndpoint('only', 'GLM', 'http://test', '', 'glm-test', 60)

    async def invoke(item, budget):
        calls.append(item.key)
        raise ChatError('账户额度不足', 'quota')

    async def report(phase, message):
        progress.append(message)

    with pytest.raises(ChatError, match='账户额度不足'):
        await ModelProviderRouter(ProviderCircuitBreaker()).route_call(
            [endpoint], budget_seconds=120, invoke=invoke, on_progress=report)
    assert calls == ['only']
    assert not any('备用模型' in message for message in progress)


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


def test_output_budget_error_is_configuration_problem_not_user_question():
    error = chat._status_error(400, '{"error":"max_tokens must be <= 8192 sk-private"}')
    assert error.error_class == 'config'
    assert '输出额度' in error.message
    assert '换一种问法' not in error.message and 'sk-private' not in error.message


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
    assert ei.value.error_class == "timeout"
    assert "超时" in ei.value.message
    assert len(calls) == 1, "读超时不重试，尽快交给上层按已耗时间决定降级或放弃"


@pytest.mark.asyncio
async def test_truncated_response_is_not_a_final_answer():
    def handler(request):
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "length", "message": {"content": "Let me analyze the request..."},
        }]})
    with pytest.raises(ChatError) as error:
        await _call(httpx.MockTransport(handler))
    assert error.value.error_class == "incomplete_output"


@pytest.mark.asyncio
async def test_reasoning_only_tool_reply_is_rejected(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(chat, "_post_chat", AsyncMock(return_value={
        "content": "", "reasoning_content": "I'll call lookup_schedule_setup...",
    }))
    with pytest.raises(ChatError) as error:
        await chat.complete_chat_tools(base_url="http://llm.test", api_key="", model="m", timeout=5, messages=_MSGS)
    assert error.value.error_class == "empty"
