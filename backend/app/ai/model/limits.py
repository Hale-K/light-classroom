"""Bounded provider limit diagnostics; never expose raw response bodies."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re


def limit_details(body: str, headers=None) -> dict:
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        payload = {}
    error = payload.get('error', payload) if isinstance(payload, dict) else {}
    error = error if isinstance(error, dict) else {}
    code = str(error.get('code') or error.get('type') or '')
    # Allow business codes, not arbitrary strings that might contain secrets.
    safe_code = code if re.fullmatch(r'\d{1,12}|[a-z][a-z0-9_]{1,48}', code) and not re.search(r'secret|api_?key|token$', code) else None
    message = str(error.get('message') or (body if not payload else ''))[:4000].lower()
    text = code.lower() + ' ' + message
    reason = 'unknown'
    if re.search(r'insufficient_quota|quota_exceeded|余额不足|欠费|额度(?:不足|耗尽|用尽)|套餐.{0,8}(?:到期|耗尽)|billing|insufficient.{0,15}(?:balance|credit)|exceeded.{0,15}quota', text):
        reason = 'quota'
    elif re.search(r'并发|concurren|simultaneous', text):
        reason = 'concurrency'
    elif re.search(r'tokens? per (?:minute|second)|tokens?[_ -]per[_ -](?:minute|second)|\btpm\b|token.{0,15}(?:速率|吞吐|限额)|(?:速率|吞吐).{0,15}token', text):
        reason = 'token_rate'
    elif re.search(r'频率|频次|requests? per (?:minute|second)|requests?[_ -]per[_ -](?:minute|second)|\brpm\b', text):
        reason = 'request_rate'
    elif re.search(r'overload|访问量过大|服务.{0,8}(?:繁忙|拥堵)|负载过高', text):
        reason = 'overload'
    result = {'http_status': 429, 'provider_code': safe_code, 'limit_reason': reason,
              'retry_after_seconds': None, 'retry_after_source': None}
    values = headers or {}
    raw = values.get('retry-after') or values.get('Retry-After')
    source = 'Retry-After'
    if raw is None:
        raw = error.get('retry_after')
        source = 'error.retry_after'
    if raw is not None and not isinstance(raw, bool):
        try:
            seconds = float(raw)
        except (ValueError, TypeError):
            try:
                target = parsedate_to_datetime(str(raw))
                if target.tzinfo is None:
                    raise ValueError('Missing timezone')
                server_date = values.get('date') or values.get('Date')
                now = parsedate_to_datetime(server_date) if server_date else datetime.now(timezone.utc)
                seconds = (target - now).total_seconds()
            except (ValueError, TypeError, OverflowError):
                seconds = -1
        if math.isfinite(seconds) and 0 <= seconds <= 604800:
            result.update(retry_after_seconds=math.ceil(seconds), retry_after_source=source)
    return result


def limit_message(details: dict) -> str:
    label = {'quota': '账户额度不足或已耗尽', 'concurrency': '并发请求超过限制',
             'token_rate': 'Token吞吐超过限制', 'request_rate': '请求频率超过限制',
             'overload': '模型服务繁忙或过载', 'unknown': '具体限制原因未提供'}[details['limit_reason']]
    code = '，错误码' + details['provider_code'] if details['provider_code'] else ''
    message = f'模型服务返回HTTP 429{code}：{label}。'
    seconds = details['retry_after_seconds']
    if seconds is not None:
        message += f'服务商要求至少等待{seconds}秒后再试；不保证届时恢复。'
    elif details['limit_reason'] == 'quota':
        message += '服务商未提供恢复时间，请检查账户额度或套餐。'
    else:
        message += '服务商未提供恢复时间，请稍后重试。'
    return message
