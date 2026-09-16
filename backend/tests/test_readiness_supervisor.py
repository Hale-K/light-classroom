import asyncio
import pytest

from app.ai.supervisor import SchedulingReadinessSupervisor


@pytest.mark.asyncio
async def test_readiness_supervisor_runs_server_owned_tasks_and_emits_events():
    supervisor = SchedulingReadinessSupervisor()
    seen: list[str] = []
    events: list[str] = []

    async def execute(task, task_context):
        seen.append(task.id)
        assert len(task.allowed_tools) == 1
        assert task_context.task_id == task.id
        assert task_context.allowed_tools == task.allowed_tools
        return f"{task.label}已检查"

    async def on_event(kind, data):
        events.append(f"{kind}:{data['task_id']}")

    report = await supervisor.run(execute, on_event=on_event)

    assert seen == ["schedule_setup", "teacher_assignments", "rules"]
    assert len(report.results) == 3
    assert report.failed_tasks == ()
    assert "### 学期与课位" in report.summary
    assert events.count("supervisor.task_started:schedule_setup") == 1
    assert "规则已检查" in report.summary


@pytest.mark.asyncio
async def test_readiness_supervisor_isolates_failed_check():
    async def execute(task, task_context):
        if task.id == "teacher_assignments":
            raise RuntimeError("连接超时")
        return f"{task.id} ok"

    report = await SchedulingReadinessSupervisor().run(execute)

    assert report.failed_tasks == ("teacher_assignments",)
    assert report.results[0].summary == "schedule_setup ok"
    assert report.results[2].summary == "rules ok"


@pytest.mark.asyncio
async def test_readiness_supervisor_retries_only_failed_task():
    attempts: dict[str, int] = {}
    events: list[str] = []

    async def execute(task, task_context):
        attempts[task.id] = attempts.get(task.id, 0) + 1
        if task.id == "teacher_assignments" and attempts[task.id] == 1:
            raise RuntimeError("临时连接失败")
        return "ok"

    async def on_event(kind, data):
        if kind == "supervisor.task_retry":
            events.append(data["task_id"])

    report = await SchedulingReadinessSupervisor().run(execute, on_event=on_event)

    assert report.failed_tasks == ()
    assert attempts == {"schedule_setup": 1, "teacher_assignments": 2, "rules": 1}
    assert events == ["teacher_assignments"]


@pytest.mark.asyncio
async def test_readiness_supervisor_aggregates_structured_subtask_results():
    async def execute(task, task_context):
        return {
            "summary": f"{task.id} 已完成",
            "facts": ["学期已配置" if task.id == "schedule_setup" else "教师关系已配置"],
            "missing": ["规则组"],
            "next_steps": ["建立规则组"],
        }

    report = await SchedulingReadinessSupervisor().run(execute)

    assert report.facts == ("学期已配置", "教师关系已配置")
    assert report.missing == ("规则组",)
    assert report.next_steps == ("建立规则组",)
    assert report.results[0].summary == "schedule_setup 已完成"


@pytest.mark.asyncio
async def test_readiness_supervisor_can_run_checks_in_parallel():
    active = 0
    peak = 0

    async def execute(task, task_context):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return f"{task.id} ok"

    report = await SchedulingReadinessSupervisor().run(execute, parallel=True)

    assert len(report.results) == 3
    assert peak >= 2
