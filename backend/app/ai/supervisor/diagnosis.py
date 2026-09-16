"""排课失败诊断 Supervisor 的第一版只读证据编排器。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.ai.supervisor.contracts import (
    SupervisorKind,
    SupervisorContext,
    SupervisorReport,
    SupervisorResult,
    SupervisorResultStatus,
    SupervisorTask,
)


DiagnosisExecutor = Callable[[SupervisorTask], Awaitable[str]]
DiagnosisEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


DIAGNOSIS_TASKS: tuple[SupervisorTask, ...] = (
    SupervisorTask(
        id="generation_status",
        label="排课任务状态",
        instruction="读取最近一次排课任务的状态、阶段和失败信息。",
        allowed_tools=frozenset({"lookup_generation_status"}),
    ),
    SupervisorTask(
        id="schedule_setup",
        label="排课基础数据",
        instruction="核对学期、课位、课时和任教关系是否完整。",
        allowed_tools=frozenset({"lookup_schedule_setup"}),
    ),
    SupervisorTask(
        id="rules",
        label="排课规则",
        instruction="读取当前学期规则组、启用状态和硬约束。",
        allowed_tools=frozenset({"lookup_rules"}),
    ),
)


class SchedulingDiagnosisSupervisor:
    """收集排课失败证据；不执行重试、写入或规则修改。"""

    kind = SupervisorKind.DIAGNOSIS
    tasks = DIAGNOSIS_TASKS

    async def run(
        self,
        execute: DiagnosisExecutor,
        *,
        context: SupervisorContext | None = None,
        on_event: DiagnosisEvent | None = None,
    ) -> SupervisorReport:
        results: list[SupervisorResult] = []
        for task in self.tasks:
            if on_event:
                await on_event("supervisor.task_started", {"task_id": task.id, "label": task.label, **(context.trace_data(task) if context else {})})
            try:
                output = (await execute(task)).strip()
                result = SupervisorResult(
                    task_id=task.id,
                    status=SupervisorResultStatus.SUCCEEDED,
                    summary=output,
                    metadata=context.trace_data(task) if context else {},
                )
                if on_event:
                    await on_event("supervisor.task_succeeded", {"task_id": task.id})
            except Exception as exc:
                result = SupervisorResult(
                    task_id=task.id,
                    status=SupervisorResultStatus.FAILED,
                    summary=f"{task.label}检查失败",
                    error=str(exc)[:500],
                    metadata=context.trace_data(task) if context else {},
                )
                if on_event:
                    await on_event("supervisor.task_failed", {"task_id": task.id, "error": str(exc)[:500]})
            results.append(result)

        sections = [
            f"### {task.label}\n{result.summary}"
            for task, result in zip(self.tasks, results)
            if result.summary
        ]
        return SupervisorReport(
            kind=self.kind,
            results=tuple(results),
            summary="\n\n".join(sections),
        )
