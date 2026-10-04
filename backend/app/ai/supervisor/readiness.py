"""排课准备检查 Supervisor 的第一版只读编排器。"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.ai.supervisor.contracts import (
    SupervisorKind,
    SupervisorContext,
    SupervisorTaskContext,
    aggregate_report,
    normalize_supervisor_result,
    SupervisorReport,
    SupervisorResult,
    SupervisorResultStatus,
    SupervisorTask,
)
from app.ai.intent import IntentGateway


ReadinessExecutor = Callable[[SupervisorTask, SupervisorTaskContext], Awaitable[str]]
ReadinessEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


def preparation_guidance(steps: list[dict]) -> tuple[str, list[dict], bool]:
    """按业务顺序推荐第一个未完成步骤；缺少基础条件时不评价排课细项。"""
    first_missing = next((step for step in steps if not step["done"]), None)
    foundations = {"year", "personnel", "space", "allocation", "class_planning", "grid", "hours", "assignments"}
    observed = {step["key"]: step["done"] for step in steps}
    foundations_ready = all(observed.get(key, False) for key in foundations)
    lines = ["### 当前结论"]
    if not steps:
        lines += ["暂未取得排课准备清单，请稍后重试；本轮无法判断前置条件。"]
    elif first_missing:
        lines += [f"下一步先完成：**{first_missing['title']}**。", first_missing["detail"]]
    else:
        lines += ["基础流程已有记录，仍需核对本次课量、教师和资源约束；不能据此保证排课无冲突。"]
    lines += ["", "### 推荐操作顺序"]
    pending_seen = False
    for index, step in enumerate(steps, 1):
        if step["done"]:
            state = "已有基础记录"
        elif not pending_seen:
            state = "当前应处理"
            pending_seen = True
        else:
            state = "前置完成后再处理"
        lines.append(f"{index}. {step['title']}：{state}")
    if not foundations_ready:
        lines += ["", "排课前置条件尚未齐全，本轮列出基础准备状态，暂不进行后续详细诊断；没有检查对象不等于检查通过。"]
    jumps = [{
        "label": first_missing["title"], "path": first_missing["path"],
        "requires_confirmation": True,
    }] if first_missing else []
    return "\n".join(lines), jumps, foundations_ready


READINESS_TASKS: tuple[SupervisorTask, ...] = (
    SupervisorTask(
        id="schedule_setup",
        label="学期与课位",
        instruction="检查当前学年学期、课位结构和课时基础数据。",
        allowed_tools=frozenset({"lookup_schedule_setup"}),
    ),
    SupervisorTask(
        id="teacher_assignments",
        label="任教关系",
        instruction="检查当前学期教师、班级和科目的任教关系。",
        allowed_tools=frozenset({"lookup_teachers"}),
    ),
    SupervisorTask(
        id="rules",
        label="排课规则",
        instruction="检查当前学期规则组和已启用规则。",
        allowed_tools=frozenset({"lookup_rules"}),
    ),
)


class SchedulingReadinessSupervisor:
    """运行固定的只读准备检查，并把每项结果转换为 SupervisorReport。"""

    kind = SupervisorKind.READINESS
    tasks = READINESS_TASKS

    async def run(
        self,
        execute: ReadinessExecutor,
        *,
        context: SupervisorContext | None = None,
        max_retries: int = 1,
        parallel: bool = False,
        on_event: ReadinessEvent | None = None,
    ) -> SupervisorReport:
        async def run_task(task: SupervisorTask) -> SupervisorResult:
            task_context = context.task_context(task) if context else SupervisorTaskContext(
                None, None, None, None, None, None, task.id, task.label, task.instruction, task.allowed_tools,
            )
            attempts = 0
            while True:
                if on_event:
                    await on_event("supervisor.task_started", {"task_id": task.id, "label": task.label, "attempt": attempts + 1, **task_context.trace_data()})
                try:
                    output = await execute(task, task_context)
                    result = normalize_supervisor_result(task, output, metadata=task_context.trace_data())
                    if on_event:
                        await on_event("supervisor.task_succeeded", {"task_id": task.id, "attempt": attempts + 1})
                    break
                except Exception as exc:  # one failed check must not hide the other checks
                    policy = IntentGateway.failure_policy(retry_count=attempts, max_retries=max_retries)
                    if on_event:
                        await on_event("router.failure_policy", {"task_id": task.id, **policy.trace_data()})
                    if policy.action.value == "retry":
                        attempts += 1
                        if on_event:
                            await on_event("supervisor.task_retry", {"task_id": task.id, "attempt": attempts + 1, "retry_count": attempts, "error": str(exc)[:500]})
                        continue
                    result = SupervisorResult(task_id=task.id, status=SupervisorResultStatus.FAILED, summary=f"{task.label}检查失败", error=str(exc)[:500], metadata=task_context.trace_data())
                    if on_event:
                        await on_event("supervisor.task_failed", {"task_id": task.id, "attempt": attempts + 1, "error": str(exc)[:500]})
                    break
            return result

        if parallel:
            results = list(await asyncio.gather(*(run_task(task) for task in self.tasks)))
        else:
            results = []
            for task in self.tasks:
                results.append(await run_task(task))

        return aggregate_report(self.kind, tuple(results), self.tasks)
