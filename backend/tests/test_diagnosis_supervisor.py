import pytest

from app.ai.supervisor import SchedulingDiagnosisSupervisor


@pytest.mark.asyncio
async def test_diagnosis_supervisor_collects_fixed_evidence_tasks():
    seen: list[str] = []

    async def execute(task):
        seen.append(task.id)
        assert task.allowed_tools
        return f"{task.id} evidence"

    report = await SchedulingDiagnosisSupervisor().run(execute)

    assert seen == ["generation_status", "schedule_setup", "rules"]
    assert report.failed_tasks == ()
    assert "### 排课任务状态" in report.summary
    assert "generation_status evidence" in report.summary


@pytest.mark.asyncio
async def test_diagnosis_supervisor_keeps_other_evidence_after_failure():
    async def execute(task):
        if task.id == "generation_status":
            raise RuntimeError("状态服务不可用")
        return f"{task.id} evidence"

    report = await SchedulingDiagnosisSupervisor().run(execute)

    assert report.failed_tasks == ("generation_status",)
    assert "schedule_setup evidence" in report.summary
    assert "rules evidence" in report.summary
