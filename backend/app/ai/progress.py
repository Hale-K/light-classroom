"""真实执行阶段与活性心跳；不输出模型内部推理。"""
import asyncio
from contextlib import suppress
from typing import Awaitable, Callable

Progress = Callable[[str, str], Awaitable[None]]

TOOL_LABELS = {
    "lookup_generation_status": "正在核对课表生成任务的最新状态",
    "lookup_rules": "正在查询本校规则组",
    "lookup_teachers": "正在查询本校教师任教",
    "lookup_schedule_setup": "正在核对课位、课时和任教覆盖",
    "lookup_playbook": "正在查阅排课操作说明",
    "propose_rules": "正在校验规则对象和课位，准备确认草稿",
}


async def report_progress(callback: Progress | None, phase: str, message: str):
    if callback:
        await callback(phase, message)


async def drive_turn(work, heartbeat, *, interval=5, timeout=100):
    """即便 work 无输出也检查活性/取消；结束前必须回收底层协程。"""
    task = asyncio.create_task(work)
    try:
        async with asyncio.timeout(timeout):
            while True:
                done, _ = await asyncio.wait({task}, timeout=interval)
                if done:
                    return await task
                if not await heartbeat():
                    raise asyncio.CancelledError()
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
