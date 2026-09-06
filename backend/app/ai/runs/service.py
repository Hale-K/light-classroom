"""助手任务的持久化与后台执行：重启后标记中断，不自动重放。"""
import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta
import logging

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.ai.actions import fingerprint
from app.ai.runs.models import AiRun
from app.ai.runs.progress import drive_turn
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()
# 草稿流程至少两轮模型调用（可能再澄清一次），慢服务商下 100 秒不够；单步上限 90 秒也在此闸内。
RUN_TIMEOUT = 180
STALE_SECONDS = 30


def run_view(run: AiRun) -> dict:
    now = datetime.utcnow()
    return {
        "id": run.id, "status": run.status, "phase": run.phase, "message": run.message,
        "events": run.events, "result": run.result,
        "elapsed_seconds": max(0, int(((now if run.status == 'running' else run.updated_at) - run.created_at).total_seconds())),
        "phase_elapsed_seconds": max(0, int((now - run.phase_started_at).total_seconds())),
        "heartbeat_at": run.updated_at.isoformat() + "Z",
    }


async def get_run(session, run_id: str, tenant_id: int, user_id: int, *, cancel=False) -> dict:
    run = (await session.execute(select(AiRun).where(
        AiRun.id == run_id, AiRun.tenant_id == tenant_id, AiRun.user_id == user_id,
    ).with_for_update().execution_options(populate_existing=True))).scalars().first()
    if run is None:
        raise HTTPException(404, "未找到本账号的助手任务")
    if run.status == "running":
        if cancel:
            run.status = "cancelled"
            run.message = "已取消本轮处理，未执行规则写入。"
        elif run.updated_at < datetime.utcnow() - timedelta(seconds=STALE_SECONDS):
            run.status = "interrupted"
            run.message = "服务已失去本轮心跳，任务中断。请重新发送需求，未执行规则写入。"
        if run.status != "running":
            run.updated_at = datetime.utcnow()
    await session.commit()  # Release the status row before the next poll/heartbeat.
    return run_view(run)


async def _reject_concurrent_run(session, run_id: str, tenant_id: int, user_id: int) -> None:
    """同一用户同时只放行一个在跑任务：新请求 409，防连点挤占模型调用与连接池。

    失联（超过 STALE_SECONDS 无心跳）的旧任务就地判中断，不挡新任务，
    判定口径与 get_run 一致。
    """
    cutoff = datetime.utcnow() - timedelta(seconds=STALE_SECONDS)
    rows = (await session.execute(select(AiRun).where(
        AiRun.tenant_id == tenant_id, AiRun.user_id == user_id, AiRun.status == "running",
    ).with_for_update())).scalars().all()
    for row in rows:
        if row.id == run_id:
            continue
        if row.updated_at < cutoff:
            row.status = "interrupted"
            row.message = "服务已失去本轮心跳，任务中断。请重新发送需求，未执行规则写入。"
            row.updated_at = datetime.utcnow()
        else:
            raise HTTPException(409, "上一条助手任务还在处理中，请等它完成或先取消")


async def create_run(session, run_id: str, tenant_id: int, user_id: int, payload: dict) -> tuple[dict, bool]:
    digest = fingerprint(payload)
    existing = await session.get(AiRun, run_id)
    if existing:
        if (existing.tenant_id, existing.user_id) != (tenant_id, user_id):
            raise HTTPException(404, "未找到本账号的助手任务")
        if existing.request_hash != digest:
            raise HTTPException(409, "任务编号已用于其他内容，请重新发送")
        return await get_run(session, run_id, tenant_id, user_id), False
    await _reject_concurrent_run(session, run_id, tenant_id, user_id)
    run = AiRun(id=run_id, tenant_id=tenant_id, user_id=user_id, request_hash=digest)
    session.add(run)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if await session.get(AiRun, run_id) is None:
            raise
        return await create_run(session, run_id, tenant_id, user_id, payload)
    return run_view(run), True


async def execute_run(run_id: str, tenant_id: int, user_id: int, payload: dict, *, sessions=AsyncSessionLocal):
    from app.ai.agent.teacher import handle_teacher_turn
    from app.ai.model.chat import ChatError
    from app.api.deps import get_user_permission_codes
    from app.models.org import User

    events: list[dict] = []

    async def persist(**values) -> bool:
        async with sessions() as session:
            result = await session.execute(update(AiRun).where(
                AiRun.id == run_id, AiRun.tenant_id == tenant_id,
                AiRun.user_id == user_id, AiRun.status == "running",
            ).values(updated_at=datetime.utcnow(), **values))
            await session.commit()
            return result.rowcount == 1

    async def progress(phase, message):
        now = datetime.utcnow()
        events.append({"phase": phase, "message": message, "at": now.isoformat() + "Z"})
        if not await persist(phase=phase, message=message[:300], phase_started_at=now, events=events[-30:]):
            raise asyncio.CancelledError()

    try:
        async with sessions() as session:
            user = (await session.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id, User.status == "active"))).scalars().first()
            if user is None:
                raise ChatError("账号已失效，请重新登录")
            permissions = await get_user_permission_codes(session, user_id)
            turns = [{"role": item["role"] if item["role"] in ("user", "assistant") else "user", "content": item["content"].strip()[:4000]} for item in payload["messages"][-20:] if item["content"].strip()]
            await progress("preparing", "正在结合当前页面和已有对话核对需求")
            result = await drive_turn(handle_teacher_turn(
                session, tenant_id, turns, user_id=user_id,
                can_manage_rules="scheduling:assign" in permissions,
                page_title=payload.get("page_title"), page_path=payload.get("page_path"),
                can=payload.get("can"), cannot=payload.get("cannot"),
                page_context=payload.get("page_context"),
                memory_summary=payload.get("memory_summary") or "",
                message_id=payload.get("message_id"), on_progress=progress,
            ), persist, timeout=RUN_TIMEOUT)
            # A cancellation racing completion wins if it acquired this row first.
            run = (await session.execute(select(AiRun).where(AiRun.id == run_id, AiRun.tenant_id == tenant_id, AiRun.user_id == user_id).with_for_update().execution_options(populate_existing=True))).scalars().one()
            if run.status != "running":
                await session.rollback()  # Also discard any uncommitted proposal.
                return
            run.result = asdict(result)
            run.status = "done"
            run.phase = "done"
            run.message = "处理完成，请查看回答" if not result.plan else "规则草稿已准备，等待你确认"
            run.updated_at = datetime.utcnow()
            await session.commit()  # The final answer and proposal become visible together.
    except asyncio.CancelledError:
        await persist(status="cancelled", message="本轮已停止，未执行规则写入。")
    except TimeoutError:
        await persist(status="timed_out", message=f"本轮等待超过{RUN_TIMEOUT}秒，已停止请求。请重试或拆分要求，未执行规则写入。")
    except Exception as exc:
        logger.exception("assistant run failed id=%s class=%s", run_id, getattr(exc, "error_class", "-"))
        message = exc.message if isinstance(exc, ChatError) else "处理失败，请重试；未执行规则写入。"
        await persist(status="failed", message=message[:300])


def spawn_run(run_id, tenant_id, user_id, payload):
    task = asyncio.create_task(execute_run(run_id, tenant_id, user_id, payload))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
