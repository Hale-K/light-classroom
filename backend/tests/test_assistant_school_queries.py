import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.tools import school
from app.ai.harness.router import GUIDE_HARNESS, PLAN_HARNESS, DIAGNOSIS_HARNESS
from app.ai.gateway.tool import ToolGateway
from app.models.org import (
    Grade, Class, Student, StudentClassMembership, StudentGradeMembership,
    Subject, User, Schedule, TeachingAssignment, CourseHourPlan, TenantConfig, Tenant, OrganizationUnit,
)
from app.models.gaokao import (
    StudentSubjectChoice, TeachingClass, TeachingClassStudent, TeachingClassSchedule,
)
from app.models.rbac import Role, UserRole


NEW_TOOLS = {
    'lookup_student_choices', 'lookup_teaching_assignments',
    'lookup_timetable', 'lookup_schedule_conflicts',
}


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    models = (Grade, Class, Student, StudentClassMembership, StudentGradeMembership,
              Subject, User, Schedule, TeachingAssignment, CourseHourPlan,
              StudentSubjectChoice, TeachingClass, TeachingClassStudent, TeachingClassSchedule,
              Role, UserRole, TenantConfig, Tenant, OrganizationUnit)
    for model in models:
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            Tenant(id=1, code='school', name='测试学校', gaokao_mode='3+1+2'),
            TenantConfig(tenant_id=1, config_key='timetable_mode', config_value={'mode': 'walk_class'}),
            TenantConfig(tenant_id=1, config_key='academic_years', config_value={
                'current_entry_year': 2026, 'current_academic_year': '2026-2027', 'current_term': '2'}),
            Grade(id=1, tenant_id=1, name='高一', level=1),
            Grade(id=2, tenant_id=1, name='高二', level=2),
            Grade(id=3, tenant_id=2, name='另一校高一', level=1),
            Subject(id=1, tenant_id=1, name='数学'),
            Subject(id=2, tenant_id=None, name='物理'),
            User(id=1, tenant_id=1, name='甲老师', phone='1', password_hash='unused'),
            Class(id=10, tenant_id=1, grade_id=1, name='高一1班', academic_year='2026-2027', term='2'),
            Class(id=20, tenant_id=1, grade_id=2, name='高二1班', academic_year='2026-2027', term='2'),
            Class(id=30, tenant_id=2, grade_id=3, name='外校班', academic_year='2026-2027', term='2'),
            Class(id=11, tenant_id=1, grade_id=1, name='旧班', academic_year='2026-2027', term='1'),
            Student(id=1, tenant_id=1, name='学生甲', gender='male', class_id=11),
            Student(id=2, tenant_id=1, name='学生乙', gender='female', class_id=11),
            Student(id=3, tenant_id=2, name='外校学生', gender='male', class_id=30),
            Student(id=4, tenant_id=1, name='未分班学生', gender='male', grade_id=1),
            StudentClassMembership(tenant_id=1, student_id=1, class_id=10, grade_id=1,
                cohort_label='2026', academic_year='2026-2027', term='2'),
            StudentClassMembership(tenant_id=1, student_id=2, class_id=10, grade_id=1,
                cohort_label='2026', academic_year='2026-2027', term='2'),
            StudentGradeMembership(tenant_id=1, student_id=4, grade_id=1, grade_unit_id=1,
                academic_year='2026-2027'),
            StudentSubjectChoice(tenant_id=1, student_id=1, scheme_id=1,
                academic_year='2026-2027', effective_term='2', selected_subject_ids=[2]),
            StudentSubjectChoice(tenant_id=1, student_id=2, scheme_id=1,
                academic_year='2026-2027', effective_term='1', selected_subject_ids=[1]),
            StudentSubjectChoice(tenant_id=2, student_id=3, scheme_id=1,
                academic_year='2026-2027', effective_term='2', selected_subject_ids=[2]),
            TeachingAssignment(tenant_id=1, class_id=10, subject_id=1, teacher_id=1,
                academic_year='2026-2027', term='2', weekly_periods=9),
            CourseHourPlan(tenant_id=1, class_id=10, subject_id=1,
                academic_year='2026-2027', term='2', weekly_periods=5, week_parity='odd'),
            CourseHourPlan(tenant_id=1, class_id=10, subject_id=1,
                academic_year='2026-2027', term='2', weekly_periods=4, week_parity='even'),
            TeachingClass(id=100, tenant_id=1, grade_id=1, subject_id=2, name='物理1班',
                academic_year='2026-2027', term='2', teacher_id=1, weekly_periods=3, capacity=45),
            TeachingClassStudent(tenant_id=1, teaching_class_id=100, student_id=1),
            Schedule(id=1, tenant_id=1, class_id=10, teacher_id=1, subject_id=1,
                academic_year='2026-2027', term='2', weekday=1, period=1, room='A', week_parity='odd'),
            Schedule(id=2, tenant_id=1, class_id=10, teacher_id=None, subject_id=1,
                academic_year='2026-2027', term='2', weekday=1, period=2, room='A', week_parity='odd'),
            Schedule(id=3, tenant_id=1, class_id=10, teacher_id=None, subject_id=1,
                academic_year='2026-2027', term='2', weekday=1, period=2, room='A', week_parity='even'),
            Schedule(id=4, tenant_id=1, class_id=20, teacher_id=1, subject_id=1,
                academic_year='2026-2027', term='2', weekday=1, period=1, room='B'),
            Schedule(id=5, tenant_id=2, class_id=30, teacher_id=1, subject_id=1,
                academic_year='2026-2027', term='2', weekday=1, period=1, room='A'),
            Schedule(id=6, tenant_id=1, class_id=10, teacher_id=1, subject_id=1,
                academic_year='2026-2027', term='1', weekday=1, period=1, room='A'),
            TeachingClassSchedule(id=1, tenant_id=1, teaching_class_id=100,
                teacher_id=1, subject_id=2, academic_year='2026-2027', term='2',
                weekday=1, period=1, room='A'),
        ])
        session.commit()

        class ReadOnly:
            async def execute(self, statement):
                assert statement.is_select, '助手工具只能查询'
                return session.execute(statement)

        yield ReadOnly(), session
    engine.dispose()


async def query(db, name, **args):
    return json.loads(await school.execute_school_tool(name, json.dumps(args),
        session=db[0], tenant_id=1,
        page_context={'academic_year': '2026-2027', 'term': '2', 'grade_id': 1}))


def test_new_tools_are_registered_and_authorized_for_read_only_modes():
    assert NEW_TOOLS <= {item['function']['name'] for item in school.SCHOOL_TOOLS}
    for harness in (GUIDE_HARNESS, PLAN_HARNESS, DIAGNOSIS_HARNESS):
        assert NEW_TOOLS <= harness.allowed_tools
        assert 'propose_rules' not in harness.allowed_tools


@pytest.mark.asyncio
async def test_choices_use_term_membership_and_include_unassigned_students(db):
    result = await query(db, 'lookup_student_choices')
    assert result['ok']
    data = result['data']
    assert data['total'] == 3
    students = {item['student_id']: item for item in data['items']}
    assert students[1]['administrative_class_ids'] == [10]
    assert students[1]['selected_subject_ids'] == [2]
    assert students[1]['teaching_class_ids'] == [100]
    assert students[2]['choice_status'] == 'missing'
    assert students[4]['administrative_class_ids'] == []
    assert data['missing_choice_count'] == 2
    assert data['subjects'][0]['selected_students'] == 1


@pytest.mark.asyncio
async def test_timetable_merges_admin_and_walk_with_pagination_and_parity(db):
    result = await query(db, 'lookup_timetable', student_id=1, limit=2)
    assert result['ok']
    assert result['data']['total'] == 4
    assert result['data']['has_more'] is True
    next_page = await query(db, 'lookup_timetable', student_id=1, offset=2, limit=2)
    items = result['data']['items'] + next_page['data']['items']
    assert {item['kind'] for item in items} == {'administrative', 'walk'}
    assert {item['week_parity'] for item in items} == {'all', 'odd', 'even'}
    assert all(item['class_id'] in (10, 100) for item in items)
    assert (await query(db, 'lookup_timetable', student_id=4))['code'] == 'EMPTY_RESULT'


@pytest.mark.asyncio
async def test_assignments_preserve_configured_hours_and_separate_week_parity(db):
    result = await query(db, 'lookup_teaching_assignments', teacher_id=1)
    assert result['ok']
    assert result['data']['total'] == 2
    admin = next(item for item in result['data']['items'] if item['kind'] == 'administrative')
    assert admin['assignment_weekly_periods'] == 9
    assert {p['week_parity']: p['weekly_periods'] for p in admin['hour_plans']} == {'odd': 5, 'even': 4}
    assert admin['scheduled_periods_by_week'] == {'odd': 2, 'even': 1}
    assert admin['scheduled_teacher_mismatch_count'] == 2
    assert result['data']['teachers'][0]['scheduled_periods_by_week'] == {'odd': 2, 'even': 1}


@pytest.mark.asyncio
async def test_conflicts_cross_admin_walk_and_grade_without_false_parity_conflicts(db):
    result = await query(db, 'lookup_schedule_conflicts')
    assert result['ok']
    data = result['data']
    assert {'teacher', 'student', 'room'} <= {item['resource_type'] for item in data['items']}
    assert any({s['class_id'] for s in item['lessons']} == {10, 20, 100}
               for item in data['items'] if item['resource_type'] == 'teacher')
    assert not any(item['period'] == 2 for item in data['items'])
    assert data['coverage']['includes_cross_grade_resources'] is True
    assert data['coverage']['full_rule_validation'] is False


@pytest.mark.asyncio
async def test_new_tools_reject_foreign_scope_bad_parameters_and_missing_grade(db):
    for name in NEW_TOOLS:
        assert (await query(db, name, grade_id=3))['code'] == 'MISSING_SCOPE'
        assert (await query(db, name, term='3'))['code'] == 'INVALID_ARGUMENT'
        assert (await query(db, name, limit=0))['code'] == 'INVALID_ARGUMENT'
        assert (await query(db, name, teacher_id='garbage'))['code'] == 'INVALID_ARGUMENT'
        missing = json.loads(await school.execute_school_tool(name,
            '{"academic_year":"2026-2027","term":"2"}', session=db[0], tenant_id=1))
        assert missing['code'] == 'MISSING_SCOPE'
    assert (await query(db, 'lookup_timetable', class_id=30))['code'] == 'MISSING_SCOPE'
    assert (await query(db, 'lookup_student_choices', student_id=3))['data']['total'] == 0


@pytest.mark.asyncio
async def test_explicit_grade_name_does_not_use_page_grade_or_class(db):
    result = json.loads(await school.execute_school_tool('lookup_timetable', '{"grade":"高二"}',
        session=db[0], tenant_id=1, page_context={'grade_id': 1, 'class_id': 10,
            'academic_year': '2026-2027', 'term': '2'}))
    assert result['ok']
    assert result['scope']['grade_id'] == 2
    assert [item['class_id'] for item in result['data']['items']] == [20]


@pytest.mark.asyncio
async def test_choices_teacher_filter_includes_administrative_students(db):
    result = await query(db, 'lookup_student_choices', teacher_id=1)
    assert {item['student_id'] for item in result['data']['items']} == {1, 2}


@pytest.mark.asyncio
async def test_conflict_filters_keep_competing_lessons_and_paginate_full_counts(db):
    result = await query(db, 'lookup_schedule_conflicts', subject='数学', teacher_id=1, limit=1)
    assert result['data']['has_more']
    assert result['data']['total'] > len(result['data']['items'])
    assert sum(result['data']['counts_by_resource'].values()) == result['data']['total']
    assert any(s['subject'] == '物理' for s in result['data']['items'][0]['lessons'])
    timetable = await query(db, 'lookup_timetable', weekday=1, period=2)
    assert timetable['data']['total'] == 2


@pytest.mark.asyncio
async def test_malformed_arguments_cannot_fall_back_to_page_scope(db):
    for args in ('{{{', '[]', 'null', '{"unexpected":true}'):
        result = json.loads(await school.execute_school_tool('lookup_timetable', args,
            session=db[0], tenant_id=1, page_context={'grade_id': 1,
                'academic_year': '2026-2027', 'term': '2'}))
        assert result['code'] == 'INVALID_ARGUMENT'
        assert result['data'] is None


@pytest.mark.asyncio
async def test_choice_subject_summary_distinguishes_drafts(db):
    db[1].add(StudentSubjectChoice(tenant_id=1, student_id=2, scheme_id=1,
        academic_year='2026-2027', effective_term='2', selected_subject_ids=[2], status='draft'))
    db[1].commit()
    result = await query(db, 'lookup_student_choices', subject='物理')
    summary = result['data']['subjects'][0]
    assert summary['selected_students'] == 2
    assert summary['choice_status_counts'] == {'confirmed': 1, 'draft': 1}


@pytest.mark.asyncio
async def test_gateway_rejects_school_queries_for_regular_teacher_and_missing_identity(db):
    for uid in (None, 1):
        scope = ToolGateway().open_scope(session=db[0], tenant_id=1, user_id=uid,
            can_manage_rules=True, page_context={'grade_id': 1,
                'academic_year': '2026-2027', 'term': '2'})
        result = json.loads(await scope.execute('lookup_student_choices', '{}'))
        assert result['code'] == 'FORBIDDEN'
        assert result['data'] is None


@pytest.mark.asyncio
async def test_gateway_allows_management_queries_without_write_permission(db):
    teacher = db[1].get(User, 1)
    teacher.role = 'director'
    db[1].commit()
    scope = ToolGateway().open_scope(session=db[0], tenant_id=1, user_id=1,
        can_manage_rules=False, page_context={'grade_id': 1,
            'academic_year': '2026-2027', 'term': '2'})
    result = json.loads(await scope.execute('lookup_student_choices', '{}'))
    assert result['ok']


@pytest.mark.asyncio
async def test_human_names_can_select_teacher_student_and_class(db):
    teacher = await query(db, 'lookup_timetable', teacher='甲老师')
    assert teacher['scope']['teacher_id'] == 1
    assert teacher['data']['total'] == 2
    student = await query(db, 'lookup_timetable', student='学生甲')
    assert student['scope']['student_id'] == 1
    assert student['data']['total'] == 4
    other_class = await query(db, 'lookup_timetable', class_name='高二1班')
    assert other_class['scope']['grade_id'] == 2
    assert other_class['data']['total'] == 1
    unknown = await query(db, 'lookup_timetable', teacher='不存在')
    assert unknown['code'] == 'MISSING_SCOPE'


@pytest.mark.asyncio
async def test_administrative_mode_ignores_saved_walk_records(db):
    config = db[1].query(TenantConfig).filter(TenantConfig.config_key == 'timetable_mode').one()
    config.config_value = {'mode': 'administrative'}
    db[1].commit()
    timetable = await query(db, 'lookup_timetable', student_id=1)
    assert timetable['scope']['timetable_mode'] == 'administrative'
    assert timetable['data']['total'] == 3
    assert {s['kind'] for s in timetable['data']['items']} == {'administrative'}
    assignments = await query(db, 'lookup_teaching_assignments')
    assert assignments['data']['total'] == 1
    explicit_walk = await query(db, 'lookup_timetable', lesson_type='walk')
    assert explicit_walk['code'] == 'MODE_MISMATCH'


@pytest.mark.asyncio
async def test_walk_mode_distinguishes_display_type_from_conflict_coverage(db):
    admin = await query(db, 'lookup_timetable', lesson_type='administrative')
    walk = await query(db, 'lookup_timetable', lesson_type='walk')
    assert admin['data']['total'] == 3
    assert walk['data']['total'] == 1
    conflicts = await query(db, 'lookup_schedule_conflicts', lesson_type='administrative')
    assert any(s['kind'] == 'walk' for c in conflicts['data']['items'] for s in c['lessons'])
    assert conflicts['scope']['timetable_mode'] == 'walk_class'
    assert conflicts['scope']['lesson_type'] == 'administrative'


@pytest.mark.asyncio
async def test_school_context_separates_gaokao_and_timetable_modes(db):
    context = json.loads(await school.execute_school_tool('lookup_school_context', '{}',
        session=db[0], tenant_id=1))
    assert context['data']['timetable_mode'] == 'walk_class'
    assert context['data']['gaokao_mode'] == '3+1+2'
    assert context['data']['available_lesson_types'] == ['administrative', 'walk', 'combined']
    assert context['data']['academic_year'] == '2026-2027'
    assert context['data']['term'] == '2'


@pytest.mark.asyncio
async def test_model_gets_verified_environment_before_answering(db):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.ai.agent.agent_loop import run_agent_loop
    from app.ai.model.chat import ChatOutcome

    scope = ToolGateway().open_scope(session=db[0], tenant_id=1, user_id=1,
        can_manage_rules=False, page_context={'timetable_mode': 'administrative'})
    caller = AsyncMock(return_value=ChatOutcome(text='本校使用选科走班模式。'))
    await run_agent_loop([{'role': 'user', 'content': '本校是哪种课表模式？'}], '',
        base_url='http://test', api_key='', model='test', timeout=10,
        on_progress=None, on_trace=None, on_step=None,
        model_gateway=SimpleNamespace(complete_tools=caller), tool_scope=scope,
        harness=GUIDE_HARNESS, page_title=None, page_path=None, can=None, cannot=None,
        page_context={'timetable_mode': 'administrative'}, retrieved='')
    system = caller.await_args.kwargs['messages'][0]['content']
    assert '服务端已核对的学校环境' in system
    assert '"timetable_mode": "walk_class"' in system
    assert '数字明细优先使用表格' in system
