from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.models import AiRun
from app.ai.runs import create_run, get_run


@pytest.mark.asyncio
async def test_durable_run_identity_scope_cancel_and_stale_heartbeat():
    engine = create_engine('sqlite://')
    AiRun.__table__.create(engine)
    with Session(engine, expire_on_commit=False) as sync:
        class Adapter:
            add = sync.add
            async def get(self, model, key):
                return sync.get(model, key)
            async def execute(self, stmt):
                return sync.execute(stmt)
            async def commit(self):
                sync.commit()
            async def rollback(self):
                sync.rollback()
        session = Adapter()
        payload = {'messages': [{'role': 'user', 'content': '检查排课'}]}
        first, created = await create_run(session, 'a' * 32, 1, 2, payload)
        assert created and first['status'] == 'running'
        again, created = await create_run(session, first['id'], 1, 2, payload)
        assert not created and again['id'] == first['id']
        with pytest.raises(HTTPException) as conflict:
            await create_run(session, first['id'], 1, 2, {'messages': []})
        assert conflict.value.status_code == 409
        for tenant, user in [(2, 2), (1, 3)]:
            with pytest.raises(HTTPException) as denied:
                await get_run(session, first['id'], tenant, user, cancel=True)
            assert denied.value.status_code == 404
        cancelled = await get_run(session, first['id'], 1, 2, cancel=True)
        assert cancelled['status'] == 'cancelled'
        sync.expire_all()
        assert (await get_run(session, first['id'], 1, 2))['status'] == 'cancelled'
        stale, _ = await create_run(session, 'b' * 32, 1, 2, payload)
        row = sync.get(AiRun, stale['id'])
        row.updated_at = datetime.utcnow() - timedelta(seconds=31)
        sync.commit()
        assert (await get_run(session, stale['id'], 1, 2))['status'] == 'interrupted'
    engine.dispose()


def test_readiness_reports_missing_assignment_and_over_capacity():
    from types import SimpleNamespace as Row
    from app.ai.tools.readiness import readiness_lines
    class Plan(Row):
        def model_dump(self):
            return vars(self)
    plan = Plan(class_id=1, subject_id=2, week_parity='all', weekday_periods=40, saturday_periods=0, evening_periods=0)
    classes = [Row(id=1, name='高一1班')]
    subjects = [Row(id=2, name='数学', course_type='subject')]
    grid = {'configured': True, 'daily_periods': [7] * 5 + [0, 0]}
    missing = '\n'.join(readiness_lines(classes, [plan], [], subjects, grid))
    assert '高一1班·数学' in missing
    assert '先到任教关系补齐' in missing
    full = '\n'.join(readiness_lines(classes, [plan], [Row(class_id=1, subject_id=2, teacher_id=3)], subjects, grid))
    assert '40/35' in full
    assert '解决超容量' in full
