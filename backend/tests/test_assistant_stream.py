import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.api.v1 import assistant as assistant_api


class _ScalarResult:
    def __init__(self, run):
        self._run = run

    def scalars(self):
        return self

    def first(self):
        return self._run


class _Session:
    def __init__(self, runs):
        self._runs = iter(runs)
        self.rollbacks = 0

    async def execute(self, _statement):
        return _ScalarResult(next(self._runs))

    async def rollback(self):
        self.rollbacks += 1


def _run(status: str):
    now = datetime.now()
    return SimpleNamespace(
        id="run-id",
        status=status,
        phase="waiting" if status == "queued" else "done",
        message="排队中" if status == "queued" else "完成",
        events=[],
        result=None if status == "queued" else {"text": "完成"},
        created_at=now,
        updated_at=now,
        phase_started_at=now,
    )


@pytest.mark.asyncio
async def test_stream_keeps_queued_run_open_and_releases_read_transaction(monkeypatch):
    session = _Session([_run("queued"), _run("done")])
    user = SimpleNamespace(id=7, tenant_id=3)

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(assistant_api.asyncio, "sleep", no_wait)
    response = await assistant_api.stream_assistant_run(
        "run-id", session=session, user=user, tenant_id=3,
    )

    statuses = []
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        if "event: run.status" in text:
            statuses.append(json.loads(text.split("data: ", 1)[1]).get("status"))

    assert statuses == ["queued", "done"]
    assert session.rollbacks == 2
