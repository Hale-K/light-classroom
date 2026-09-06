from types import SimpleNamespace
from datetime import datetime, timedelta

import pytest


@pytest.mark.asyncio
async def test_success_is_staged_in_the_schedule_transaction():
    """课表和成功状态必须等待同一个外层事务提交。"""
    from app.services.scheduling.generate_job_store import stage_success

    row = SimpleNamespace(
        tenant_id=7,
        status="running",
        stage="generating",
        message="正在求解",
        percent=70,
        result=None,
        error={"message": "old"},
        updated_at=None,
        heartbeat_at=None,
        finished_at=None,
    )

    class FakeSession:
        async def get(self, model, job_id):
            return row

        def add(self, value):
            assert value is row

    result = {"created": 42, "class_count": 3, "unplaced": []}
    updated = await stage_success(FakeSession(), "job-1", 7, result)

    assert updated is True
    assert row.status == "succeeded"
    assert row.stage == "done"
    assert row.percent == 100
    assert row.result == result
    assert row.error is None


@pytest.mark.asyncio
async def test_heartbeat_refreshes_the_durable_job():
    from app.services.scheduling.generate_job_store import stage_heartbeat

    previous = datetime.utcnow() - timedelta(minutes=10)
    row = SimpleNamespace(tenant_id=7, status="running", heartbeat_at=previous, updated_at=previous)

    class FakeSession:
        async def get(self, model, job_id):
            return row

        def add(self, value):
            assert value is row

    updated = await stage_heartbeat(FakeSession(), "job-1", 7)

    assert updated is True
    assert row.heartbeat_at > previous
    assert row.updated_at == row.heartbeat_at


def test_restart_recovery_selects_queued_and_stale_running_jobs():
    from app.services.scheduling.generate_job_store import should_recover

    now = datetime.utcnow()
    queued = SimpleNamespace(status="queued", created_at=now, heartbeat_at=now)
    fresh_running = SimpleNamespace(status="running", created_at=now, heartbeat_at=now)
    stale_running = SimpleNamespace(
        status="running",
        created_at=now - timedelta(minutes=5),
        heartbeat_at=now - timedelta(minutes=5),
    )

    assert should_recover(queued, now=now) is True
    assert should_recover(fresh_running, now=now) is False
    assert should_recover(stale_running, now=now) is True


def test_running_job_is_not_declared_stale_at_the_old_150_second_boundary(monkeypatch):
    from app.services.scheduling import generate_jobs

    now = 10_000.0
    job = generate_jobs.GenerateJob(
        id="job-1",
        tenant_id=7,
        status="running",
        created_at=now - 200,
        heartbeat_at=now - 151,
    )
    monkeypatch.setattr(generate_jobs.time, "time", lambda: now)

    generate_jobs._reap_stale(job)

    assert job.status == "running"


def test_running_job_is_declared_stale_after_the_new_timeout(monkeypatch):
    from app.services.scheduling import generate_jobs

    now = 10_000.0
    job = generate_jobs.GenerateJob(
        id="job-2",
        tenant_id=7,
        status="running",
        created_at=now - 400,
        heartbeat_at=now - 301,
    )
    released = []
    monkeypatch.setattr(generate_jobs.time, "time", lambda: now)
    monkeypatch.setattr(generate_jobs, "release_generate_slot", released.append)

    generate_jobs._reap_stale(job)

    assert job.status == "error"
    assert released == [7]
