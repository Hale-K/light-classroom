import json
from types import SimpleNamespace

import pytest

from app.ai.tools.school.resource_planning import calculate_resource_plan


def calculate(**kw):
    return json.loads(calculate_resource_plan(json.dumps({
        'student_count': 1000, 'minimum_class_size': 45, 'maximum_class_size': 55,
        'basis': '用户人数；教师工作量及课时为待确认假设', **kw})))


def test_class_sizes_cover_all_students_without_breaking_bounds():
    result = calculate()['data']
    assert (result['minimum_classes'], result['maximum_classes']) == (19, 22)
    for option in result['class_options']:
        assert sum(r['class_size'] * r['classes'] for r in option['distribution']) == 1000
        assert all(45 <= r['class_size'] <= 55 for r in option['distribution'])
    assert result['teachers_required'] is None


def test_teachers_are_rounded_per_subject_and_includes_added_courses():
    subjects = {**dict.fromkeys(['语文', '数学', '英语'], 5),
                **dict.fromkeys(['物理', '化学', '生物'], 3),
                **dict.fromkeys(['政治', '历史', '地理', '体育'], 2),
                **dict.fromkeys(['心理', '音乐', '美术'], 1)}
    result = calculate(preferred_class_count=20, subjects=[
        {'subject': name, 'weekly_periods': hours, 'teacher_weekly_periods': 14}
        for name, hours in subjects.items()])['data']
    assert result['weekly_periods_per_class'] == 35
    assert result['teachers_required'] == 57
    assert result['selected']['rooms_required'] == 20


def test_invalid_or_infeasible_class_distribution_is_rejected():
    assert not calculate(minimum_class_size=56)['ok']
    assert not calculate(preferred_class_count=18)['ok']
    assert not calculate(student_count=56, minimum_class_size=45, maximum_class_size=55)['ok']


def test_alternate_week_staffing_uses_peak_not_average():
    result = calculate(preferred_class_count=20, subjects=[
        {'subject': '心理', 'weekly_periods': 1, 'week_parity': 'odd', 'teacher_weekly_periods': 14},
    ])['data']
    assert result['teachers_required'] == 2
    assert result['weekly_periods_per_class'] == 0.5
    assert result['periods_per_class_by_week'] == {'odd': 1, 'even': 0}


def test_provider_failure_preserves_mixed_week_staffing_without_formatter_crash():
    from app.ai.agent.partial import checked_partial
    hours = {'语文':6,'英语':6,'数学':7,'物理':4,'化学':4,'生物':3,'政治':3,'历史':3,'地理':3,'体育':2,'音乐':1,'美术':1,'心理':1}
    result = calculate(preferred_class_count=20, subjects=[
        {'subject':name,'weekly_periods':value,'teacher_weekly_periods':14,
         'week_parity':'odd' if name == '心理' else 'all'} for name,value in hours.items()])
    assert result['data']['teachers_required'] == 69
    partial = checked_partial(SimpleNamespace(checked_hour_evidence=None,checked_resource_plan=result),'模型接口不可用')
    assert partial is not None
    assert '| 心理 | 1.0 | 0 | 14.0 | 2 |' in partial['text']
    assert '| 合计 | 44.0 | 43.0 |' in partial['text']
    assert '43.5' in partial['text']
    assert '最终规划尚未完成' in partial['text']


@pytest.mark.asyncio
async def test_staffing_followup_cannot_skip_calculation_tool():
    from app.ai.gateway.tool import ToolScope
    scope = ToolScope(None, 1, None, False, {})
    scope.configure_request('沿用刚才20班方案，教师周授课量改14节，重新计算各科教师人数')
    assert 'calculate_resource_plan' in await scope.final_guard('共需68位教师')


@pytest.mark.asyncio
async def test_original_question_routes_to_planning_and_does_not_require_inventory():
    from app.ai.intent.gateway import IntentGateway, ExecutionMode
    from app.ai.gateway.tool import ToolScope
    from app.ai.harness.router import HarnessRouter

    question = '我现在有1000个人的学生，每一个班可以安排45-55个人，请告知我需要几个教室，需要多少老师，我们添加了心理+音乐+美术+体育，请结合高一的课程，看看需要多少老师比较合适'
    decision = await IntentGateway().classify(None, question, page_path='/exam-scheduling')
    assert decision.effective_mode == ExecutionMode.PLANNING
    harness = HarnessRouter().select(decision)
    scope = ToolScope(session=None, tenant_id=1, user_id=None, can_manage_rules=False,
                      page_context={}, allowed_tools=harness.allowed_tools)
    scope.configure_request(question)
    assert 'lookup_room_resources' not in scope._required_evidence
    result = await scope.execute('calculate_resource_plan', json.dumps({
        'student_count': 1000, 'minimum_class_size': 45, 'maximum_class_size': 55, 'basis': '用户给定'}))
    assert json.loads(result)['ok']
    assert scope.checked_resource_plan['data']['minimum_classes'] == 19


def test_failure_summary_uses_business_labels_and_preserves_calculations():
    from app.ai.agent.partial import checked_partial

    scope = SimpleNamespace(checked_resource_plan=calculate(), checked_hour_evidence=None)
    text = checked_partial(scope, '模型超时')['text']
    assert '| 19 |' in text and '| 22 |' in text
    assert '最终规划尚未完成' in text
    scope = SimpleNamespace(checked_read_evidence=[{'evidence_id': 'lookup_room_resources:2',
        'scope': {'academic_year': '2026-2027', 'term': '1', 'room_type': None},
        'summary': {'configured_spaces': 1}}])
    text = checked_partial(scope, '模型超时')['text']
    assert '2026-2027学年' in text and '第1学期' in text
    assert 'lookup_room_resources' not in text and '"room_type"' not in text
