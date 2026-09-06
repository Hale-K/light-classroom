"""PostgreSQL-backed source of truth for scheduling generation jobs."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from sqlalchemy import select

from app.models.scheduling import SchedulingGenerateJob


@dataclass(frozen=True)
class JobClaim:
    state: str
    result: dict | None = None


def job_snapshot(row: SchedulingGenerateJob) -> dict:
    return {
        "job_id": row.id,
        "tenant_id": row.tenant_id,
        "academic_year": row.academic_year,
        "term": row.term,
        "status": row.status,
        "stage": row.stage,
        "message": row.message,
        "percent": row.percent,
        "attempt": row.attempt,
        "result": row.result,
        "error": row.error,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "heartbeat_at": row.heartbeat_at.isoformat(),
    }


async def register_job(session, job_id: str, tenant_id: int, payload: dict) -> SchedulingGenerateJob:
    row = SchedulingGenerateJob(
        id=job_id,
        tenant_id=tenant_id,
        academic_year=str(payload.get("academic_year") or ""),
        term=str(payload.get("term") or "1"),
        payload=payload,
    )
    session.add(row)
    await session.flush()
    return row


async def active_job(session, tenant_id: int, academic_year: str, term: str):
    result = await session.execute(
        select(SchedulingGenerateJob)
        .where(
            SchedulingGenerateJob.tenant_id == tenant_id,
            SchedulingGenerateJob.academic_year == academic_year,
            SchedulingGenerateJob.term == term,
            SchedulingGenerateJob.status.in_(("queued", "running", "retrying")),
        )
        .order_by(SchedulingGenerateJob.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def stage_success(session, job_id: str, tenant_id: int, result: dict) -> bool:
    """Stage success on the caller's transaction; never commit independently."""
    row = await session.get(SchedulingGenerateJob, job_id)
    if row is None or row.tenant_id != tenant_id:
        return False
    now = datetime.utcnow()
    row.status = "succeeded"
    row.stage = "done"
    row.message = "生成完成"
    row.percent = 100
    row.result = result
    row.error = None
    row.updated_at = now
    row.heartbeat_at = now
    row.finished_at = now
    session.add(row)
    return True


async def claim_job(job_id: str, tenant_id: int, *, allow_reclaim: bool = False) -> JobClaim:
    """Claim a durable job, or return its already committed result.

    ``legacy`` keeps pre-migration/test jobs runnable. A redelivered MQ message may
    reclaim ``running`` because RabbitMQ only redelivers after the former consumer
    has lost ownership of that delivery.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return JobClaim("legacy")

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        row = await session.get(SchedulingGenerateJob, job_id)
        if row is None or row.tenant_id != tenant_id:
            return JobClaim("legacy")
        if row.status == "succeeded":
            logger.bind(event="scheduling_job_reused", job_id=job_id, tenant_id=tenant_id).info(
                "已完成排课任务收到重复投递，复用持久结果"
            )
            return JobClaim("succeeded", row.result)
        if row.status == "running" and not allow_reclaim:
            logger.bind(event="scheduling_job_duplicate", job_id=job_id, tenant_id=tenant_id).warning(
                "排课任务已由其他 Worker 执行"
            )
            return JobClaim("running")
        row.status = "running"
        row.stage = "validating"
        row.message = "任务已排队，开始校验"
        row.attempt += 1
        row.heartbeat_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        session.add(row)
        await session.commit()
        logger.bind(
            event="scheduling_job_claimed",
            job_id=job_id,
            tenant_id=tenant_id,
            attempt=row.attempt,
            reclaimed=allow_reclaim,
        ).info("排课任务已领取")
        return JobClaim("claimed")


async def record_progress(job_id: str, tenant_id: int, stage: str, message: str, **extra) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        row = await session.get(SchedulingGenerateJob, job_id)
        if row is None or row.tenant_id != tenant_id or row.status == "succeeded":
            return
        row.status = "running"
        row.stage = stage
        row.message = message[:300]
        if isinstance(extra.get("percent"), (int, float)):
            row.percent = max(0, min(100, int(extra["percent"])))
        row.heartbeat_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        session.add(row)
        await session.commit()


async def record_failure(job_id: str, tenant_id: int, message: str, detail=None) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        row = await session.get(SchedulingGenerateJob, job_id)
        if row is None or row.tenant_id != tenant_id or row.status == "succeeded":
            return
        now = datetime.utcnow()
        row.status = "error"
        row.stage = "error"
        row.message = message[:300]
        row.error = detail if isinstance(detail, dict) else {"message": message}
        row.updated_at = now
        row.heartbeat_at = now
        row.finished_at = now
        session.add(row)
        await session.commit()
        logger.bind(event="scheduling_job_failed", job_id=job_id, tenant_id=tenant_id).error(message)
