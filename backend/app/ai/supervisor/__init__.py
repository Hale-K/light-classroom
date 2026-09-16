"""受控的复杂教务任务 Supervisor 能力。"""

from app.ai.supervisor.contracts import (
    SupervisorKind,
    SupervisorContext,
    SupervisorTaskContext,
    SupervisorReport,
    SupervisorResult,
    SupervisorResultStatus,
    SupervisorTask,
)
from app.ai.supervisor.readiness import READINESS_TASKS, SchedulingReadinessSupervisor
from app.ai.supervisor.diagnosis import DIAGNOSIS_TASKS, SchedulingDiagnosisSupervisor

__all__ = [
    "SupervisorKind",
    "SupervisorContext",
    "SupervisorTaskContext",
    "SupervisorReport",
    "SupervisorResult",
    "SupervisorResultStatus",
    "SupervisorTask",
    "READINESS_TASKS",
    "SchedulingReadinessSupervisor",
    "DIAGNOSIS_TASKS",
    "SchedulingDiagnosisSupervisor",
]
