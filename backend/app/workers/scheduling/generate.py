"""排课 worker：RabbitMQ 投递，线程里跑 CP-SAT。"""
from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from app.services.scheduling.cpsat import CpSatSolveResult, solve_daytime_cpsat
from app.services.scheduling.evening_cpsat import generate_evening_schedule


class WorkerTimeout(Exception):
    def __init__(self, label: str, timeout_seconds: float) -> None:
        super().__init__(f"{label}超时已中止")
        self.label = label
        self.timeout_seconds = timeout_seconds
        self.message = f"{label}超时已中止，请收紧规则后重试"


def solver_worker_count(available_cpus: int | None = None) -> int:
    """Bound CP-SAT parallelism and leave one CPU available for progress/heartbeats."""
    override = os.environ.get("SCHEDULING_CP_SAT_WORKERS")
    if override:
        try:
            return max(1, min(8, int(override)))
        except ValueError:
            logger.warning(f"忽略无效的 SCHEDULING_CP_SAT_WORKERS={override!r}")
    if available_cpus is None:
        process_cpu_count = getattr(os, "process_cpu_count", None)
        available_cpus = process_cpu_count() if process_cpu_count else os.cpu_count()
    cpus = max(1, int(available_cpus or 1))
    return max(1, min(8, cpus - 1))


def _heartbeat_sync_loop(job_id: str, stop: threading.Event) -> None:
    """Use a dedicated thread so solver callbacks cannot block the Redis heartbeat."""
    from app.services.scheduling.generate_jobs import touch_heartbeat

    consecutive_failures = 0
    while not stop.is_set():
        try:
            touch_heartbeat(job_id)
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            if consecutive_failures == 1 or consecutive_failures % 12 == 0:
                logger.bind(
                    event="scheduling_redis_heartbeat_failed",
                    job_id=job_id,
                    consecutive_failures=consecutive_failures,
                ).warning(f"排课 Redis 心跳刷新失败: {exc}")
        stop.wait(5)


async def _durable_heartbeat_loop(
    job_id: str,
    tenant_id: int,
    stop: asyncio.Event,
) -> None:
    """Keep restart recovery state current while the solver runs in its worker thread."""
    from app.services.scheduling.generate_job_store import record_heartbeat

    consecutive_failures = 0
    while not stop.is_set():
        try:
            await record_heartbeat(job_id, tenant_id)
            consecutive_failures = 0
        except Exception as exc:
            consecutive_failures += 1
            if consecutive_failures == 1 or consecutive_failures % 12 == 0:
                logger.bind(
                    event="scheduling_db_heartbeat_failed",
                    job_id=job_id,
                    tenant_id=tenant_id,
                    consecutive_failures=consecutive_failures,
                ).warning(f"排课数据库心跳刷新失败: {exc}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass


async def run_in_thread(fn, /, *args, timeout: float, label: str, **kwargs):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=timeout)
    except TimeoutError as exc:
        raise WorkerTimeout(label, timeout) from exc


async def run_daytime_cpsat(*, timeout: float, **kwargs) -> CpSatSolveResult:
    return await run_in_thread(
        lambda: solve_daytime_cpsat(**kwargs),
        timeout=timeout,
        label="白天课求解",
    )


async def run_evening_cpsat(*args, timeout: float, **kwargs) -> CpSatSolveResult:
    return await run_in_thread(
        generate_evening_schedule,
        *args,
        timeout=timeout,
        label="晚自习求解",
        **kwargs,
    )


async def run_generate_payload(
    job_id: str,
    tenant_id: int,
    payload: dict[str, Any],
    *,
    allow_reclaim: bool = False,
) -> None:
    from fastapi import HTTPException

    from app.api.v1.scheduling import GenerateIn, _execute_schedule_generation
    from app.db.session import AsyncSessionLocal, tenant_id_ctx
    from app.services.scheduling.generate_jobs import (
        get_or_create_job,
        release_generate_slot,
        touch_heartbeat,
    )
    from app.services.scheduling.generate_job_store import (
        claim_job,
        record_failure,
        record_progress,
    )

    current = get_or_create_job(job_id, tenant_id)
    claim = await claim_job(job_id, tenant_id, allow_reclaim=allow_reclaim)
    if claim.state == "succeeded":
        current.emit(
            "done",
            stage="done",
            message="生成完成（已恢复）",
            percent=100,
            result=claim.result or {},
        )
        release_generate_slot(tenant_id)
        return
    if claim.state == "running":
        return

    async def on_progress(stage: str, message: str, **extra: Any) -> None:
        current.emit("progress", stage=stage, message=message, **extra)
        await record_progress(job_id, tenant_id, stage, message, **extra)

    heartbeat_stop = threading.Event()
    beat = threading.Thread(
        target=_heartbeat_sync_loop, args=(job_id, heartbeat_stop), daemon=True)
    beat.start()
    durable_heartbeat_stop = asyncio.Event()
    durable_heartbeat = asyncio.create_task(
        _durable_heartbeat_loop(job_id, tenant_id, durable_heartbeat_stop)
    )
    token = tenant_id_ctx.set(tenant_id)
    try:
        current.emit("progress", stage="validating", message="任务已排队，开始校验")
        async with AsyncSessionLocal() as session:
            try:
                data = await _execute_schedule_generation(
                    session,
                    GenerateIn.model_validate(payload),
                    tenant_id,
                    on_progress=on_progress,
                    persisted_job_id=job_id,
                )
                await session.commit()
                current.emit("done", stage="done", message="生成完成", percent=100, result=data)
            except HTTPException as exc:
                await session.rollback()
                detail = exc.detail
                if isinstance(detail, dict):
                    message = str(detail.get("message") or detail)
                else:
                    message = str(detail)
                await record_failure(job_id, tenant_id, message, detail)
                current.emit("error", stage="error", message=message, detail=detail)
            except WorkerTimeout as exc:
                await session.rollback()
                await record_failure(job_id, tenant_id, exc.message)
                current.emit("error", stage="error", message=exc.message)
            except Exception as exc:
                await session.rollback()
                message = str(exc) or "生成失败"
                await record_failure(job_id, tenant_id, message)
                current.emit("error", stage="error", message=message)
    finally:
        durable_heartbeat_stop.set()
        await durable_heartbeat
        heartbeat_stop.set()
        beat.join(timeout=1)
        tenant_id_ctx.reset(token)
        release_generate_slot(tenant_id)


async def _run_spawned_job(
    job_id: str,
    tenant_id: int,
    execute: Callable[..., Awaitable[Any]],
) -> None:
    from fastapi import HTTPException

    from app.db.session import AsyncSessionLocal, tenant_id_ctx
    from app.services.scheduling.generate_jobs import get_job, release_generate_slot, touch_heartbeat
    from app.services.scheduling.generate_job_store import (
        claim_job,
        record_failure,
        record_progress,
    )

    current = get_job(job_id)
    if current is None:
        release_generate_slot(tenant_id)
        return
    claim = await claim_job(job_id, tenant_id)
    if claim.state == "succeeded":
        current.emit(
            "done",
            stage="done",
            message="生成完成（已恢复）",
            percent=100,
            result=claim.result or {},
        )
        release_generate_slot(tenant_id)
        return
    if claim.state == "running":
        return

    async def on_progress(stage: str, message: str, **extra: Any) -> None:
        current.emit("progress", stage=stage, message=message, **extra)
        await record_progress(job_id, tenant_id, stage, message, **extra)

    heartbeat_stop = threading.Event()
    beat = threading.Thread(
        target=_heartbeat_sync_loop, args=(job_id, heartbeat_stop), daemon=True)
    beat.start()
    durable_heartbeat_stop = asyncio.Event()
    durable_heartbeat = asyncio.create_task(
        _durable_heartbeat_loop(job_id, tenant_id, durable_heartbeat_stop)
    )
    token = tenant_id_ctx.set(tenant_id)
    try:
        current.emit("progress", stage="validating", message="任务已排队，开始校验")
        async with AsyncSessionLocal() as session:
            try:
                data = await execute(session, on_progress)
                await session.commit()
                current.emit("done", stage="done", message="生成完成", percent=100, result=data)
            except HTTPException as exc:
                await session.rollback()
                detail = exc.detail
                if isinstance(detail, dict):
                    message = str(detail.get("message") or detail)
                else:
                    message = str(detail)
                await record_failure(job_id, tenant_id, message, detail)
                current.emit("error", stage="error", message=message, detail=detail)
            except WorkerTimeout as exc:
                await session.rollback()
                await record_failure(job_id, tenant_id, exc.message)
                current.emit("error", stage="error", message=exc.message)
            except Exception as exc:
                await session.rollback()
                message = str(exc) or "生成失败"
                await record_failure(job_id, tenant_id, message)
                current.emit("error", stage="error", message=message)
    finally:
        durable_heartbeat_stop.set()
        await durable_heartbeat
        heartbeat_stop.set()
        beat.join(timeout=1)
        tenant_id_ctx.reset(token)
        release_generate_slot(tenant_id)


def spawn_generate_job(
    tenant_id: int,
    payload: dict[str, Any],
    *,
    job_id: str | None = None,
) -> str:
    """优先投递 RabbitMQ；broker 不可用时回退到本进程，避免本地无 MQ 时完全不能排。"""
    from app.services.scheduling.generate_jobs import create_job

    job = create_job(tenant_id, job_id)
    job.emit("progress", stage="queued", message="已进入排课队列")
    try:
        from app.workers.celery_app import generate_schedule_task

        generate_schedule_task.apply_async(args=[job.id, tenant_id, payload], queue="scheduling")
        return job.id
    except Exception as exc:
        logger.warning(f"RabbitMQ 投递失败，回退本进程执行: {exc}")

        async def _execute(session, on_progress):
            from app.api.v1.scheduling import GenerateIn, _execute_schedule_generation

            return await _execute_schedule_generation(
                session,
                GenerateIn.model_validate(payload),
                tenant_id,
                on_progress=on_progress,
                persisted_job_id=job.id,
            )

        asyncio.create_task(_run_spawned_job(job.id, tenant_id, _execute))
        return job.id


async def recover_incomplete_jobs() -> int:
    """Republish durable jobs that were queued or interrupted by a restart."""
    from app.db.session import AsyncSessionLocal
    from app.services.scheduling.generate_job_store import prepare_recovery_jobs

    async with AsyncSessionLocal() as session:
        jobs = await prepare_recovery_jobs(session)
    for item in jobs:
        spawn_generate_job(
            int(item["tenant_id"]),
            dict(item["payload"]),
            job_id=str(item["job_id"]),
        )
        logger.bind(
            event="scheduling_job_republished",
            job_id=item["job_id"],
            tenant_id=item["tenant_id"],
        ).warning("重启后重新投递排课任务")
    return len(jobs)
