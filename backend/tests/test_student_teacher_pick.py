import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.gaokao import TeacherPickIn, set_teacher_pick
from app.api.v1.student_auth import StudentChoiceIn, choice_options, save_choice
from app.models.gaokao import GaokaoScheme
from app.models.org import Student


def session_for(scheme):
    session = MagicMock()
    session.get = AsyncMock(return_value=scheme)
    result = MagicMock()
    result.scalar_one_or_none.return_value = scheme
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def test_teacher_pick_toggle_preserves_configuration_and_checks_tenant():
    scheme = GaokaoScheme(id=1, tenant_id=7, name='方案', entry_year=2026,
                          strategy_config={'elective_count': 3})
    session = session_for(scheme)
    async def verify():
        for enabled in (True, False):
            await set_teacher_pick(1, TeacherPickIn(enabled=enabled), session=session, tenant_id=7)
            assert scheme.strategy_config == {'elective_count': 3, 'allow_teacher_pick': enabled}
        with pytest.raises(HTTPException) as error:
            await set_teacher_pick(1, TeacherPickIn(enabled=True), session=session, tenant_id=8)
        assert error.value.status_code == 404
    asyncio.run(verify())


@pytest.mark.parametrize('enabled,preferences,error_code', [
    (False, {'1': 9}, 403), (False, {}, None),
    (True, {'1': 9}, 422), (True, {'2': 9}, 422), (True, {'1': 10}, 422),
])
def test_student_teacher_pick_enforces_switch_and_subject_teacher(enabled, preferences, error_code):
    scheme = GaokaoScheme(id=1, tenant_id=7, name='方案', entry_year=2026,
                          strategy_config={'allow_teacher_pick': enabled})
    session = session_for(scheme)
    student = Student(id=3, tenant_id=7, name='学生', grade_id=4)
    session.execute.return_value.scalar_one_or_none.side_effect = [scheme, None]
    body = StudentChoiceIn(scheme_id=1, academic_year='2026-2027', teacher_preferences=preferences)
    async def verify():
        with patch('app.api.v1.student_auth._selected_subject_ids', return_value=(1,)), patch(
            'app.api.v1.student_auth._grade_subject_teachers', AsyncMock(return_value={'1': [{'id': 9, 'name': '老师'}]})):
            if error_code:
                with pytest.raises(HTTPException) as error:
                    await save_choice(body, student=student, session=session)
                assert error.value.status_code == error_code
                session.commit.assert_not_awaited()
            else:
                result = await save_choice(body, student=student, session=session)
                assert result['data']['teacher_preferences'] == preferences
    asyncio.run(verify())


def test_student_options_without_scheme_stays_course_only():
    session = session_for(None)
    student = Student(id=3, tenant_id=7, name='学生')
    async def verify():
        with patch('app.api.v1.student_auth._ensure_default_scheme', AsyncMock(return_value=None)):
            result = (await choice_options('2026-2027', student=student, session=session))['data']
            assert result['scheme'] is None
            assert result['allow_teacher_pick'] is False
            assert result['teachers_by_subject'] == {}
    asyncio.run(verify())


def test_class_quota_submit_draft_switch_and_capacity():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlmodel import SQLModel
    from app.api.v1.gaokao import TeachingClassCapacityIn, set_teaching_class_capacity
    from app.models.gaokao import StudentSubjectChoice, TeachingClass, TeachingClassStudent
    from app.models.org import Class, Subject, TeachingAssignment, User

    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in (
        GaokaoScheme, StudentSubjectChoice, TeachingClass, TeachingClassStudent, User, Class, Subject, TeachingAssignment,
    )])
    with Session(engine) as db:
        db.add(GaokaoScheme(id=1, tenant_id=7, name='方案', entry_year=2026,
                           strategy_config={'allow_teacher_pick': True}))
        db.add(User(id=9, tenant_id=7, name='老师', phone='123', password_hash='hash'))
        for class_id, capacity in [(11, 1), (12, 2)]:
            db.add(TeachingClass(id=class_id, tenant_id=7, grade_id=4, subject_id=1,
                                 name=f'教学班{class_id}', academic_year='2026-2027',
                                 term='1', teacher_id=9, capacity=capacity, sequence=class_id))
        db.commit()

        class Adapter:
            async def execute(self, statement): return db.execute(statement)
            async def get(self, model, key): return db.get(model, key)
            def add(self, item): db.add(item)
            async def commit(self): db.commit()
            async def refresh(self, item): db.refresh(item)

        session = Adapter()
        async def submit(student_id, class_id, status='confirmed', subject_id='1'):
            return await save_choice(StudentChoiceIn(scheme_id=1, academic_year='2026-2027',
                teaching_class_preferences={subject_id: class_id}, status=status),
                student=Student(id=student_id, tenant_id=7, name='学生', grade_id=4), session=session)

        async def verify():
            with patch('app.api.v1.student_auth._selected_subject_ids', return_value=(1,)):
                await submit(3, 11, 'draft')
                await submit(4, 11)
                with pytest.raises(HTTPException) as full:
                    await submit(3, 11)
                assert full.value.status_code == 409
                await submit(4, 11)  # 重复提交本人不重复占用
                await submit(4, 12)  # 改选释放旧班名额
                await submit(3, 11)
                for class_id, subject_id in [(99, '1'), (12, '2')]:
                    with pytest.raises(HTTPException) as invalid:
                        await submit(5, class_id, subject_id=subject_id)
                    assert invalid.value.status_code == 422
                result = (await choice_options('2026-2027', '1',
                    student=Student(id=3, tenant_id=7, name='学生', grade_id=4), session=session))['data']
                first = next(c for c in result['teaching_classes'] if c['id'] == 11)
                assert first['is_full'] and first['selected_count'] == 1 and first['selected_by_me']
                await set_teaching_class_capacity(11, TeachingClassCapacityIn(capacity=2), session=session, tenant_id=7)
                await submit(5, 11)
                with pytest.raises(HTTPException) as too_small:
                    await set_teaching_class_capacity(11, TeachingClassCapacityIn(capacity=1), session=session, tenant_id=7)
                assert too_small.value.status_code == 409
                with pytest.raises(HTTPException) as foreign:
                    await set_teaching_class_capacity(11, TeachingClassCapacityIn(capacity=3), session=session, tenant_id=8)
                assert foreign.value.status_code == 404
        asyncio.run(verify())
    engine.dispose()
