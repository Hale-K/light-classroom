import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.api.v1.gaokao import (
    UpdateTeachingClassHoursIn, UpdateTeachingSubjectHoursIn,
    get_teaching_subject_hours, update_teaching_class_hours, update_teaching_subject_hours,
)
from app.models.gaokao import TeachingClass, TeachingClassSchedule, TeachingSubjectHourPlan
from app.models.org import Grade, Subject


def test_subject_plan_before_classes_and_scoped_class_override():
    engine = create_engine("sqlite://")
    tables = [Grade, Subject, TeachingSubjectHourPlan, TeachingClass, TeachingClassSchedule]
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    with Session(engine) as db:
        db.add_all([Grade(id=1, tenant_id=7, name="高一", level=1), Subject(id=1, name="化学")])
        db.commit()

        class Adapter:
            async def execute(self, stmt): return db.execute(stmt)
            async def get(self, model, key): return db.get(model, key)
            def add(self, obj): db.add(obj)
            async def flush(self): db.flush()
            async def commit(self): db.commit()

        async def verify():
            scope = dict(grade_id=1, academic_year="2026-2027", term="2")
            deps = dict(session=Adapter(), user=object(), tenant_id=7)
            result = await update_teaching_subject_hours(UpdateTeachingSubjectHoursIn(
                **scope, subject_id=1, weekly_periods=4), **deps)
            assert result["data"]["updated"] == 0  # 无教学班也可以先配置
            assert (await get_teaching_subject_hours(**scope, **deps))["data"] == {"1": 4}
            assert (await get_teaching_subject_hours(**{**scope, "term": "1"}, **deps))["data"] == {}
            plan = db.execute(select(TeachingSubjectHourPlan)).scalar_one()
            for cid, tm, tenant in [(1, "2", 7), (2, "2", 7), (3, "1", 7), (4, "2", 8)]:
                db.add(TeachingClass(id=cid, tenant_id=tenant, grade_id=1, subject_id=1,
                       sequence=cid, name=f"化学{cid}", academic_year="2026-2027", term=tm, weekly_periods=3))
                db.add(TeachingClassSchedule(tenant_id=tenant, teaching_class_id=cid,
                       subject_id=1, academic_year="2026-2027", term=tm, weekday=1, period=1))
            db.commit()
            result = await update_teaching_subject_hours(UpdateTeachingSubjectHoursIn(
                **scope, subject_id=1, weekly_periods=4), **deps)
            assert result["data"]["updated"] == 2
            assert result["data"]["cleared_schedule_count"] == 2
            assert db.get(TeachingClass, 1).hour_plan_id == plan.id
            assert db.get(TeachingClass, 3).weekly_periods == 3
            assert db.get(TeachingClass, 4).weekly_periods == 3
            result = await update_teaching_class_hours(1, UpdateTeachingClassHoursIn(
                **scope, weekly_periods=5), **deps)
            assert db.get(TeachingClass, 1).weekly_periods == 5
            assert db.get(TeachingClass, 1).hours_overridden is True
            assert db.get(TeachingClass, 2).weekly_periods == 4
            assert (await get_teaching_subject_hours(**scope, **deps))["data"] == {"1": 4}
            with pytest.raises(HTTPException) as error:
                await update_teaching_class_hours(3, UpdateTeachingClassHoursIn(
                    **scope, weekly_periods=5), **deps)
            assert error.value.status_code == 404
            assert db.get(TeachingClass, 3).weekly_periods == 3
            assert len(db.execute(select(TeachingClassSchedule)).scalars().all()) == 2
        asyncio.run(verify())
    engine.dispose()
