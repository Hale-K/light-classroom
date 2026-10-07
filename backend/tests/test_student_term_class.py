import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.api.v1 import gaokao
from app.models.org import Class, Student, StudentClassMembership


@pytest.mark.asyncio
async def test_current_membership_overrides_legacy_class_and_ignores_other_scopes():
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine, tables=[
        Class.__table__, Student.__table__, StudentClassMembership.__table__])
    with Session(engine) as db:
        db.add_all([
            Class(id=10, tenant_id=7, grade_id=12, name='旧班', academic_year='2026-2027', term='1'),
            Class(id=20, tenant_id=7, grade_id=12, name='新班', academic_year='2026-2027', term='2'),
            Student(id=1, tenant_id=7, name='学生', gender='male', class_id=10),
            StudentClassMembership(tenant_id=7, student_id=1, class_id=10, grade_id=12,
                cohort_label='2026届', academic_year='2026-2027', term='1'),
            StudentClassMembership(tenant_id=7, student_id=1, class_id=20, grade_id=12,
                cohort_label='2026届', academic_year='2026-2027', term='2'),
            StudentClassMembership(tenant_id=8, student_id=1, class_id=10, grade_id=12,
                cohort_label='2026届', academic_year='2026-2027', term='2'),
        ])
        db.commit()
        class AsyncAdapter:
            async def execute(self, query):
                return db.execute(query)
        classes = await gaokao._student_term_classes(AsyncAdapter(), 7, [1], '2026-2027', '2', 12)
        assert classes[1].id == 20


@pytest.mark.asyncio
async def test_missing_current_membership_does_not_fall_back_to_old_class():
    from fastapi import HTTPException
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine, tables=[Class.__table__, StudentClassMembership.__table__])
    with Session(engine) as db:
        class AsyncAdapter:
            async def execute(self, query):
                return db.execute(query)
        with pytest.raises(HTTPException) as error:
            await gaokao._student_term_classes(AsyncAdapter(), 7, [1], '2026-2027', '2', 12)
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_personal_timetable_uses_current_class_for_public_lessons_and_rules(monkeypatch):
    from types import SimpleNamespace
    from app.api.v1 import scheduling
    current = Class(id=20, tenant_id=7, grade_id=12, name='新班', academic_year='2026-2027', term='2')
    class SessionStub:
        async def get(self, model, pk):
            assert model is Student  # Must not read the legacy class.
            return SimpleNamespace(tenant_id=7, class_id=10)
    async def term_classes(*args):
        assert args[2:] == ([1], '2026-2027', '2')
        return {1: current}
    async def public(class_id, year, term, *args):
        assert (class_id, year, term) == (20, '2026-2027', '2')
        return {'data': [{'id': 1, 'class_id': 20, 'class_name': '新班',
            'weekday': 1, 'period': 1, 'week_parity': 'all'}]}
    async def walk(*args):
        return {'data': []}
    async def rules(*args, grade_id):
        assert grade_id == 12
        return None
    monkeypatch.setattr(gaokao, '_student_term_classes', term_classes)
    monkeypatch.setattr(scheduling, 'weekly_schedule', public)
    monkeypatch.setattr(scheduling, '_load_rule_group', rules)
    monkeypatch.setattr(gaokao, 'list_schedules', walk)
    result = await gaokao.student_timetable(1, '2026-2027', '2', SessionStub(), None, 7)
    assert result['data'][0]['class_id'] == 20
