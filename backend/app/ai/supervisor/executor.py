"""Run all assigned evidence queries within the existing authorized scope."""
from typing import Protocol

from app.ai.supervisor.contracts import SupervisorTask, SupervisorResult, SupervisorResultStatus, normalize_supervisor_result


class ReadOnlyScope(Protocol):
    async def execute(self, name: str, arguments: str) -> str: ...


async def execute_task_tools(task: SupervisorTask, scope: ReadOnlyScope, allowed_tools: frozenset[str]) -> SupervisorResult:
    names = sorted(task.allowed_tools.intersection(allowed_tools))
    if not names:
        raise RuntimeError(f"任务 {task.id} 没有配置只读工具")
    results = []
    for name in names:
        try:
            output = await scope.execute(name, "{}")
            results.append(normalize_supervisor_result(task, output))
        except Exception as exc:
            results.append(SupervisorResult(task.id, SupervisorResultStatus.FAILED,
                summary=f"{task.label}查询失败，无法确认该项", error=str(exc)[:500]))
    failed = [result for result in results if result.status is SupervisorResultStatus.FAILED]
    return SupervisorResult(
        task.id, SupervisorResultStatus.FAILED if failed else SupervisorResultStatus.SUCCEEDED,
        facts=tuple(item for result in results for item in result.facts),
        missing=tuple(item for result in results for item in result.missing),
        next_steps=tuple(item for result in results for item in result.next_steps),
        summary="\n\n".join(result.summary for result in results if result.summary),
        error="；".join(result.error or "查询失败" for result in failed) or None,
        metadata={"queried_tools": names},
    )
