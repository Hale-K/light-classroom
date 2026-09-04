"""排课 worker：RabbitMQ 投递，线程里跑 CP-SAT。"""
from __future__ import annotations

import asyncio
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


async def run_generate_payload(job_id: str, tenant_id: int, payload: dict[str, Any]) -> None:
    from fastapi import HTTPException

    from app.api.v1.scheduling import GenerateIn, _execute_schedule_generation
    from app.db.session import AsyncSessionLocal, tenant_id_ctx
    from app.services.scheduling.generate_jobs import get_or_create_job, release_generate_slot

    current = get_or_create_job(job_id, tenant_id)

    async def on_progress(stage: str, message: str, **extra: Any) -> None:
        current.emit("progress", stage=stage, message=message, **extra)

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
                current.emit("error", stage="error", message=message, detail=detail)
            except WorkerTimeout as exc:
                await session.rollback()
                current.emit("error", stage="error", message=exc.message)
            except Exception as exc:
                await session.rollback()
                current.emit("error", stage="error", message=str(exc) or "生成失败")
    finally:
        tenant_id_ctx.reset(token)
        release_generate_slot(tenant_id)


async def _run_spawned_job(
    job_id: str,
    tenant_id: int,
    execute: Callable[..., Awaitable[Any]],
) -> None:
    from fastapi import HTTPException

    from app.db.session import AsyncSessionLocal, tenant_id_ctx
    from app.services.scheduling.generate_jobs import get_job, release_generate_slot

    current = get_job(job_id)
    if current is None:
        release_generate_slot(tenant_id)
        return

    async def on_progress(stage: str, message: str, **extra: Any) -> None:
        current.emit("progress", stage=stage, message=message, **extra)

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
                current.emit("error", stage="error", message=message, detail=detail)
            except WorkerTimeout as exc:
                await session.rollback()
                current.emit("error", stage="error", message=exc.message)
            except Exception as exc:
                await session.rollback()
                current.emit("error", stage="error", message=str(exc) or "生成失败")
    finally:
        tenant_id_ctx.reset(token)
        release_generate_slot(tenant_id)


def spawn_generate_job(tenant_id: int, payload: dict[str, Any]) -> str:
    """优先投递 RabbitMQ；broker 不可用时回退到本进程，避免本地无 MQ 时完全不能排。"""
    from app.services.scheduling.generate_jobs import create_job

    job = create_job(tenant_id)
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
            )

        asyncio.create_task(_run_spawned_job(job.id, tenant_id, _execute))
        return job.id
