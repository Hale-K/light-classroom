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
from app.ai.runs.events import run_event, trace_event
from app.ai.runs.inbox import consume, receive
from app.ai.runs.progress import drive_turn
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()
# 草稿流程至少两轮模型调用（可能再澄清一次），慢服务商下 100 秒不够；单步上限 90 秒也在此闸内。
RUN_TIMEOUT = 180
STALE_SECONDS = 30


def execution_view(events: list[dict], *, status: str) -> dict:
    """从内部轨迹投影安全的执行摘要，不公开上下文、工具结果或错误详情。"""
    mode = "pending"
    kind = None
    tasks: dict[str, dict] = {}
    for event in events:
        event_type = event.get("type")
        data = event.get("data") or {}
        if event_type == "assistant.harness.selected":
            mode = "direct" if data.get("name") == "direct" else "agent"
        elif event_type == "assistant.turn.agent_started":
            mode = "agent"
        elif event_type == "assistant.intent.classified" and data.get("kind") in {"readiness", "diagnosis"}:
            kind = data["kind"]
        elif event_type in {
            "assistant.supervisor.task_started",
            "assistant.supervisor.task_succeeded",
            "assistant.supervisor.task_failed",
            "assistant.supervisor.task_retry",
        }:
            mode = "supervisor"
            task_id = data.get("task_id")
            if task_id not in {"prerequisites", "schedule_setup", "teacher_assignments", "rules", "generation_status"}:
                continue
            task = tasks.setdefault(task_id, {
                "id": task_id,
                "label": str(data.get("label") or task_id)[:40],
                "status": "running",
                "attempt": 1,
                "retry_count": 0,
                "allowed_tools": sorted(str(tool)[:60] for tool in (data.get("allowed_tools") or []) if tool),
            })
            if event_type.endswith("task_retry"):
                task["attempt"] = max(1, int(data.get("attempt") or task["attempt"] + 1))
                task["retry_count"] = max(0, int(data.get("retry_count") or task["retry_count"] + 1))
                task["status"] = "running"
            elif data.get("attempt"):
                task["attempt"] = max(1, int(data["attempt"]))
            if event_type.endswith("task_succeeded"):
                task["status"] = "succeeded"
            elif event_type.endswith("task_failed"):
                task["status"] = "failed"
        elif event_type == "assistant.supervisor.completed":
            mode = "supervisor"
            if data.get("kind") in {"readiness", "diagnosis"}:
                kind = data["kind"]
    if mode == "pending" and status == "done":
        mode = "direct"
    return {
        "mode": mode,
        # 目前 Supervisor 顺序执行固定只读工具，没有独立模型子 Agent。
        "multi_agent": False,
        "kind": kind if mode == "supervisor" else None,
        "tasks": list(tasks.values()) if mode == "supervisor" else [],
    }


def run_view(run: AiRun) -> dict:
    now = datetime.utcnow()
    return {
        "id": run.id, "status": run.status, "phase": run.phase, "message": run.message,
        # 原始轨迹可能含模型上下文和查询结果，只保留给受控诊断通道；老师界面只收进度投影。
        "events": [event for event in run.events if event.get("visibility") != "internal"], "result": run.result,
        "checkpoint": run.checkpoint or {},
        "execution": execution_view(run.events or [], status=run.status),
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


async def steer_run(session, run_id: str, tenant_id: int, user_id: int, content: str) -> dict:
    """把运行中的用户补充写入 Inbox，由下一个 Step 消费。"""
    run = (await session.execute(select(AiRun).where(
        AiRun.id == run_id, AiRun.tenant_id == tenant_id, AiRun.user_id == user_id,
    ).with_for_update().execution_options(populate_existing=True))).scalars().first()
    if run is None:
        raise HTTPException(404, "未找到本账号的助手任务")
    if run.status != "running":
        raise HTTPException(409, "当前任务已经结束，请作为新消息继续")
    stored = list(run.events or [])
    event = receive("steer", content)
    stored.append(event)
    run.events = stored[-100:]
    run.message = "已收到方向调整，将在下一步处理"
    run.updated_at = datetime.utcnow()
    await session.commit()
    return {"accepted": True, "kind": "steer", "message_id": event["data"]["id"]}


async def get_run_trace(session, run_id: str, tenant_id: int) -> dict:
    """返回诊断轨迹；调用方必须先完成学校管理员权限校验。"""
    run = (await session.execute(select(AiRun).where(
        AiRun.id == run_id, AiRun.tenant_id == tenant_id,
    ))).scalars().first()
    if run is None:
        raise HTTPException(404, "未找到本学校的助手任务")
    return {
        "id": run.id,
        "status": run.status,
        "trace": [event for event in run.events if event.get("visibility") == "internal"],
    }


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
    from app.ai.agent.assistant_agent import handle_assistant_turn
    from app.ai.conversations import compact_for_chat, project_messages, project_summary
    from app.ai.model.chat import ChatError
    from app.api.deps import get_user_permission_codes
    from app.models.org import User

    events: list[dict] = []
    checkpoint: dict = {
        "version": 1, "stage": "received", "current_task": None,
        "completed_tasks": [], "failed_tasks": [], "retry_count": 0,
    }

    def inbox_messages(messages):
        out = []
        for item in messages:
            if item.kind == "steer":
                out.append({"role": "user", "content": f"执行方向调整：{item.content}", "_wake": item.wake})
            elif item.kind == "inject":
                out.append({"role": "system", "content": f"运行时上下文补充：{item.content}", "_wake": item.wake})
            else:
                out.append({"role": "user", "content": str(item.content), "_wake": item.wake})
        return out

    async def consume_inbox(boundary: str) -> list[dict]:
        async with sessions() as inbox_session:
            run = (await inbox_session.execute(select(AiRun).where(
                AiRun.id == run_id, AiRun.tenant_id == tenant_id,
                AiRun.user_id == user_id, AiRun.status == "running",
            ).with_for_update())).scalars().first()
            if run is None:
                raise asyncio.CancelledError()
            stored = list(run.events or [])
            messages = consume(stored, boundary)  # type: ignore[arg-type]
            if messages:
                for item in messages:
                    stored.append(trace_event("inbox.consumed", {
                        "id": item.id, "kind": item.kind, "boundary": boundary,
                    }))
                run.events = stored[-100:]
                run.updated_at = datetime.utcnow()
                await inbox_session.commit()
                events[:] = run.events
            return inbox_messages(messages)

    async def persist(**values) -> bool:
        async with sessions() as session:
            if "events" in values:
                current = (await session.execute(select(AiRun).where(
                    AiRun.id == run_id, AiRun.tenant_id == tenant_id,
                    AiRun.user_id == user_id, AiRun.status == "running",
                ).with_for_update())).scalars().first()
                if current is None:
                    return False
                proposed = list(values["events"] or [])
                known = {
                    str((event.get("data") or {}).get("id") or "")
                    for event in proposed if event.get("type") == "assistant.inbox.received"
                }
                pending = [
                    event for event in list(current.events or [])
                    if event.get("type") == "assistant.inbox.received"
                    and str((event.get("data") or {}).get("id") or "") not in known
                ]
                values["events"] = (proposed + pending)[-100:]
                events[:] = values["events"]
            result = await session.execute(update(AiRun).where(
                AiRun.id == run_id, AiRun.tenant_id == tenant_id,
                AiRun.user_id == user_id, AiRun.status == "running",
            ).values(updated_at=datetime.utcnow(), **values))
            await session.commit()
            return result.rowcount == 1

    async def progress(phase, message):
        now = datetime.utcnow()
        events.append(run_event(phase, message, at=now))
        if not await persist(phase=phase, message=message[:300], phase_started_at=now, events=events[-100:]):
            raise asyncio.CancelledError()

    async def trace(kind: str, data: dict) -> None:
        events.append(trace_event(kind, data))
        if kind == "supervisor.task_started":
            checkpoint["stage"] = "supervisor"
            checkpoint["current_task"] = data.get("task_id")
        elif kind == "supervisor.task_succeeded":
            task_id = data.get("task_id")
            if task_id and task_id not in checkpoint["completed_tasks"]:
                checkpoint["completed_tasks"].append(task_id)
            checkpoint["current_task"] = None
        elif kind == "supervisor.task_failed":
            task_id = data.get("task_id")
            if task_id and task_id not in checkpoint["failed_tasks"]:
                checkpoint["failed_tasks"].append(task_id)
            checkpoint["current_task"] = None
        elif kind == "supervisor.task_retry":
            checkpoint["retry_count"] += 1
            checkpoint["current_task"] = data.get("task_id")
        elif kind == "supervisor.completed":
            checkpoint["stage"] = "supervisor_completed"
            checkpoint["current_task"] = None
        if not await persist(events=events[-100:], checkpoint=checkpoint):
            raise asyncio.CancelledError()

    try:
        async with sessions() as session:
            user = (await session.execute(select(User).where(User.id == user_id, User.tenant_id == tenant_id, User.status == "active"))).scalars().first()
            if user is None:
                raise ChatError("账号已失效，请重新登录")
            permissions = await get_user_permission_codes(session, user_id)
            candidates = [{
                "role": item["role"] if item["role"] in ("user", "assistant") else "user",
                "content": compact_for_chat(item["content"]),
                "model_visible": item.get("model_visible", True),
            } for item in payload["messages"][-24:] if item["content"].strip()]
            turns = project_messages(candidates, limit=20)
            turns.extend(await consume_inbox("turn"))
            memory_summary = project_summary(payload.get("memory_summary") or "")
            await trace("session.turn", {
                "messages": turns,
                "page_title": payload.get("page_title"),
                "page_path": payload.get("page_path"),
                "page_context": payload.get("page_context") or {},
                "memory_summary": memory_summary,
            })
            await progress("preparing", "正在结合当前页面和已有对话核对需求")
            result = await drive_turn(handle_assistant_turn(
                session, tenant_id, turns, user_id=user_id,
                can_manage_rules="scheduling:assign" in permissions,
                page_title=payload.get("page_title"), page_path=payload.get("page_path"),
                can=payload.get("can"), cannot=payload.get("cannot"),
                page_context=payload.get("page_context"),
                memory_summary=memory_summary,
                message_id=payload.get("message_id"), on_progress=progress, on_trace=trace,
                on_step=lambda step: consume_inbox("step"),
            ), persist, timeout=RUN_TIMEOUT)
            # A cancellation racing completion wins if it acquired this row first.
            run = (await session.execute(select(AiRun).where(AiRun.id == run_id, AiRun.tenant_id == tenant_id, AiRun.user_id == user_id).with_for_update().execution_options(populate_existing=True))).scalars().one()
            if run.status != "running":
                await session.rollback()  # Also discard any uncommitted proposal.
                return
            run.result = asdict(result)
            checkpoint["stage"] = "done"
            checkpoint["current_task"] = None
            run.checkpoint = checkpoint
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
