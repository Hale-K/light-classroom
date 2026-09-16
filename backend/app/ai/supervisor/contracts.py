"""Supervisor 与子任务之间的稳定数据契约。

契约只描述调度事实，不携带模型生成的工具定义；工具权限仍由 ToolGateway
在执行边界校验。这样后续接入不同的 Supervisor 实现时，Run 事件格式保持稳定。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
import json


@dataclass(frozen=True, slots=True)
class SupervisorContext:
    """一次 Supervisor 调用的最小可信上下文。

    只携带路由和授权所需的元数据；业务大对象通过引用或子任务工具读取，
    不把主 Agent 的完整对话历史复制给每个子任务。
    """

    run_id: str | None = None
    request_id: str | None = None
    tenant_id: int | None = None
    user_id: int | None = None
    intent: str | None = None
    page_path: str | None = None
    allowed_tools: frozenset[str] = frozenset()
    metadata: dict[str, Any] = field(default_factory=dict)

    def for_task(self, task: "SupervisorTask") -> "SupervisorContext":
        """返回仅保留当前任务工具权限的上下文副本。"""
        return SupervisorContext(
            run_id=self.run_id,
            request_id=self.request_id,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            intent=self.intent,
            page_path=self.page_path,
            allowed_tools=self.allowed_tools.intersection(task.allowed_tools),
            metadata={**self.metadata, "task_id": task.id},
        )

    def trace_data(self, task: "SupervisorTask" | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {
            "run_id": self.run_id,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "intent": self.intent,
        }
        if task is not None:
            data.update({"task_id": task.id, "allowed_tools": sorted(self.for_task(task).allowed_tools)})
        return {key: value for key, value in data.items() if value is not None}

    def task_context(self, task: "SupervisorTask") -> "SupervisorTaskContext":
        return SupervisorTaskContext(
            run_id=self.run_id,
            request_id=self.request_id,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            intent=self.intent,
            page_path=self.page_path,
            task_id=task.id,
            label=task.label,
            instruction=task.instruction,
            allowed_tools=self.allowed_tools.intersection(task.allowed_tools),
            input_refs=tuple(self.metadata.get("input_refs", ())),
        )


@dataclass(frozen=True, slots=True)
class SupervisorTaskContext:
    """子任务的私有窗口；刻意不包含主 Agent 对话 turns。"""

    run_id: str | None
    request_id: str | None
    tenant_id: int | None
    user_id: int | None
    intent: str | None
    page_path: str | None
    task_id: str
    label: str
    instruction: str
    allowed_tools: frozenset[str] = frozenset()
    input_refs: tuple[str, ...] = ()
    private_state: dict[str, Any] = field(default_factory=dict)

    def trace_data(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "allowed_tools": sorted(self.allowed_tools),
            "input_refs": list(self.input_refs),
        }




class SupervisorKind(StrEnum):
    READINESS = "readiness"
    DIAGNOSIS = "diagnosis"


class SupervisorResultStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class SupervisorTask:
    """由主管分配给一个只读子任务执行器的工作单元。"""

    id: str
    label: str
    instruction: str
    allowed_tools: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SupervisorResult:
    """子任务结果；事实、缺失项和建议分开，便于主管安全汇总。"""

    task_id: str
    status: SupervisorResultStatus
    facts: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    summary: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def normalize_supervisor_result(task: SupervisorTask, output: Any, *, metadata: dict[str, Any] | None = None) -> SupervisorResult:
    """把子任务输出规范化为可汇总的结构化结果。"""
    if isinstance(output, SupervisorResult):
        return output
    payload: dict[str, Any] = {}
    if isinstance(output, dict):
        payload = output
    elif isinstance(output, str):
        text = output.strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            pass
        if not payload:
            payload = {"summary": text}
            for line in text.splitlines():
                for marker, key in (("事实：", "facts"), ("缺少：", "missing"), ("下一步：", "next_steps")):
                    if line.strip().startswith(marker):
                        payload[key] = [item.strip() for item in line.split("：", 1)[1].replace("；", "、").split("、") if item.strip()]
    def values(key: str) -> tuple[str, ...]:
        value = payload.get(key, ())
        if isinstance(value, str):
            value = [value]
        return tuple(str(item).strip() for item in value if str(item).strip()) if isinstance(value, (list, tuple)) else ()
    return SupervisorResult(
        task_id=task.id,
        status=SupervisorResultStatus.SUCCEEDED,
        facts=values("facts"), missing=values("missing"), next_steps=values("next_steps"),
        summary=str(payload.get("summary") or payload.get("message") or output or "").strip(),
        metadata=metadata or {},
    )


def aggregate_report(kind: SupervisorKind, results: tuple[SupervisorResult, ...], tasks: tuple[SupervisorTask, ...]) -> "SupervisorReport":
    def unique(field: str) -> tuple[str, ...]:
        seen: set[str] = set()
        output: list[str] = []
        for result in results:
            for item in getattr(result, field):
                if item not in seen:
                    seen.add(item)
                    output.append(item)
        return tuple(output)
    sections = [f"### {task.label}\n{result.summary}" for task, result in zip(tasks, results) if result.summary]
    return SupervisorReport(
        kind=kind, results=results, summary="\n\n".join(sections),
        facts=unique("facts"), missing=unique("missing"), next_steps=unique("next_steps"),
    )


@dataclass(frozen=True, slots=True)
class SupervisorReport:
    """主管向 AssistantGateway 返回的聚合结果。"""

    kind: SupervisorKind
    results: tuple[SupervisorResult, ...] = ()
    summary: str = ""
    facts: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()

    @property
    def failed_tasks(self) -> tuple[str, ...]:
        return tuple(
            result.task_id
            for result in self.results
            if result.status is SupervisorResultStatus.FAILED
        )
