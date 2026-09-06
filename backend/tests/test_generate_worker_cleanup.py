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
