import pytest
from pydantic import ValidationError
from app.api.v1.gaokao import UpdateTeachingSubjectHoursIn
from app.services.scheduling.walk_recommendation import recommend_walk_slots


def test_split_hours_total_and_validation():
    scope = dict(grade_id=1, subject_id=1, academic_year='2026-2027', term='2')
    body = UpdateTeachingSubjectHoursIn(**scope, weekday_periods=3, weekend_periods=1)
    assert body.weekly_periods == 4
    for values in ({'weekday_periods': 3}, {'weekday_periods': 0, 'weekend_periods': 0},
                   {'weekday_periods': 3, 'weekend_periods': 1, 'weekly_periods': 5}):
        with pytest.raises(ValidationError):
            UpdateTeachingSubjectHoursIn(**scope, **values)


@pytest.mark.parametrize('weekend_day', [6, 7])
def test_walk_solver_enforces_weekday_and_weekend_separately(weekend_day):
    classes = [dict(id=1, name='化学', teacher_id=1, weekly_periods=2,
                    weekday_periods=1, weekend_periods=1)]
    rooms = [dict(id=1, name='教室', capacity=45)]
    result = recommend_walk_slots(classes, [(1, 1)], rooms, [(1, 1), (1, 2), (weekend_day, 1)])
    assert result['status'] == 'feasible'
    assert sum(p['weekday'] >= 6 for p in result['placements']) == 1
    result = recommend_walk_slots(classes, [(1, 1)], rooms, [(1, 1), (1, 2)])
    assert result['status'] == 'infeasible'


@pytest.mark.asyncio
async def test_split_save_sync_and_same_total_change_invalidates_schedule():
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlmodel import SQLModel
    from app.models.org import Grade, Subject
    from app.models.gaokao import TeachingClass, TeachingClassSchedule, TeachingSubjectHourPlan
    from app.api.v1.gaokao import (update_teaching_subject_hours, get_teaching_subject_hours,
                                  update_teaching_class_hours, UpdateTeachingClassHoursIn)
    engine = create_engine('sqlite://')
    models = [Grade, Subject, TeachingClass, TeachingClassSchedule, TeachingSubjectHourPlan]
    SQLModel.metadata.create_all(engine, tables=[m.__table__ for m in models])
    with Session(engine) as db:
        db.add_all([Grade(id=1, tenant_id=7, name='高一', level=1), Subject(id=1, name='化学')])
        for cid, term in [(1, '2'), (2, '1')]:
            db.add(TeachingClass(id=cid, tenant_id=7, grade_id=1, subject_id=1, name=f'班{cid}',
                                academic_year='2026-2027', term=term, weekly_periods=4,
                                weekday_periods=3, weekend_periods=1))
            db.add(TeachingClassSchedule(tenant_id=7, teaching_class_id=cid, subject_id=1,
                        academic_year='2026-2027', term=term, weekday=6, period=1))
        db.commit()
        class Adapter:
            async def get(self, model, key): return db.get(model, key)
            async def execute(self, stmt): return db.execute(stmt)
            def add(self, obj): db.add(obj)
            async def flush(self): db.flush()
            async def commit(self): db.commit()
        deps = dict(session=Adapter(), user=object(), tenant_id=7)
        scope = dict(grade_id=1, academic_year='2026-2027', term='2')
        result = await update_teaching_subject_hours(UpdateTeachingSubjectHoursIn(
            **scope, subject_id=1, weekday_periods=2, weekend_periods=2), **deps)
        assert result['data']['cleared_schedule_count'] == 1
        assert (db.get(TeachingClass, 1).weekday_periods, db.get(TeachingClass, 1).weekend_periods) == (2, 2)
        assert db.get(TeachingClass, 2).weekday_periods == 3
        assert (await get_teaching_subject_hours(**scope, detailed=True, **deps))['data'] == {
            '1': dict(weekly_periods=4, weekday_periods=2, weekend_periods=2)}
        db.add(TeachingClassSchedule(tenant_id=7, teaching_class_id=1, subject_id=1,
                   academic_year='2026-2027', term='2', weekday=6, period=1))
        db.commit()
        result = await update_teaching_class_hours(1, UpdateTeachingClassHoursIn(
            **scope, weekday_periods=4, weekend_periods=0), **deps)
        assert result['data']['cleared_schedule_count'] == 1
        assert db.get(TeachingClass, 1).weekend_periods == 0
        assert db.execute(select(TeachingSubjectHourPlan)).scalar_one().weekend_periods == 2
    engine.dispose()


def test_joint_calendar_honors_configured_split_over_automatic_phase_quota():
    from app.services.scheduling.walk_regroup_calendar import trial_calendar, audit_draft
    draft = {'classes': [dict(id=1, subject_id=10, phase=('A', 0), size=1,
        weekday_periods=1, weekend_periods=0), dict(id=2, subject_id=20, phase=('B', 0),
        size=1, weekday_periods=0, weekend_periods=1)], 'members': [(1, 1), (2, 1)]}
    args = (draft, [], [100], {100: 0}, {100: 0}, {10: {1}, 20: {2}}, 1, set())
    result = trial_calendar(*args, slots=[(1, 1), (6, 1)], phase_hours=1,
                           saturday_hours={'A': 1, 'B': 0})
    assert result['status'] in ('FEASIBLE', 'OPTIMAL')
    assert result['phase_slots'][str(('A', 0))] == [(1, 1)]
    result['public'] = [dict(id=9, teacher_id=9, class_id=200, room='home', weekday=1, period=1)]
    audit_draft(draft, result, {1: {10, 20}}, {1: 100}, [dict(id=9, weekly_periods=1)],
                [dict(id=1, capacity=45)], set(), slots=[(1, 1), (6, 1)], phase_hours=1)
    draft['classes'][0]['weekday_periods'] = 0
    draft['classes'][0]['weekend_periods'] = 1
    with pytest.raises(AssertionError, match='weekday hours'):
        audit_draft(draft, result, {1: {10, 20}}, {1: 100}, [dict(id=9, weekly_periods=1)],
                    [dict(id=1, capacity=45)], set(), slots=[(1, 1), (6, 1)], phase_hours=1)
