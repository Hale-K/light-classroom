"""助手回答缓存：固定知识类问题直接复用上一轮回答，不再重跑两轮模型。

问题分两类（按本轮实际调过的工具判定）：
- 静态：只调了 lookup_playbook 取说明书——答案不随本校数据变化，缓存 6 小时；
- 动态：查过教师/准备度/规则组/生成状态，或没调工具的纯对话——答案含本校实时
  数据或上下文，只缓存 2 分钟，兜住短时间重复提问，过期即重查。
规则草稿、降级回答、空回答一律不缓存。
存储优先 Redis（多 worker 共享命中），不可用退化为进程内字典（沿用排课任务的模式）。
改 prompt 措辞会影响答案口径，届时把 CACHE_VERSION 加一让旧缓存整体失效。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time

from app.core.config import settings

logger = logging.getLogger(__name__)

CACHE_VERSION = 1
STATIC_TTL = 6 * 3600
DYNAMIC_TTL = 120
_MAX_MEMORY_ENTRIES = 256
_KEY_PREFIX = "lc:ai:answer:"

STATIC_TOOLS = {"lookup_playbook"}

_MEMORY: dict[str, tuple[float, str]] = {}
_redis_client = None
_redis_checked = False


def _use_memory() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _redis():
    global _redis_client, _redis_checked
    if _use_memory():
        return None
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    try:
        import redis

        client = redis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=0.4,
        )
        client.ping()
        _redis_client = client
    except Exception as exc:
        logger.warning(f"助手回答缓存 Redis 不可用，仅本进程可见: {exc}")
        _redis_client = None
    return _redis_client


def answer_cache_key(
    tenant_id: int,
    model: str,
    turns: list[dict],
    *,
    page_path: str | None,
    can_manage_rules: bool,
    page_context: dict | None,
) -> str:
    """同一学校同一模型下，问题原文 + 对话上下文 + 页面 + 权限一致才算同一问。"""
    material = {
        "v": CACHE_VERSION,
        "tenant": tenant_id,
        "model": model,
        "turns": turns,
        "page": page_path or "",
        "rules_flag": can_manage_rules,
        "context": page_context or {},
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def classify_steps(tools: list[str]) -> str:
    """按本轮实际用过的工具判静态/动态；没调工具的纯对话按动态处理。"""
    return "static" if tools and set(tools) <= STATIC_TOOLS else "dynamic"


def get_cached_answer(key: str) -> dict | None:
    client = _redis()
    if client is not None:
        try:
            raw = client.get(f"{_KEY_PREFIX}{key}")
        except Exception:
            return None
    else:
        item = _MEMORY.get(key)
        if not item:
            return None
        expires, raw = item
        if expires < time.time():
            _MEMORY.pop(key, None)
            return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def put_cached_answer(
    key: str,
    *,
    text: str,
    think: list[str],
    jumps: list[dict],
    tools: list[str],
) -> str | None:
    """存一条回答，返回类别（static/dynamic）；空回答不缓存返回 None。"""
    body = (text or "").strip()
    if not body:
        return None
    kind = classify_steps(tools)
    ttl = STATIC_TTL if kind == "static" else DYNAMIC_TTL
    payload = json.dumps(
        {"text": body, "think": think, "jumps": jumps, "kind": kind},
        ensure_ascii=False,
    )
    client = _redis()
    if client is not None:
        try:
            client.setex(f"{_KEY_PREFIX}{key}", ttl, payload)
            return kind
        except Exception as exc:
            logger.warning(f"助手回答缓存写入失败，退进程内: {exc}")
    if len(_MEMORY) >= _MAX_MEMORY_ENTRIES:
        now = time.time()
        for stale in [k for k, (exp, _) in _MEMORY.items() if exp < now]:
            _MEMORY.pop(stale, None)
        if len(_MEMORY) >= _MAX_MEMORY_ENTRIES:
            _MEMORY.pop(next(iter(_MEMORY)))
    _MEMORY[key] = (time.time() + ttl, payload)
    return kind
