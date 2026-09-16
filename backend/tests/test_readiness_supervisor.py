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
