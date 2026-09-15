"""排课准备检查 Supervisor 的第一版只读编排器。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.ai.supervisor.contracts import (
    SupervisorKind,
    SupervisorReport,
    SupervisorResult,
    SupervisorResultStatus,
    SupervisorTask,
)


ReadinessExecutor = Callable[[SupervisorTask], Awaitable[str]]
ReadinessEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


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
        on_event: ReadinessEvent | None = None,
    ) -> SupervisorReport:
        results: list[SupervisorResult] = []
        for task in self.tasks:
            if on_event:
                await on_event("supervisor.task_started", {"task_id": task.id, "label": task.label})
            try:
                output = (await execute(task)).strip()
                result = SupervisorResult(
                    task_id=task.id,
                    status=SupervisorResultStatus.SUCCEEDED,
                    summary=output,
                )
                if on_event:
                    await on_event("supervisor.task_succeeded", {"task_id": task.id})
            except Exception as exc:  # one failed check must not hide the other checks
                result = SupervisorResult(
                    task_id=task.id,
                    status=SupervisorResultStatus.FAILED,
                    summary=f"{task.label}检查失败",
                    error=str(exc)[:500],
                )
                if on_event:
                    await on_event("supervisor.task_failed", {"task_id": task.id, "error": str(exc)[:500]})
            results.append(result)

        sections: list[str] = []
        for task, result in zip(self.tasks, results):
            if result.summary:
                sections.append(f"### {task.label}\n{result.summary}")
        summary = "\n\n".join(sections)
        return SupervisorReport(kind=self.kind, results=tuple(results), summary=summary)
