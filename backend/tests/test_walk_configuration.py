import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.api.v1.gaokao import WalkConfigurationIn, get_walk_configuration, save_walk_configuration
from app.models.gaokao import WalkSchedulingPlan, WalkSchedulingSlot, WalkSchedulingRoom
from app.models.org import Grade
from app.models.facility import Room


def test_walk_draft_scope_slots_resources_and_stale_revision():
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in (Grade, WalkSchedulingPlan, WalkSchedulingSlot, WalkSchedulingRoom)])
    with Session(engine) as db:
        db.add(Grade(id=1, tenant_id=7, name='高一', level=1))
        db.commit()
        class Adapter:
            async def execute(self, stmt): return db.execute(stmt)
            async def get(self, model, key): return db.get(model, key)
            def add(self, item): db.add(item)
            def add_all(self, items): db.add_all(items)
            async def flush(self): db.flush()
            async def commit(self): db.commit()
        grid = {'configured': True, 'daily_periods': [9, 9, 9, 9, 9, 9, 0]}
        async def verify():
            scope = dict(grade_id=1, academic_year='2026-2027', term='2')
            deps = dict(session=Adapter(), tenant_id=7)
            with patch('app.api.v1.scheduling._load_grid_config', AsyncMock(return_value=grid)), patch(
                'app.api.v1.gaokao._shared_teaching_rooms', AsyncMock(return_value=[Room(id=5, tenant_id=7, building_id=1, name='共享教室', capacity=50)])):
                empty = (await get_walk_configuration(**scope, **deps))['data']
                assert empty['revision'] == 0 and empty['slots'] == [] and empty['room_ids'] == []
                for slots, rooms in [([(7, 1)], [5]), ([(1, 10)], [5]), ([(1, 1)], [6])]:
                    with pytest.raises(HTTPException) as error:
                        await save_walk_configuration(WalkConfigurationIn(**scope, expected_revision=0, slots=slots, room_ids=rooms), **deps)
                    assert error.value.status_code == 422
                assert not db.execute(select(WalkSchedulingPlan)).scalars().all()
                await save_walk_configuration(WalkConfigurationIn(**scope, expected_revision=0, slots=[(1, 1), (1, 1)], room_ids=[5, 5]), **deps)
                saved = (await get_walk_configuration(**scope, **deps))['data']
                assert saved['revision'] == 1 and saved['slots'] == [[1, 1]] and saved['room_ids'] == [5]
                assert (await get_walk_configuration(**{**scope, 'term': '1'}, **deps))['data']['revision'] == 0
                with pytest.raises(HTTPException) as foreign:
                    await get_walk_configuration(**scope, session=Adapter(), tenant_id=8)
                assert foreign.value.status_code == 404
                with pytest.raises(HTTPException) as stale:
                    await save_walk_configuration(WalkConfigurationIn(**scope, expected_revision=0), **deps)
                assert stale.value.status_code == 409
                await save_walk_configuration(WalkConfigurationIn(**scope, expected_revision=1), **deps)
                actual = (await get_walk_configuration(**scope, **deps))['data']
                assert actual['revision'] == 2 and actual['slots'] == [] and actual['room_ids'] == []
                grid['configured'] = False
                with pytest.raises(HTTPException) as missing_grid:
                    await save_walk_configuration(WalkConfigurationIn(**scope, expected_revision=2), **deps)
                assert missing_grid.value.status_code == 422
        asyncio.run(verify())
    engine.dispose()
