import json
import httpx
import pytest
from app.ai.model.chat import ChatEndpoint, ChatError, _post_chat, _status_error
from app.ai.model.routing import ModelProviderRouter
from app.ai.resilience import ProviderCircuitBreaker


@pytest.mark.parametrize('code,message,reason,error_class', [
    ('1302', '当前API并发数过高', 'concurrency', 'rate_limit'),
    ('1303', 'API请求频率过高', 'request_rate', 'rate_limit'),
    ('rate_limit_exceeded', 'tokens per minute exceeded', 'token_rate', 'rate_limit'),
    ('insufficient_quota', 'quota exceeded', 'quota', 'quota'),
    ('1113', '账户余额不足', 'quota', 'quota'),
    ('1305', '模型访问量过大', 'overload', 'rate_limit'),
    ('9999', 'unspecified failure', 'unknown', 'rate_limit'),
])
def test_specific_reason_code_and_wait_are_preserved(code, message, reason, error_class):
    error = _status_error(429, json.dumps({'error': {'code': code, 'message': message + ' sk-private-secret'}}), {'Retry-After': '12.5'})
    assert error.details['provider_code'] == code
    assert error.details['limit_reason'] == reason
    assert error.details['retry_after_seconds'] == 13
    assert error.error_class == error_class
    assert '13秒' in error.message and 'sk-private' not in error.message
    assert 'sk-private' not in json.dumps(error.details)


def test_unknown_error_does_not_invent_reason_or_reset_time():
    error = _status_error(429, '<html>private gateway message</html>', {'Retry-After': 'nan'})
    assert error.details['limit_reason'] == 'unknown'
    assert error.details['retry_after_seconds'] is None
    assert '恢复时间' in error.message and '未提供' in error.message
    assert 'private' not in error.message
    dated = _status_error(429, '{}', {'Date': 'Sun, 11 Oct 2026 02:00:00 GMT', 'Retry-After': 'Sun, 11 Oct 2026 02:02:00 GMT'})
    assert dated.details['retry_after_seconds'] == 120
    for raw in ['-1', 'inf', '9999999999', 'wrong-date']:
        assert _status_error(429, '{}', {'Retry-After': raw}).details['retry_after_seconds'] is None
    assert _status_error(429, '{"error":{"retry_after":30}}').details['retry_after_source'] == 'error.retry_after'
    assert _status_error(429, '{"error":{"code":"sk-private"}}').details['provider_code'] is None


@pytest.mark.asyncio
async def test_http_header_is_forwarded_and_raw_body_not_logged(caplog):
    def handler(request):
        return httpx.Response(429, headers={'Retry-After': '90'}, json={'error': {'code': '1302', 'message': '并发超限 sk-private'}})
    with pytest.raises(ChatError) as caught:
        await _post_chat(base_url='http://test', api_key='unused', model='test', timeout=2,
            messages=[], temperature=0, max_tokens=10, transport=httpx.MockTransport(handler))
    assert caught.value.details['retry_after_seconds'] == 90
    assert 'sk-private' not in caplog.text


@pytest.mark.asyncio
async def test_backup_bad_request_does_not_hide_limit_and_wait_is_respected():
    endpoints = [ChatEndpoint('main', 'GLM', 'http://main', '', 'm', 5), ChatEndpoint('backup', '备用', 'http://backup', '', 'b', 5)]
    circuits = ProviderCircuitBreaker(cooldown_seconds=60)
    events, progress = [], []
    async def trace(kind, data):
        events.append((kind, data))
    async def report(phase, message):
        progress.append(message)
    async def invoke(endpoint, timeout):
        if endpoint.key == 'main':
            raise _status_error(429, '{"error":{"code":"1302","message":"并发超限"}}', {'Retry-After': '120'})
        raise ChatError('参数不兼容', 'bad_request')
    with pytest.raises(ChatError) as caught:
        await ModelProviderRouter(circuits).route_call(endpoints, budget_seconds=10, invoke=invoke, on_trace=trace, on_progress=report)
    assert caught.value.error_class == 'rate_limit'
    assert '120秒' in caught.value.message and '备用模型' in caught.value.message
    assert events[0][1]['details']['provider_code'] == '1302'
    assert any('120秒' in message for message in progress)
    assert not circuits.is_available('main')
    snapshot = circuits.snapshot('main')
    assert not circuits.is_available('main', now=snapshot.isolated_until - 1)
    assert circuits.is_available('main', now=snapshot.isolated_until)
