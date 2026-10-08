import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.tools import school
from app.ai.harness import HarnessRouter
from app.models.org import Grade, Subject, User
from app.models.gaokao import TeachingClass, TeachingClassStudent, TeachingClassSchedule


@pytest.fixture
def evidence_session():
    engine = create_engine('sqlite://')
    for model in (Grade, Subject, User, TeachingClass, TeachingClassStudent, TeachingClassSchedule):
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            Grade(id=1, tenant_id=1, name='高一', level=10), Grade(id=2, tenant_id=1, name='高二', level=11),
            Subject(id=1, tenant_id=1, name='政治'),
            User(id=1, tenant_id=1, name='甲老师', phone='test1', password_hash='unused'),
            User(id=2, tenant_id=1, name='乙老师', phone='test2', password_hash='unused'),
        ])
        for cid, tenant, grade, year, teacher in (
            (1, 1, 1, '2026-2027', 1), (2, 1, 1, '2026-2027', 1),
            (3, 1, 1, '2026-2027', 2), (4, 1, 2, '2026-2027', 1),
            (5, 2, 1, '2026-2027', 1), (6, 1, 1, '2025-2026', 1),
        ):
            session.add(TeachingClass(id=cid, tenant_id=tenant, grade_id=grade, subject_id=1,
                name=f'政治{cid}班', academic_year=year, term='2', sequence=cid,
                teacher_id=teacher, capacity=45, weekly_periods=5))
        session.add_all([
            TeachingClassStudent(tenant_id=1, teaching_class_id=1, student_id=10),
            TeachingClassStudent(tenant_id=1, teaching_class_id=1, student_id=11),
            TeachingClassStudent(tenant_id=1, teaching_class_id=2, student_id=10),
            TeachingClassStudent(tenant_id=2, teaching_class_id=1, student_id=99),
            TeachingClassSchedule(tenant_id=1, teaching_class_id=1, subject_id=1,
                teacher_id=2, academic_year='2026-2027', term='2', weekday=1, period=1),
            TeachingClassSchedule(tenant_id=2, teaching_class_id=2, subject_id=1,
                teacher_id=1, academic_year='2026-2027', term='2', weekday=1, period=1),
        ])
        session.commit()
        class ReadOnlySession:
            async def execute(self, stmt):
                assert stmt.is_select
                return session.execute(stmt)
        yield ReadOnlySession()
    engine.dispose()


@pytest.mark.asyncio
async def test_walk_evidence_is_scoped_and_distinguishes_hours_from_people(evidence_session):
    result = json.loads(await school.execute_school_tool('lookup_walk_classes',
        '{"grade_id":1,"subject":"政治"}', session=evidence_session, tenant_id=1,
        page_context={'academic_year':'2026-2027', 'term':'2'}))
    assert result['ok'] and result['code'] == 'OK'
    data = result['data']
    assert data['class_count'] == 3
    assert [item['student_count'] for item in data['classes']] == [2, 1, 0]
    assert data['classes'][0]['scheduled_teacher_mismatch_count'] == 1
    assert data['classes'][1]['scheduled_periods'] == 0
    teacher = next(item for item in data['teachers'] if item['teacher_id'] == 1)
    assert teacher['configured_weekly_periods'] == 10
    assert teacher['student_enrollments'] == 3
    assert teacher['unique_students'] == 2
    assert result['scope']['grade_id'] == 1


@pytest.mark.asyncio
async def test_walk_evidence_requires_grade_instead_of_silently_using_all_school(evidence_session):
    result = json.loads(await school.execute_school_tool('lookup_walk_classes',
        '{"academic_year":"2026-2027","term":"2"}',
        session=evidence_session, tenant_id=1))
    assert result['code'] == 'MISSING_SCOPE'
    assert result['status'] != 'success'


def test_diagnostic_tools_are_available_without_write_authority():
    required = {'lookup_walk_classes', 'lookup_generation_log', 'lookup_subject_capacity',
                'lookup_remaining_capacity', 'lookup_slot_role_capacity'}
    for name in ('guide', 'diagnosis'):
        allowed = HarnessRouter().profiles[name].allowed_tools
        assert required <= allowed
        assert 'propose_rules' not in allowed


@pytest.mark.asyncio
async def test_explicit_grade_name_overrides_current_page(evidence_session):
    result = json.loads(await school.execute_school_tool('lookup_walk_classes',
        '{"grade":"高二"}', session=evidence_session, tenant_id=1,
        page_context={'academic_year':'2026-2027', 'term':'2', 'grade_id':1}))
    assert result['scope']['grade_id'] == 2
    assert [item['class_id'] for item in result['data']['classes']] == [4]


@pytest.mark.asyncio
async def test_grade_id_from_other_tenant_is_rejected(evidence_session):
    result = json.loads(await school.execute_school_tool('lookup_walk_classes',
        '{"grade_id":1,"academic_year":"2026-2027","term":"2"}',
        session=evidence_session, tenant_id=2))
    assert result['code'] == 'MISSING_SCOPE'
    assert result['data'] is None
