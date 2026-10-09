import json

import pytest

from app.ai.graph.loop import ReactLoop
from app.ai.model.chat import ChatError, ChatOutcome
from app.ai.tools.markdown import format_markdown, hour_table_error


BAD = '建议如下。\n\n| 科目 | 建议课时 | 说明 |\n| --- | --- | --- |\n| 语文 | 7 | — |\n| 数学 | 7 | — |\n| 英语 | 7 | — |\n| 物理 | 6 | — |\n| 化学 | 6 | — |\n| 生物 | 6 | — |\n| 政治 | 6 | — |\n| 历史 | 6 | — |\n| 美术 | 1 | — |\n| 音乐 | 1 | — |\n| 体育 | 2 | — |\n| 合计 | 54 | — |'
GOOD = BAD.replace('| 政治 | 6 |', '| 政治 | 5 |')


@pytest.mark.asyncio
async def test_incorrect_subject_hour_total_is_repaired_before_returning():
    seen = []

    async def caller(**kwargs):
        seen.append(kwargs)
        return ChatOutcome(text=BAD if len(seen) == 1 else GOOD)

    result = await ReactLoop(base_url='http://test', api_key='', model='test', timeout=10,
        messages=[{'role': 'user', 'content': '给我课时方案'}], tools=[],
        executor=None, caller=caller).run()
    assert result.text == GOOD
    assert len(seen) == 2
    assert '55' in seen[1]['messages'][-1]['content']


@pytest.mark.asyncio
async def test_persistently_incorrect_total_is_not_delivered():
    async def caller(**kwargs):
        return ChatOutcome(text=BAD)

    with pytest.raises(ChatError) as error:
        await ReactLoop(base_url='http://test', api_key='', model='test', timeout=10,
            messages=[{'role': 'user', 'content': '给我课时方案'}], tools=[],
            executor=None, caller=caller).run()
    assert error.value.error_class == 'invalid_answer'


def test_formatter_rejects_incorrect_hour_table_totals():
    result = json.loads(format_markdown(json.dumps({'summary': '课时建议', 'sections': [{
        'type': 'table', 'columns': ['科目', '建议课时'],
        'rows': [['数学', '7'], ['语文', '7'], ['合计', '13']],
    }]})))
    assert result['ok'] is False
    assert '14' in result['message']


def test_non_additive_or_qualified_tables_are_not_misinterpreted():
    from app.ai.tools.markdown import hour_table_error

    assert hour_table_error('| 教师 | 去重人数 |\n| --- | --- |\n| 甲 | 2 |\n| 乙 | 2 |\n| 合计 | 3 |') is None
    assert hour_table_error('| 科目 | 当前课时 |\n| --- | --- |\n| 数学 | 3（单周） |\n| 语文 | 2（双周） |\n| 合计 | 2.5 |') is None
    assert hour_table_error(GOOD) is None


def test_three_scenario_comparison_accepts_four_columns_and_checks_each_total():
    body = {'summary': '三套课时建议', 'sections': [{
        'type': 'table', 'columns': ['科目', '方案一', '方案二', '方案三'],
        'rows': [['数学', '31', '35', '39'], ['体育', '2', '2', '2'],
                 ['音乐', '1', '1', '1'], ['心理', '1', '1', '1'],
                 ['合计', '35', '39', '43']],
    }]}
    assert json.loads(format_markdown(json.dumps(body)))['ok'] is True
    body['sections'][0]['rows'][-1][2] = '43'
    result = json.loads(format_markdown(json.dumps(body)))
    assert result['ok'] is False
    assert '方案二' in result['message'] and '39' in result['message']


@pytest.mark.parametrize('field', ['summary', 'paragraph'])
def test_formatter_does_not_accept_raw_flat_tables_inside_text_blocks(field):
    flat = '#### 方案二39节 | 科目 | 建议课时 | | --- | --- | | 数学 | 39 | | 合计 | 39 |'
    body = {'summary': flat if field == 'summary' else '课时建议', 'sections': []}
    if field == 'paragraph':
        body['sections'] = [{'type': 'paragraph', 'text': flat}]
    result = json.loads(format_markdown(json.dumps(body)))
    assert result['ok'] is False
    assert result['code'] == 'INVALID_ARGUMENT'


@pytest.mark.parametrize('heading', ['方案二（39节）', '方案三：总课时35节'])
def test_scenario_heading_hours_must_equal_its_table_total(heading):
    table = f'#### {heading}\n\n| 科目 | 建议课时 |\n| --- | --- |\n| 数学 | 40 |\n| 体育 | 2 |\n| 心理 | 1 |\n| 合计 | 43 |'
    error = hour_table_error(table)
    assert error and '标题' in error and '43' in error


@pytest.mark.asyncio
async def test_final_guard_matches_values_to_validated_scenario_not_only_subject_names():
    from app.ai.gateway.tool import ToolScope
    scope = ToolScope(object(), 1, 1, True, {})
    scope._last_hour_validation = {'all_valid': True, 'all_numeric_constraints_valid': True,
        'scenarios': [{'name': '方案A', 'subjects': [
            {'subject': '数学', 'periods': 7, 'week_parity': 'all'}], 'errors': []}]}
    scope._checked_hour_scenarios = True
    error = await scope.final_guard('方案A课时已全部通过校验。\n| 科目 | 方案A课时 |\n| --- | --- |\n| 数学 | 99 |')
    assert error and '数学' in error and '7' in error and '99' in error
    assert await scope.final_guard('方案A课时建议。\n| 科目 | 方案A课时 |\n| --- | --- |\n| 数学 | 7 |') is None
    # Omitting the word “方案” cannot bypass evidence matching.
    assert await scope.final_guard('课时建议已核对。\n| 科目 | 建议课时 |\n| --- | --- |\n| 数学 | 99 |')


@pytest.mark.asyncio
async def test_final_guard_checks_every_scenario_column_and_missing_subject():
    from app.ai.gateway.tool import ToolScope
    scope = ToolScope(object(), 1, 1, True, {})
    scope._last_hour_validation = {'all_valid': True, 'all_numeric_constraints_valid': True,
        'scenarios': [{'name': name, 'subjects': [
            {'subject': '数学', 'periods': value, 'week_parity': 'all'},
            {'subject': '体育', 'periods': 2, 'week_parity': 'all'}], 'errors': []}
            for name, value in [('方案一', 33), ('方案二', 37), ('方案三', 41)]]}
    scope._checked_hour_scenarios = True
    table = '三套方案课时建议。\n| 科目 | 方案一 | 方案二 | 方案三 |\n| --- | --- | --- | --- |\n| 数学 | 33 | 38 | 41 |\n| 体育 | 2 | 2 | 2 |\n| 合计 | 35 | 40 | 43 |'
    assert '37' in await scope.final_guard(table)
    good = table.replace('| 33 | 38 | 41 |', '| 33 | 37 | 41 |').replace('| 35 | 40 | 43 |', '| 35 | 39 | 43 |')
    assert await scope.final_guard(good) is None
    assert '体育' in await scope.final_guard(good.replace('| 体育 | 2 | 2 | 2 |\n', ''))


@pytest.mark.asyncio
async def test_final_guard_parity_values_require_matching_parity_columns():
    from app.ai.gateway.tool import ToolScope
    scope = ToolScope(object(), 1, 1, True, {})
    scope._last_hour_validation = {'all_valid': True, 'all_numeric_constraints_valid': True,
        'scenarios': [{'name': '方案A', 'subjects': [
            {'subject': '数学', 'periods': 8, 'week_parity': 'odd'},
            {'subject': '数学', 'periods': 7, 'week_parity': 'even'}], 'errors': []}]}
    scope._checked_hour_scenarios = True
    assert await scope.final_guard('方案A课时建议。\n| 科目 | 方案A课时 |\n| --- | --- |\n| 数学 | 8 |')
    assert await scope.final_guard('方案A课时建议。\n| 科目 | 方案A单周课时 | 方案A双周课时 |\n| --- | --- | --- |\n| 数学 | 8 | 7 |') is None


@pytest.mark.asyncio
async def test_aggregate_validation_cannot_be_promoted_to_full_timetable_feasibility():
    from app.ai.gateway.tool import ToolScope
    scope = ToolScope(object(), 1, 1, True, {})
    scope._last_hour_validation = {'all_valid': True, 'all_numeric_constraints_valid': True,
        'coverage': {'teacher_conflicts_verified': False, 'room_conflicts_verified': False,
                     'mandatory_slot_placement_verified': False, 'all_rules_verified': False},
        'scenarios': [{'name': '方案A', 'subjects': [
            {'subject': '数学', 'periods': 7, 'week_parity': 'all'}], 'errors': []}]}
    scope._checked_hour_scenarios = True
    table = '\n| 科目 | 方案A课时 |\n| --- | --- |\n| 数学 | 7 |'
    assert await scope.final_guard('方案A可直接实施，已满足完整排课全部约束。' + table)
    assert await scope.final_guard('方案A课时数字约束已通过。' + table)
    partial = '方案A课时数字约束已通过。教师与教室冲突尚未验证，实际排满待验证。' + table
    assert await scope.final_guard(partial) is None
    natural = ('本次仅课量验算。教师时间冲突、教室冲突以及最终能否把第1-7节实际排满，'
        '需在录入课时并完成生成后的冲突校验中确认，本回复不预设结论。' + table)
    assert await scope.final_guard(natural) is None
    assert await scope.final_guard(natural.replace('需在录入课时并完成生成后的冲突校验中确认', '无需验证，全部排课均已通过'))
    # A pure prose claim cannot skip the same evidence boundary.
    assert await scope.final_guard('已经完成完整排课，方案可直接实施。')


@pytest.mark.asyncio
async def test_failed_numeric_validation_cannot_claim_success_without_any_table():
    from app.ai.gateway.tool import ToolScope
    scope = ToolScope(object(), 1, 1, True, {})
    scope._last_hour_validation = {'all_valid': False, 'all_numeric_constraints_valid': False,
        'scenarios': [{'name': '方案A', 'subjects': [], 'errors': [{'code': 'CAPACITY_EXCEEDED'}]}]}
    assert await scope.final_guard('三套方案已全部通过校验。')


@pytest.mark.asyncio
async def test_current_data_table_remains_readable_when_scenario_delivery_is_blocked():
    from app.ai.gateway.tool import ToolScope
    scope = ToolScope(object(), 1, 1, True, {})
    scope.configure_request('心理1节')
    scope._last_hour_validation = {'all_valid': False, 'all_numeric_constraints_valid': False,
        'scenarios': [{'name': '方案A', 'subjects': [{'subject': '数学', 'periods': 50}],
                       'errors': [{'code': 'CAPACITY_EXCEEDED'}]}]}
    text = '方案尚未通过，课位不足。已查询现状如下，需先调整范围。\n| 科目 | 当前课时 |\n| --- | --- |\n| 数学 | 7 |'
    assert await scope.final_guard(text) is None
