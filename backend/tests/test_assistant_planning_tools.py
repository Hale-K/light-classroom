import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.tools import school
from app.models.org import Class, CourseHourPlan, Grade, Subject, TeachingAssignment, Tenant, TenantConfig, OrganizationUnit
from app.models.gaokao import GaokaoScheme, TeachingClass, TeachingSubjectHourPlan, WalkSchedulingPlan, WalkSchedulingSlot, WalkSchedulingRoom
from app.models.scheduling_grid import SchedulingGridPlan, SchedulingGridDay, SchedulingGridSlot, SchedulingGridSubject


@pytest.fixture
def planning_db():
    engine = create_engine('sqlite://')
    models = (Class, CourseHourPlan, Grade, Subject, TeachingAssignment, Tenant, TenantConfig, OrganizationUnit,
              GaokaoScheme, TeachingClass, TeachingSubjectHourPlan, WalkSchedulingPlan,
              WalkSchedulingSlot, WalkSchedulingRoom, SchedulingGridPlan, SchedulingGridDay,
              SchedulingGridSlot, SchedulingGridSubject)
    for model in models:
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            Tenant(id=1, code='test', name='学校', province='吉林'),
            TenantConfig(tenant_id=1, config_key='timetable_mode', config_value={'mode': 'administrative'}),
            TenantConfig(tenant_id=1, config_key='academic_years', config_value={
                'current_entry_year': 2026, 'current_academic_year': '2026-2027', 'current_term': '1'}),
            Grade(id=1, tenant_id=1, name='高一', level=1),
            Grade(id=2, tenant_id=1, name='高二', level=2),
            Grade(id=3, tenant_id=2, name='外校', level=1),
            Class(id=10, tenant_id=1, grade_id=1, name='高一1班', cohort_label='2026', academic_year='2026-2027', term='1'),
            Class(id=11, tenant_id=1, grade_id=1, name='旧班', academic_year='2025-2026', term='1'),
            Class(id=20, tenant_id=1, grade_id=2, name='高二1班', academic_year='2026-2027', term='1'),
            Subject(id=1, tenant_id=1, name='数学'),
            Subject(id=2, tenant_id=1, name='体育'),
            Subject(id=3, tenant_id=1, name='音乐'),
            Subject(id=4, tenant_id=1, name='心理'),
            CourseHourPlan(tenant_id=1, class_id=10, subject_id=1, academic_year='2026-2027', term='1', weekday_periods=8, weekly_periods=8, week_parity='odd'),
            CourseHourPlan(tenant_id=1, class_id=10, subject_id=1, academic_year='2026-2027', term='1', weekday_periods=7, weekly_periods=7, week_parity='even'),
            GaokaoScheme(tenant_id=1, name='2026届方案', entry_year=2026, required_subject_ids=[1], primary_subject_ids=[], secondary_subject_ids=[]),
            SchedulingGridPlan(id=1, tenant_id=1, grade_id=1, academic_year='2026-2027', term='1'),
            SchedulingGridSlot(plan_id=1, weekday=1, period=9, week_parity='odd', slot_type='disabled'),
        ])
        session.add_all([SchedulingGridDay(plan_id=1, weekday=day, daytime_periods=9 if day <= 6 else 0) for day in range(1, 8)])
        session.commit()

        class ReadOnly:
            async def execute(self, statement):
                assert statement.is_select, '规划工具不得写入'
                return session.execute(statement)

        yield ReadOnly(), session
    engine.dispose()


async def ask(db, name, context=None, **args):
    return json.loads(await school.execute_school_tool(name, json.dumps(args, ensure_ascii=False),
        session=db[0], tenant_id=1, page_context=context or {'grade_id': 1, 'academic_year': '2026-2027', 'term': '1'}))


@pytest.mark.asyncio
async def test_basis_reads_grade_grid_overrides_parity_and_policy_without_invented_scores(planning_db):
    result = await ask(planning_db, 'lookup_planning_basis')
    assert result['ok']
    data = result['data']
    assert data['grid']['configured'] is True
    assert data['grid']['daytime_capacity_by_week'] == {'odd': 53, 'even': 54}
    assert data['grid']['weekday_capacity_by_week'] == {'odd': 44, 'even': 45}
    assert data['current_hours'][0]['daytime_periods_by_week'] == {'odd': 8, 'even': 7}
    assert data['score_weights']['verified'] is False
    assert data['selection_policy']['schemes'][0]['entry_year'] == 2026
    assert data['walk_resources']['applicable'] is False


@pytest.mark.asyncio
async def test_validator_checks_three_scenarios_exact_totals_fixed_subjects_and_capacity(planning_db):
    common = [{'subject': '体育', 'periods': 2}, {'subject': '音乐', 'periods': 1}, {'subject': '心理', 'periods': 1}]
    result = await ask(planning_db, 'validate_hour_scenarios', weekdays=[1, 2, 3, 4, 5],
        mandatory_periods=list(range(1, 8)), optional_periods=[8, 9],
        fixed_subject_hours={'体育': 2, '音乐': 1, '心理': 1}, scenarios=[
            {'name': '35节', 'subjects': [{'subject': '数学', 'periods': 31}, *common]},
            {'name': '45节', 'subjects': [{'subject': '数学', 'periods': 41}, *common]},
            {'name': '34节', 'subjects': [{'subject': '数学', 'periods': 30}, *common]},
        ])
    assert result['ok']
    data = result['data']
    assert data['mandatory_capacity_by_week'] == {'odd': 35, 'even': 35}
    assert data['maximum_capacity_by_week'] == {'odd': 44, 'even': 45}
    assert data['scenarios'][0]['valid'] is True
    assert data['scenarios'][0]['total_periods_by_week'] == {'odd': 35, 'even': 35}
    assert 'CAPACITY_EXCEEDED' in {issue['code'] for issue in data['scenarios'][1]['errors']}
    assert 'MANDATORY_UNFILLED' in {issue['code'] for issue in data['scenarios'][2]['errors']}
    assert data['coverage']['solver_feasibility_verified'] is False


@pytest.mark.asyncio
async def test_validator_does_not_combine_odd_and_even_hours_and_checks_fixed_subjects(planning_db):
    result = await ask(planning_db, 'validate_hour_scenarios', scenarios=[{'name': '单双周', 'subjects': [
        {'subject': '数学', 'periods': 10, 'week_parity': 'odd'},
        {'subject': '数学', 'periods': 9, 'week_parity': 'even'},
        {'subject': '体育', 'periods': 1},
    ]}], fixed_subject_hours={'体育': 2})
    scenario = result['data']['scenarios'][0]
    assert scenario['total_periods_by_week'] == {'odd': 11, 'even': 10}
    assert 'FIXED_SUBJECT_MISMATCH' in {issue['code'] for issue in scenario['errors']}


@pytest.mark.asyncio
async def test_scope_rejects_foreign_and_ambiguous_grades_and_explicit_scope_overrides_page(planning_db):
    for args in ({'grade_id': 3}, {'grade': '高'}, {'class_id': 11}):
        assert (await ask(planning_db, 'lookup_planning_basis', **args))['code'] == 'MISSING_SCOPE'
    result = await ask(planning_db, 'lookup_planning_basis', grade='高二',
        context={'grade_id': 1, 'class_id': 10, 'academic_year': '2026-2027', 'term': '1'})
    assert result['scope']['grade_id'] == 2
    assert result['data']['grid']['configured'] is False


@pytest.mark.asyncio
async def test_validator_cannot_verify_default_unsaved_grid(planning_db):
    result = await ask(planning_db, 'validate_hour_scenarios', grade_id=2,
        scenarios=[{'name': '假设', 'subjects': [{'subject': '数学', 'periods': 35}]}])
    assert result['code'] == 'MISSING_DATA'
    assert result['ok'] is False


@pytest.mark.asyncio
async def test_planning_rejects_invalid_parameters_and_overlapping_period_roles(planning_db):
    for args in ({'term': '3'}, {'grade_id': True}, {'extra': 'untrusted'}):
        assert (await ask(planning_db, 'lookup_planning_basis', **args))['code'] == 'INVALID_ARGUMENT'
    base = {'scenarios': [{'name': '测试', 'subjects': [{'subject': '数学', 'periods': 4}]}]}
    assert (await ask(planning_db, 'validate_hour_scenarios', **base,
        mandatory_periods=[1, 2], optional_periods=[2, 3]))['code'] == 'INVALID_ARGUMENT'
    assert (await ask(planning_db, 'validate_hour_scenarios', scenarios=[{'name': '测试', 'subjects': [
        {'subject': '数学', 'periods': 4}, {'subject': '数学', 'periods': 3}]}]))['code'] == 'INVALID_ARGUMENT'


@pytest.mark.asyncio
async def test_walk_basis_returns_defaults_reserved_slots_and_room_pool(planning_db):
    db, session = planning_db
    config = session.query(TenantConfig).filter_by(config_key='timetable_mode').one()
    config.config_value = {'mode': 'walk_class'}
    session.add_all([
        TeachingSubjectHourPlan(tenant_id=1, grade_id=1, subject_id=1, academic_year='2026-2027', term='1', weekly_periods=4, weekday_periods=3, weekend_periods=1),
        WalkSchedulingPlan(id=1, tenant_id=1, grade_id=1, academic_year='2026-2027', term='1'),
        WalkSchedulingSlot(plan_id=1, weekday=1, period=8), WalkSchedulingRoom(plan_id=1, room_id=7),
    ])
    session.commit()
    data = (await ask(planning_db, 'lookup_planning_basis'))['data']
    assert data['walk_resources']['applicable'] is True
    assert data['walk_resources']['subject_hour_defaults'][0]['weekday_periods'] == 3
    assert data['walk_resources']['reserved_slots'] == [{'weekday': 1, 'period': 8}]
    assert data['walk_resources']['room_ids'] == [7]


@pytest.mark.asyncio
async def test_legacy_remaining_capacity_reads_actual_grade_grid(planning_db):
    result = await ask(planning_db, 'lookup_remaining_capacity', grade='高一')
    assert '单周' in result['message'] and '53' in result['message']
    assert '双周' in result['message'] and '54' in result['message']


def test_capacity_tool_schemas_allow_confirmed_historical_scope():
    definitions = {tool['function']['name']: tool['function'] for tool in school.SCHOOL_TOOLS}
    for name in ('lookup_subject_capacity', 'lookup_remaining_capacity', 'lookup_slot_role_capacity'):
        assert {'academic_year', 'term', 'grade_id'} <= definitions[name]['parameters']['properties'].keys()


@pytest.mark.asyncio
async def test_validator_rejects_unavailable_mandatory_slot_even_with_enough_total_hours(planning_db):
    result = await ask(planning_db, 'validate_hour_scenarios', weekdays=[1], mandatory_periods=[9], optional_periods=[1, 2],
        scenarios=[{'name': '2节', 'subjects': [{'subject': '数学', 'periods': 2}]}])
    assert result['data']['scenarios'][0]['valid'] is False
    assert any(issue['code'] == 'MANDATORY_SLOT_UNAVAILABLE' and issue['week_parity'] == 'odd'
        for issue in result['data']['scenarios'][0]['errors'])


@pytest.mark.asyncio
async def test_validator_rejects_fractional_weight_as_schedulable_hours(planning_db):
    result = await ask(planning_db, 'validate_hour_scenarios',
        scenarios=[{'name': '小数比例', 'subjects': [{'subject': '数学', 'periods': 4.37}]}])
    assert result['code'] == 'INVALID_ARGUMENT'


@pytest.mark.asyncio
async def test_setup_limits_classes_to_year_and_grade_and_reports_actual_parity_slots(planning_db):
    result = await ask(planning_db, 'lookup_schedule_setup', grade_id=1)
    assert result['ok']
    text = result['message']
    assert '旧班' not in text and '高二' not in text
    assert '单周' in text and '周一 8 节' in text
    assert '双周' in text and '周一 9 节' in text


@pytest.mark.asyncio
async def test_subject_capacity_preserves_parity_and_actual_grade_slot_limits(planning_db):
    result = await ask(planning_db, 'lookup_subject_capacity', grade_id=1)
    assert result['ok']
    assert '单周' in result['message'] and '53' in result['message']
    assert '双周' in result['message'] and '54' in result['message']


@pytest.mark.asyncio
async def test_missing_subject_catalog_is_separate_from_numeric_scenario_validity(planning_db):
    result = await ask(planning_db, 'validate_hour_scenarios',
        scenarios=[{'name': '仅建议', 'subjects': [{'subject': '未建立心理课', 'periods': 1}]}],
        fixed_subject_hours={'未建立心理课': 1})
    scenario = result['data']['scenarios'][0]
    assert scenario['valid'] is False
    assert scenario['numeric_constraints_valid'] is True
    assert scenario['subject_catalog_valid'] is False
    assert scenario['total_periods_by_week'] == {'odd': 1, 'even': 1}


@pytest.mark.asyncio
async def test_gateway_preserves_user_fixed_psychology_when_model_substitutes_art(planning_db, monkeypatch):
    from app.ai.gateway.tool import ToolScope
    from app.ai.tools.school import evidence
    from unittest.mock import AsyncMock
    monkeypatch.setattr(evidence, 'authorized', AsyncMock(return_value=True))
    scope = ToolScope(planning_db[0], 1, 1, True, {'grade_id': 1, 'academic_year': '2026-2027', 'term': '1'})
    scope.configure_request('同时添加体育+2节、音乐+1节、心理+1节，设置3个方案')
    result = json.loads(await scope.execute('validate_hour_scenarios', json.dumps({
        'fixed_subject_hours': {'体育': 2, '音乐': 1},
        'scenarios': [{'name': '方案A', 'subjects': [
            {'subject': '数学', 'periods': 31}, {'subject': '体育', 'periods': 2},
            {'subject': '音乐', 'periods': 1}, {'subject': '美术', 'periods': 1}]}],
    }, ensure_ascii=False)))
    assert result['data']['fixed_subject_hours']['心理'] == 1
    assert any(issue['code'] == 'FIXED_SUBJECT_MISMATCH' and issue['subject'] == '心理'
        for issue in result['data']['scenarios'][0]['errors'])
    error = await scope.final_guard('三套方案课时已全部通过校验。\n\n| 科目 | 方案A课时 |\n| --- | --- |\n| 体育 | 2 |\n| 音乐 | 1 |\n| 美术 | 1 |')
    assert error and '心理' in error


@pytest.mark.asyncio
async def test_final_guard_requires_all_fixed_rows_and_values_in_each_scenario_column(planning_db):
    from app.ai.gateway.tool import ToolScope
    scope = ToolScope(planning_db[0], 1, 1, True, {})
    scope.configure_request('体育2、音乐1、心理1')
    missing = await scope.final_guard('三套方案课时：\n| 科目 | 方案A | 方案B | 方案C |\n| --- | --- | --- | --- |\n| 体育 | 2 | 2 | 2 |\n| 音乐 | 1 | 1 | 1 |\n| 心理 | 1 | 0 | 1 |')
    assert missing and '心理' in missing
    good = await scope.final_guard('三套方案课时：\n| 科目 | 方案A | 方案B | 方案C |\n| --- | --- | --- | --- |\n| 体育 | 2 | 2 | 2 |\n| 音乐 | 1 | 1 | 1 |\n| 心理 | 1（待建科目） | 1 | 1 |')
    assert good is None


@pytest.mark.asyncio
async def test_complex_turn_cannot_end_without_a_server_task_plan(planning_db):
    from app.ai.gateway.tool import ToolScope
    scope = ToolScope(planning_db[0], 1, 1, True, {}, allowed_tools=frozenset({'plan_task'}))
    assert '执行计划' in await scope.final_guard('请提供年级。')


@pytest.mark.asyncio
async def test_false_numeric_success_and_unvalidated_subject_substitution_are_rejected(planning_db, monkeypatch):
    from app.ai.gateway.tool import ToolScope
    from app.ai.tools.school import evidence
    from unittest.mock import AsyncMock
    monkeypatch.setattr(evidence, 'authorized', AsyncMock(return_value=True))
    scope = ToolScope(planning_db[0], 1, 1, True, {'grade_id': 1, 'academic_year': '2026-2027', 'term': '1'})
    await scope.execute('validate_hour_scenarios', json.dumps({'scenarios': [
        {'name': '方案A', 'subjects': [{'subject': '数学', 'periods': 50}]}]}))
    assert scope._checked_hour_scenarios is True
    assert scope._last_hour_validation['all_numeric_constraints_valid'] is False
    assert await scope.final_guard('方案A课时已全部通过。\n| 科目 | 方案A课时 |\n| --- | --- |\n| 数学 | 50 |')
    assert '未验算科目' in await scope.final_guard('方案A课时仅供建议。\n| 科目 | 方案A课时 |\n| --- | --- |\n| 美术 | 50 |')


@pytest.mark.asyncio
async def test_numeric_success_with_explicit_missing_catalog_remains_a_valid_temporary_answer(planning_db, monkeypatch):
    from app.ai.gateway.tool import ToolScope
    from app.ai.tools.school import evidence
    from unittest.mock import AsyncMock
    monkeypatch.setattr(evidence, 'authorized', AsyncMock(return_value=True))
    planning_db[1].delete(planning_db[1].get(Subject, 4))
    planning_db[1].commit()
    scope = ToolScope(planning_db[0], 1, 1, True, {'grade_id': 1, 'academic_year': '2026-2027', 'term': '1'})
    scope.configure_request('心理1节')
    await scope.execute('validate_hour_scenarios', json.dumps({'scenarios': [
        {'name': '方案A', 'subjects': [{'subject': '心理', 'periods': 1}]}]}, ensure_ascii=False))
    answer = '方案A数值约束已全部通过；心理未建，保留1节仅提供临时建议。教师与教室冲突、实际排满待验证。\n| 科目 | 方案A课时 |\n| --- | --- |\n| 心理 | 1 |'
    assert await scope.final_guard(answer) is None
    assert await scope.final_guard(answer.replace('数值约束已全部通过', 'all_valid=true'))
