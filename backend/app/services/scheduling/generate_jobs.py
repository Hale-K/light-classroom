"""排课生成任务：准入、进度、SSE。

进程内内存作测试回退；API 与 Celery worker 之间用 Redis 共享进度。
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from app.core.config import settings

MAX_ACTIVE_GENERATES = 2
_JOB_TTL = 6 * 3600
_MAX_JOBS = 40
# 心跳与僵尸收割阈值：queued 超时未启动 / running 心跳超时，都明确判失败并给出原因
_STALE_QUEUED_SECONDS = 120.0
_STALE_RUNNING_SECONDS = 90.0

_jobs: dict[str, "GenerateJob"] = {}
_gate = threading.Lock()
_active_tenants: set[int] = set()
_redis_client = None
_redis_checked = False


def _use_memory() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _ns() -> str:
    return "lc:sched"


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
        logger.warning(f"排课任务 Redis 不可用，进度仅本进程可见: {exc}")
        _redis_client = None
    return _redis_client


def _job_key(job_id: str) -> str:
    return f"{_ns()}:job:{job_id}"


def _ev_key(job_id: str) -> str:
    return f"{_ns()}:ev:{job_id}"


def _busy_key() -> str:
    return f"{_ns()}:busy"


@dataclass
class GenerateJob:
    id: str
    tenant_id: int
    status: str = "queued"
    history: list[dict[str, Any]] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    heartbeat_at: float = field(default_factory=time.time)
    _redis_pumps: dict[int, asyncio.Task] = field(default_factory=dict, repr=False)

    def _snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "history": self.history[-80:],
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "heartbeat_at": self.heartbeat_at,
        }

    def emit(self, event_type: str, **payload: Any) -> None:
        event = {"type": event_type, "ts": time.time(), **payload}
        self.heartbeat_at = time.time()
        if event_type == "progress":
            self.status = "running"
        elif event_type == "done":
            self.status = "done"
            self.result = payload.get("result")
        elif event_type == "error":
            self.status = "error"
            self.error = str(payload.get("message") or "生成失败")
        self.history.append(event)
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        client = _redis()
        if client is None:
            return
        packed = json.dumps(event, ensure_ascii=False, default=str)
        client.rpush(_ev_key(self.id), packed)
        client.expire(_ev_key(self.id), _JOB_TTL)
        client.set(_job_key(self.id), json.dumps(self._snapshot(), ensure_ascii=False, default=str), ex=_JOB_TTL)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self.subscribers.append(queue)
        if _redis() is None:
            for event in self.history:
                queue.put_nowait(event)
            return queue
        pump = asyncio.create_task(self._pump_redis(queue))
        self._redis_pumps[id(queue)] = pump
        return queue

    async def _pump_redis(self, queue: asyncio.Queue) -> None:
        client = _redis()
        if client is None:
            return
        idx = 0
        key = _ev_key(self.id)
        try:
            while True:
                length = await asyncio.to_thread(client.llen, key)
                while idx < length:
                    raw = await asyncio.to_thread(client.lindex, key, idx)
                    idx += 1
                    if raw:
                        await queue.put(json.loads(raw))
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            return

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        try:
            self.subscribers.remove(queue)
        except ValueError:
            pass
        pump = self._redis_pumps.pop(id(queue), None)
        if pump is not None:
            pump.cancel()


class GenerateBusy(Exception):
    def __init__(self, message: str, *, retry_after: int = 30) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


_ACQUIRE_LUA = """
if redis.call('sismember', KEYS[1], ARGV[1]) == 1 then
  return 1
end
if redis.call('scard', KEYS[1]) >= tonumber(ARGV[2]) then
  return 2
end
redis.call('sadd', KEYS[1], ARGV[1])
redis.call('expire', KEYS[1], ARGV[3])
return 0
"""


def try_acquire_generate_slot(tenant_id: int) -> None:
    client = _redis()
    if client is None:
        with _gate:
            if tenant_id in _active_tenants:
                raise GenerateBusy("本校已有课表正在生成，请等待完成后再试")
            if len(_active_tenants) >= MAX_ACTIVE_GENERATES:
                raise GenerateBusy("排课生成繁忙，请稍后再试")
            _active_tenants.add(tenant_id)
        return
    code = client.eval(_ACQUIRE_LUA, 1, _busy_key(), str(tenant_id), MAX_ACTIVE_GENERATES, _JOB_TTL)
    if int(code) == 1:
        raise GenerateBusy("本校已有课表正在生成，请等待完成后再试")
    if int(code) == 2:
        raise GenerateBusy("排课生成繁忙，请稍后再试")


def release_generate_slot(tenant_id: int) -> None:
    client = _redis()
    if client is None:
        with _gate:
            _active_tenants.discard(tenant_id)
        return
    client.srem(_busy_key(), str(tenant_id))


def reset_generate_slots() -> None:
    with _gate:
        _active_tenants.clear()
    client = _redis()
    if client is not None:
        client.delete(_busy_key())


def create_job(tenant_id: int) -> GenerateJob:
    job = GenerateJob(id=uuid.uuid4().hex, tenant_id=tenant_id)
    _jobs[job.id] = job
    if len(_jobs) > _MAX_JOBS:
        oldest = sorted(_jobs.values(), key=lambda item: item.created_at)[: len(_jobs) - _MAX_JOBS]
        for item in oldest:
            if item.status in {"done", "error"}:
                _jobs.pop(item.id, None)
    client = _redis()
    if client is not None:
        client.set(
            _job_key(job.id),
            json.dumps(job._snapshot(), ensure_ascii=False, default=str),
            ex=_JOB_TTL,
        )
    return job


def get_job(job_id: str) -> GenerateJob | None:
    job = _jobs.get(job_id)
    if job is not None:
        _reap_stale(job)
        return job
    client = _redis()
    if client is None:
        return None
    raw = client.get(_job_key(job_id))
    if not raw:
        return None
    data = json.loads(raw)
    job = GenerateJob(
        id=data["id"],
        tenant_id=int(data["tenant_id"]),
        status=data.get("status") or "queued",
        history=list(data.get("history") or []),
        result=data.get("result"),
        error=data.get("error"),
        created_at=float(data.get("created_at") or time.time()),
        heartbeat_at=float(data.get("heartbeat_at") or data.get("created_at") or time.time()),
    )
    _reap_stale(job)
    _jobs[job.id] = job
    return job


def _reap_stale(job: "GenerateJob") -> None:
    """僵尸任务收割：queued 未启动 / running 心跳超时 → 明确判失败并持久化。

    让前端看到确定性结果，而不是永远停在「已进入排课队列」。
    """
    if job.status not in ("queued", "running"):
        return
    now = time.time()
    if job.status == "queued" and now - max(job.heartbeat_at, job.created_at) < _STALE_QUEUED_SECONDS:
        return
    if job.status == "running" and now - job.heartbeat_at < _STALE_RUNNING_SECONDS:
        return
    if job.status == "queued":
        message = "排课进程未启动（worker 可能离线），请稍后重新生成"
    else:
        message = "求解进程失去心跳（可能已中断），请重新生成"
    job.emit("error", stage="error", message=message)
    # 释放该校的排课占位：worker 中断时 finally 不会执行，占位会泄漏导致后续生成全被挡
    release_generate_slot(job.tenant_id)


def touch_heartbeat(job_id: str) -> None:
    """执行期心跳：仅刷新 heartbeat_at 并重写快照，不产生事件刷屏。"""
    job = _jobs.get(job_id)
    if job is not None:
        job.heartbeat_at = time.time()
    client = _redis()
    if client is None:
        return
    raw = client.get(_job_key(job_id))
    if not raw:
        return
    data = json.loads(raw)
    data["heartbeat_at"] = time.time()
    client.set(_job_key(job_id), json.dumps(data, ensure_ascii=False), ex=_JOB_TTL)


def get_or_create_job(job_id: str, tenant_id: int) -> GenerateJob:
    job = get_job(job_id)
    if job is not None:
        return job
    job = GenerateJob(id=job_id, tenant_id=tenant_id)
    _jobs[job.id] = job
    return job
