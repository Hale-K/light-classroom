"""Celery 应用：RabbitMQ 作 broker，Redis 作结果后端。"""
from celery import Celery
from kombu import Queue
from loguru import logger

from app.core.config import settings
from app.core.logging import setup_logging

setup_logging()

celery_app = Celery(
    "light_classroom",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=30 * 60,
    task_soft_time_limit=28 * 60,
    task_default_queue="scheduling",
    task_queues=(
        Queue("scheduling"),
        Queue("academic"),
    ),
    task_routes={
        "scheduling.generate": {"queue": "scheduling"},
    },
)


@celery_app.task(name="scheduling.generate", queue="scheduling", acks_late=True)
def generate_schedule_task(job_id: str, tenant_id: int, payload: dict) -> None:
    import asyncio

    from app.workers.scheduling.generate import run_generate_payload

    payload = payload or {}
    trace_id = str(payload.get("trace_id") or job_id)[:32]
    with logger.contextualize(trace_id=trace_id):
        asyncio.run(run_generate_payload(job_id, tenant_id, payload))
