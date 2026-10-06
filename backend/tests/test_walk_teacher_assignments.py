import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

from app.api.v1.gaokao import WalkTeachersIn, assign_walk_teachers, walk_teacher_options
from app.models.gaokao import TeachingClass, TeachingClassSchedule
from app.models.org import Grade, Subject, User, OrganizationUnit, StaffAppointment, TeachingAssignment


def test_walk_teacher_batch_scope_validation_idempotency_and_schedule_guard():
    engine = create_engine('sqlite://')
    models = [Grade, Subject, User, OrganizationUnit, StaffAppointment, TeachingAssignment, TeachingClass, TeachingClassSchedule]
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in models])
    with Session(engine) as db:
        db.add_all([Grade(id=1, tenant_id=7, name='高一', level=1), Subject(id=1, tenant_id=7, name='化学'),
            User(id=1, tenant_id=7, name='化学教师', phone='1', password_hash='test'),
            User(id=2, tenant_id=8, name='其他学校教师', phone='2', password_hash='test'),
            User(id=3, tenant_id=7, name='旧学年教师', phone='3', password_hash='test'),
            OrganizationUnit(id=1, tenant_id=7, name='化学组', unit_type='subject_group', subject_id=1),
            StaffAppointment(id=1, tenant_id=7, organization_unit_id=1, staff_id=1, position_code='member'),
            StaffAppointment(id=2, tenant_id=7, organization_unit_id=1, staff_id=3, position_code='member', academic_year='2025-2026'),
            TeachingAssignment(id=1, tenant_id=7, teacher_id=1, subject_id=1, class_id=1, academic_year='2026-2027', term='2', weekly_periods=6),
            TeachingAssignment(id=2, tenant_id=7, teacher_id=1, subject_id=1, class_id=2, academic_year='2026-2027', term='1', weekly_periods=20)])
        for cid, tenant, term in [(1, 7, '2'), (2, 7, '2'), (3, 7, '1'), (4, 8, '2')]:
            db.add(TeachingClass(id=cid, tenant_id=tenant, grade_id=1, subject_id=1, sequence=cid,
                name=f'化学{cid}', academic_year='2026-2027', term=term, weekly_periods=4))
        db.commit()

        class Adapter:
            async def execute(self, stmt): return db.execute(stmt)
            def add(self, obj): db.add(obj)
            async def commit(self): db.commit()

        async def verify():
            deps = dict(session=Adapter(), tenant_id=7)
            scope = dict(grade_id=1, academic_year='2026-2027', term='2')
            def body(ids, teacher=1, expected=None):
                return WalkTeachersIn(**scope, assignments=[dict(teaching_class_id=cid, teacher_id=teacher, expected_teacher_id=expected) for cid in ids])
            for ids, teacher, status in [([1, 3], 1, 404), ([1, 4], 1, 404), ([1, 2], 2, 422), ([1], 3, 422), ([1, 1], 1, 422)]:
                with pytest.raises(HTTPException) as error:
                    await assign_walk_teachers(body(ids, teacher), **deps)
                assert error.value.status_code == status
                assert db.get(TeachingClass, 1).teacher_id is None
            result = await assign_walk_teachers(body([1, 2]), **deps)
            assert result['data']['updated'] == 2
            assert (await assign_walk_teachers(body([1, 2]), **deps))['data']['updated'] == 0
            options = (await walk_teacher_options(academic_year='2026-2027', term='2', **deps))['data']
            first = next(item for item in options if item['id'] == 1)
            assert first['administrative_periods'] == 6 and first['walk_periods'] == 8 and first['total_periods'] == 14
            assert next(item for item in options if item['id'] == 3)['subject_ids'] == []
            with pytest.raises(HTTPException) as stale:
                await assign_walk_teachers(body([1], teacher=None), **deps)
            assert stale.value.status_code == 409
            db.add(TeachingClassSchedule(tenant_id=7, teaching_class_id=2, subject_id=1,
                academic_year='2026-2027', term='2', weekday=1, period=1))
            db.commit()
            with pytest.raises(HTTPException) as scheduled:
                await assign_walk_teachers(body([1, 2], teacher=None, expected=1), **deps)
            assert scheduled.value.status_code == 409
            assert db.get(TeachingClass, 1).teacher_id == 1
            assert (await assign_walk_teachers(body([1], teacher=None, expected=1), **deps))['data']['updated'] == 1
            assert db.get(TeachingClass, 2).teacher_id == 1
            assert db.get(TeachingClass, 3).teacher_id is None
        asyncio.run(verify())
    engine.dispose()
