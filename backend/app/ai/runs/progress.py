"""真实执行阶段与活性心跳；不输出模型内部推理。"""
import asyncio
from contextlib import suppress
from typing import Awaitable, Callable

Progress = Callable[[str, str], Awaitable[None]]

TOOL_LABELS = {
    'plan_task': '正在拆解任务并建立执行计划',
    'update_plan_task': '正在更新任务计划和完成证据',
    'lookup_school_context': '正在核对学校课表模式和高考模式',
    "lookup_student_choices": "正在查询学生选科和入班",
    "lookup_teaching_assignments": "正在核对行政班与走班任课明细",
    "lookup_timetable": "正在查询已保存课表",
    "lookup_schedule_conflicts": "正在核对教师、学生和教室时段冲突",
    "lookup_remaining_capacity": "正在查询剩余课位容量",
    "lookup_subject_capacity": "正在查询学科课时容量",
    "lookup_slot_role_capacity": "正在查询不同课位的可排容量",
    "lookup_walk_classes": "正在查询走班人数和任课关系",
    "lookup_generation_log": "正在查询排课任务日志",
    "format_markdown": "正在整理回答格式",
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
