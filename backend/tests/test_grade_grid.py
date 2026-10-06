import asyncio

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.api.v1.scheduling import SchedulingGridConfigIn
from app.models.org import Grade
from app.models.scheduling_grid import SchedulingGridDay, SchedulingGridPlan, SchedulingGridSlot, SchedulingGridSubject
from app.services.scheduling.cpsat import solve_daytime_cpsat
from app.services.scheduling.evening_cpsat import solve_evening_cpsat
from app.services.scheduling.grid_slots import allowed_slots, item_matches_grid
from app.services.scheduling.grid_storage import load_grade_grid, save_grade_grid


def grid(**changes):
    return SchedulingGridConfigIn(academic_year='2026-2027', term='2',
        daily_periods=[2, 0, 0, 0, 0, 0, 0], **changes).model_dump()


def test_grade_and_term_storage_isolation_and_idempotent_replacement():
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine, tables=[m.__table__ for m in
        (Grade, SchedulingGridPlan, SchedulingGridDay, SchedulingGridSubject, SchedulingGridSlot)])
    with Session(engine) as db:
        class Adapter:
            async def execute(self, stmt): return db.execute(stmt)
            def add(self, row): db.add(row)
            async def flush(self): db.flush()
        async def verify():
            session = Adapter()
            value = grid(slot_overrides=[dict(weekday=1, period=1, week_parity='even', slot_type='disabled')])
            await save_grade_grid(session, 7, 12, '2026-2027', '2', value)
            db.commit()
            await save_grade_grid(session, 7, 13, '2026-2027', '2', grid())
            await save_grade_grid(session, 7, 12, '2026-2027', '1', grid())
            db.commit()
            actual = await load_grade_grid(session, 7, 12, '2026-2027', '2')
            assert actual['slot_overrides'] == value['slot_overrides']
            assert item_matches_grid(actual, 1, 1, 'odd')
            assert not item_matches_grid(actual, 1, 1, 'all')
            assert not (await load_grade_grid(session, 8, 12, '2026-2027', '2'))
            assert not (await load_grade_grid(session, 7, 12, '2027-2028', '2'))
            assert not (await load_grade_grid(session, 7, 13, '2026-2027', '2'))['slot_overrides']
            await save_grade_grid(session, 7, 12, '2026-2027', '2', grid())
            db.commit()
            assert not (await load_grade_grid(session, 7, 12, '2026-2027', '2'))['slot_overrides']
            assert len(db.execute(select(SchedulingGridPlan)).scalars().all()) == 3
            assert len(db.execute(select(SchedulingGridDay)).scalars().all()) == 21
        asyncio.run(verify())
    engine.dispose()


def test_override_validation_rejects_outside_envelope_and_duplicate_leg():
    slot = dict(weekday=1, period=1, week_parity='odd', slot_type='disabled')
    with pytest.raises(ValidationError): grid(slot_overrides=[slot, slot])
    with pytest.raises(ValidationError): grid(slot_overrides=[{**slot, 'period': 3}])
    with pytest.raises(ValidationError): grid(slot_overrides=[{**slot, 'slot_type': 'evening'}])


def test_daytime_solver_obeys_each_parity_and_full_week_intersection():
    value = grid(slot_overrides=[dict(weekday=1, period=1, week_parity='even', slot_type='disabled')])
    allowed = allowed_slots(value, 'daytime')
    assignment = dict(id=1, class_id=1, subject_id=1, teacher_id=1, weekly_periods=1)
    kwargs = dict(days=1, periods_per_day=2, allowed_slots_by_parity=allowed, max_time_seconds=2, polish_seconds=0)
    result = solve_daytime_cpsat([assignment], **kwargs)
    assert result.status in ('OPTIMAL', 'FEASIBLE')
    assert [(item.weekday, item.period) for item in result.items] == [(1, 2)]
    result = solve_daytime_cpsat([{**assignment, 'weekly_periods': 0.5, 'week_parity': 'odd'}],
        **{**kwargs, 'allowed_slots_by_parity': {'odd': {(1, 1)}, 'even': set()}})
    assert result.status in ('OPTIMAL', 'FEASIBLE')
    assert [(item.period, item.week_parity.value) for item in result.items] == [(1, 'odd')]
    result = solve_daytime_cpsat([assignment], **{**kwargs, 'allowed_slots_by_parity': {'odd': {(1, 1)}, 'even': {(1, 2)}}})
    assert result.status == 'INFEASIBLE'


def test_daytime_solver_can_return_first_candidate_without_polishing():
    progress = []
    assignment = dict(id=1, class_id=1, subject_id=1, teacher_id=1, weekly_periods=1)
    result = solve_daytime_cpsat(
        [assignment], days=1, periods_per_day=4, max_time_seconds=5,
        early_subject_ids={1}, polish_seconds=30, stop_after_first_solution=True,
        on_progress=progress.append,
    )
    assert result.status in ('FEASIBLE', 'OPTIMAL')
    assert len(result.items) == 1
    assert any(row.get('solutions') == 1 for row in progress)


def test_daytime_solver_excludes_candidate_rejected_by_evening_stage():
    assignment = dict(id=71, class_id=3, subject_id=9, teacher_id=4, weekly_periods=1)
    kwargs = dict(
        days=1, periods_per_day=4, max_time_seconds=5, early_subject_ids={9},
        polish_seconds=0, stop_after_first_solution=True,
    )
    first = solve_daytime_cpsat([assignment], random_seed=10, **kwargs)
    signature = tuple(
        (item.assignment_id, item.weekday, item.period, item.week_parity.value)
        for item in first.items
    )
    second = solve_daytime_cpsat(
        [assignment], random_seed=10, excluded_schedules=[signature], **kwargs,
    )
    second_signature = tuple(
        (item.assignment_id, item.weekday, item.period, item.week_parity.value)
        for item in second.items
    )
    assert first.status in ('OPTIMAL', 'FEASIBLE')
    assert second.status in ('OPTIMAL', 'FEASIBLE')
    assert second_signature != signature


def test_evening_solver_cannot_place_in_disabled_leg():
    assignment = dict(id=1, class_id=1, subject_id=1, teacher_id=1, evening_periods_odd=1, evening_periods_even=0)
    kwargs = dict(class_ids=[1], first_evening_period=3, evening_daily_periods_odd=[1]*7,
        evening_daily_periods_even=[1]*7, allowed_slots_by_parity={'odd': {(2, 3)}, 'even': set()},
        max_time_seconds=2, polish_seconds=0, r15_enabled=False)
    result = solve_evening_cpsat([assignment], **kwargs)
    assert result.status in ('OPTIMAL', 'FEASIBLE')
    assert [(item.weekday, item.period, item.week_parity.value) for item in result.items] == [(2, 3, 'odd')]
    result = solve_evening_cpsat([assignment], **{**kwargs, 'allowed_slots_by_parity': {'odd': set(), 'even': set()}})
    assert result.status == 'INFEASIBLE'
