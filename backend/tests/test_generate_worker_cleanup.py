import pytest


@pytest.mark.asyncio
async def test_two_sequential_jobs_stop_heartbeat_and_release_school_slot(monkeypatch):
    from app.db import session as db_session
    from app.services.scheduling import generate_jobs
    from app.workers.scheduling.generate import _run_spawned_job

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class FakeJob:
        def __init__(self):
            self.events = []

        def emit(self, event_type, **payload):
            self.events.append((event_type, payload))

    jobs = {"first": FakeJob(), "second": FakeJob()}
    released = []
    monkeypatch.setattr(db_session, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(generate_jobs, "get_job", lambda job_id: jobs[job_id])
    monkeypatch.setattr(generate_jobs, "touch_heartbeat", lambda job_id: None)
    monkeypatch.setattr(generate_jobs, "release_generate_slot", released.append)

    async def execute(session, progress):
        await progress("solving", "正在求解", percent=50)
        return {"items": []}

    await _run_spawned_job("first", 7, execute)
    await _run_spawned_job("second", 7, execute)

    assert released == [7, 7]
    assert jobs["first"].events[-1][0] == "done"
    assert jobs["second"].events[-1][0] == "done"


@pytest.mark.asyncio
async def test_redelivered_completed_job_reuses_durable_result(monkeypatch):
    """MQ 在数据库提交后重投时，必须复用结果，不能再次覆盖课表。"""
    from app.db import session as db_session
    from app.services.scheduling import generate_jobs
    from app.services.scheduling import generate_job_store
    from app.workers.scheduling.generate import run_generate_payload

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class FakeJob:
        def __init__(self):
            self.events = []

        def emit(self, event_type, **payload):
            self.events.append((event_type, payload))

    durable_result = {"created": 42, "class_count": 3, "unplaced": []}
    job = FakeJob()
    released = []
    executed = False

    async def claim(*args, **kwargs):
        return generate_job_store.JobClaim("succeeded", durable_result)

    async def must_not_execute(*args, **kwargs):
        nonlocal executed
        executed = True
        raise AssertionError("已完成任务被重复执行")

    monkeypatch.setattr(db_session, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(generate_jobs, "get_or_create_job", lambda *args: job)
    monkeypatch.setattr(generate_jobs, "touch_heartbeat", lambda job_id: None)
    monkeypatch.setattr(generate_jobs, "release_generate_slot", released.append)
    monkeypatch.setattr(generate_job_store, "claim_job", claim)
    monkeypatch.setattr(
        "app.api.v1.scheduling._execute_schedule_generation",
        must_not_execute,
    )

    await run_generate_payload("already-done", 7, {}, allow_reclaim=True)

    assert executed is False
    assert job.events[-1] == (
        "done",
        {"stage": "done", "message": "生成完成（已恢复）", "percent": 100, "result": durable_result},
    )
    assert released == [7]
