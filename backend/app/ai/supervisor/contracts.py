"""Supervisor 与子任务之间的稳定数据契约。

契约只描述调度事实，不携带模型生成的工具定义；工具权限仍由 ToolGateway
在执行边界校验。这样后续接入不同的 Supervisor 实现时，Run 事件格式保持稳定。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


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
