import io
import json
import time
from types import SimpleNamespace

import httpx
import openpyxl
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.excel_config import read_rows
from app.api.deps import get_current_tenant, get_current_user
from app.api.v1 import page_excel
from app.core.security import create_access_token
from app.db.session import get_session
from app.models.org import Class, CourseHourPlan, Grade, Subject, TeachingAssignment, Tenant, User, TenantConfig


def workbook(tables):
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, rows in tables.items():
        sheet = book.create_sheet(name)
        for row in rows: sheet.append(row)
    output = io.BytesIO(); book.save(output)
    return output.getvalue()


def full_file(subject='数学', hours=4, rule='教师禁排'):
    return workbook({
        '填写说明': [['ignored']], '示例_请勿导入': [['科目'], ['不可导入']],
        '科目': [['科目', '课程类型', '晚自习资格'], [subject, '学科课', '不允许']],
        '班级课时': [['年级', '班级', '科目', '工作日课时', '周六课时', '单双周', '单周晚课', '双周晚课'],
                   ['高一', '高一（1）班', subject, hours, 0, '每周', 0, 0]],
        '任课关系': [['年级', '班级', '科目', '教师'], ['高一', '高一（1）班', subject, '张老师']],
        '排课规则': [['规则类型', '适用对象类型', '适用对象名称', '年级', '星期', '节次', '约束强度', '规则说明'],
                   [rule, '教师', '张老师', '高一', '周一', '1、2', '必须满足', '教师周一前两节禁排']],
        'Sheet2': [],
    })


@pytest_asyncio.fixture
async def context(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/fixture.db')
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all([Tenant(id=1, code='fixture', name='测试学校'), Tenant(id=2, code='other', name='另一学校'),
            Grade(id=1, tenant_id=1, name='高一年级', level=1),
            Class(id=1, tenant_id=1, grade_id=1, name='高一（1）班', academic_year='2026-2027', term='1'),
            Subject(id=1, tenant_id=1, name='数学', course_type='subject', evening_study_allowed=False),
            User(id=1, tenant_id=1, name='校长', phone='principal', password_hash='unused', role='director'),
            User(id=2, tenant_id=1, name='张老师', phone='teacher', password_hash='unused', role='teacher')])
        await session.commit()
    app = FastAPI(); app.include_router(page_excel.router)
    async def session_override():
        async with AsyncSession(engine, expire_on_commit=False) as session: yield session
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, tenant_id=1, role='director')
    app.dependency_overrides[get_current_tenant] = lambda: 1
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
        yield client, engine, app
    await engine.dispose()


async def preview(client, data=None, **options):
    return await client.post('/page-agent/excel/preview', data={'academic_year': '2026-2027', 'term': '1', **options},
                             files={'file': ('fixture.xlsx', data or full_file(), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})


@pytest.mark.asyncio
async def test_preview_is_read_only_and_ignores_examples(context):
    client, engine, _ = context
    response = await preview(client)
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert [i['kind'] for i in data['items']] == ['hours', 'assignment', 'rule']
    assert all(i['status'] == 'ready' for i in data['items']), data
    assert not any(i.get('task_token') for i in data['items'])
    async with AsyncSession(engine) as session:
        assert not (await session.execute(select(CourseHourPlan))).scalars().all()
        assert not (await session.execute(select(TeachingAssignment))).scalars().all()
        assert not (await session.execute(select(TenantConfig))).scalars().all()


@pytest.mark.asyncio
async def test_second_confirmation_and_all_business_writes_are_idempotent(context):
    client, engine, _ = context
    data = (await preview(client)).json()['data']
    assert (await client.post('/page-agent/excel/confirm', json={'plan_token': data['plan_token'], 'confirmed': False})).status_code == 422
    assert (await client.post('/page-agent/excel/save', json={'task_token': data['plan_token'], 'values': {}})).status_code == 403
    confirmation = await client.post('/page-agent/excel/confirm', json={'plan_token': data['plan_token'], 'confirmed': True})
    assert confirmation.status_code == 200, confirmation.text
    for item in confirmation.json()['data']['items']:
        body = {'task_token': item['task_token'], 'values': {f['key']: f['value'] for f in item['fields']}}
        wrong = {**body, 'values': {**body['values'], 'unexpected': 'injection'}}
        assert (await client.post('/page-agent/excel/save', json=wrong)).status_code == 422
        saved = await client.post('/page-agent/excel/save', json=body)
        assert saved.status_code == 200, saved.text
        assert (await client.post('/page-agent/excel/status', json={'task_token': item['task_token']})).json()['data']['saved']
        duplicate = await client.post('/page-agent/excel/save', json=body)
        assert duplicate.json()['data']['skipped']
    async with AsyncSession(engine) as session:
        assert len((await session.execute(select(CourseHourPlan))).scalars().all()) == 1
        assert len((await session.execute(select(TeachingAssignment))).scalars().all()) == 1
    again = (await preview(client)).json()['data']
    assert all(i['status'] == 'exists' for i in again['items']), again


@pytest.mark.asyncio
async def test_cross_tenant_expiry_and_teacher_access(context):
    client, _, app = context
    data = (await preview(client)).json()['data']
    wrong = create_access_token(1, {'scope': 'excel-preview', 'tid': 2, 'items': [], 'exp': int(time.time()) + 100})
    expired = create_access_token(1, {'scope': 'excel-preview', 'tid': 1, 'items': [], 'exp': int(time.time()) - 1})
    for token in [wrong, expired, data['plan_token'][:-3] + 'xxx']:
        assert (await client.post('/page-agent/excel/confirm', json={'plan_token': token, 'confirmed': True})).status_code == 403
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=2, tenant_id=1, role='teacher')
    assert (await preview(client)).status_code == 403


@pytest.mark.asyncio
async def test_conflicting_saved_configuration_blocks_plan(context):
    client, engine, _ = context
    async with AsyncSession(engine) as session:
        session.add(CourseHourPlan(tenant_id=1, class_id=1, subject_id=1, academic_year='2026-2027', weekday_periods=3, weekly_periods=3))
        await session.commit()
    data = (await preview(client)).json()['data']
    assert any(i['status'] == 'blocked' for i in data['items'])
    assert (await client.post('/page-agent/excel/confirm', json={'plan_token': data['plan_token'], 'confirmed': True})).status_code == 409


@pytest.mark.asyncio
async def test_change_after_preview_cannot_overwrite(context):
    client, engine, _ = context
    data = (await preview(client)).json()['data']
    confirmed = (await client.post('/page-agent/excel/confirm', json={'plan_token': data['plan_token'], 'confirmed': True})).json()['data']['items']
    async with AsyncSession(engine) as session:
        session.add(CourseHourPlan(tenant_id=1, class_id=1, subject_id=1, academic_year='2026-2027', weekday_periods=2, weekly_periods=2))
        await session.commit()
    item = confirmed[0]
    result = await client.post('/page-agent/excel/save', json={'task_token': item['task_token'], 'values': {f['key']: f['value'] for f in item['fields']}})
    assert result.status_code == 409


@pytest.mark.asyncio
async def test_unknown_rule_and_wrong_grade_block_confirmation(context):
    client, _, _ = context
    data = (await preview(client, full_file(rule='其他'))).json()['data']
    assert any(i['kind'] == 'rule' and i['status'] == 'blocked' for i in data['items'])
    assert (await client.post('/page-agent/excel/confirm', json={'plan_token': data['plan_token'], 'confirmed': True})).status_code == 409


@pytest.mark.parametrize('value', ['=1+1', 'NaN', '-1', '2.3', '21'])
@pytest.mark.asyncio
async def test_invalid_hours_cannot_execute(context, value):
    client, _, _ = context
    response = await preview(client, full_file(hours=value))
    if response.status_code == 200:
        assert any(i['status'] == 'blocked' for i in response.json()['data']['items'])
    else: assert response.status_code == 422


def test_merged_subjects_and_empty_sheet_are_read_completely():
    book = openpyxl.Workbook(); sheet = book.active; sheet.title = '教师表'
    sheet.append(['学科', '姓名', '所教班级', '周一到周五课时'])
    sheet.append(['数学', '张老师', '1、2', 8]); sheet.append([None, '李老师', '3', 4]); sheet.merge_cells('A2:A3')
    book.create_sheet('Sheet2')
    buf = io.BytesIO(); book.save(buf)
    rows = read_rows('fixture.xlsx', buf.getvalue())
    assert len(rows) == 2 and rows[1]['subject'] == '数学'
    assert rows[0]['teacher_totals']


@pytest.mark.asyncio
async def test_teacher_totals_require_explicit_interpretation(context):
    client, _, _ = context
    teacher_file = workbook({'教师表': [['学科', '姓名', '所教班级', '周一到周五课时', '周六课时', '周一到周六晚课课时'],
                                  ['数学', '张老师', '1、2', 8, 1, 1]]})
    assert (await preview(client, teacher_file)).status_code == 422
    result = await preview(client, teacher_file, distribute='true', selected_class='高一（1）班')
    assert result.status_code == 422 and '单周' in result.text
    result = await preview(client, teacher_file, distribute='true', selected_class='高一（1）班', half_parity='单周')
    assert result.status_code == 200
    assert any('晚自习' in i['message'] for i in result.json()['data']['items'])


def test_long_file_is_rejected_instead_of_truncated():
    rows = [['科目']] + [[f'科目{i}'] for i in range(211)]
    with pytest.raises(ValueError, match='过大|200'):
        read_rows('fixture.xlsx', workbook({'科目': rows}))


@pytest.mark.asyncio
async def test_subject_only_creation_and_replay(context):
    client, _, _ = context
    file = workbook({'科目': [['科目', '课程类型', '晚自习资格'], ['测试活动', '活动课', '不允许']]})
    data = (await preview(client, file)).json()['data']
    item = (await client.post('/page-agent/excel/confirm', json={'plan_token': data['plan_token'], 'confirmed': True})).json()['data']['items'][0]
    result = await client.post('/page-agent/excel/save', json={'task_token': item['task_token'], 'values': {f['key']: f['value'] for f in item['fields']}})
    assert result.status_code == 200
    assert (await preview(client, file)).json()['data']['items'] == []


@pytest.mark.asyncio
async def test_new_subject_dependencies_and_rule_phone_resolution(context):
    client, _, _ = context
    content = full_file(subject='新科目')
    book = openpyxl.load_workbook(io.BytesIO(content))
    sheet = book['排课规则']
    sheet.cell(2, 1, '科目禁排'); sheet.cell(2, 2, '科目'); sheet.cell(2, 3, '新科目')
    sheet.append(['教师禁排', '教师', 'teacher', '高一', '周二', '3', '必须满足', '账号匹配'])
    output = io.BytesIO(); book.save(output)
    data = (await preview(client, output.getvalue())).json()['data']
    assert [i['kind'] for i in data['items']] == ['subject', 'hours', 'assignment', 'rule']
    assert all(i['status'] == 'ready' for i in data['items']), data
    items = (await client.post('/page-agent/excel/confirm', json={'plan_token': data['plan_token'], 'confirmed': True})).json()['data']['items']
    for item in items:
        response = await client.post('/page-agent/excel/save', json={'task_token': item['task_token'], 'values': {f['key']: f['value'] for f in item['fields']}})
        assert response.status_code == 200, response.text
    assert all(i['status'] == 'exists' for i in (await preview(client, output.getvalue())).json()['data']['items'])


@pytest.mark.asyncio
async def test_corrupt_file_returns_actionable_error(context):
    client, _, _ = context
    assert (await preview(client, b'not an Excel archive')).status_code == 422


@pytest.mark.asyncio
async def test_rule_class_scope_is_never_silently_filtered(context):
    client, _, _ = context
    file = workbook({'排课规则': [['规则类型', '适用对象类型', '适用对象名称', '年级', '班级', '星期', '节次', '约束强度'],
                               ['教师禁排', '教师', '张老师', '高一', '别的班级', '周一', '1', '必须满足']]})
    data = (await preview(client, file, selected_class='高一（1）班')).json()['data']
    assert len(data['items']) == 1 and data['items'][0]['status'] == 'blocked'


@pytest.mark.asyncio
async def test_subject_definitions_can_follow_dependent_sheets(context):
    client, _, _ = context
    book = openpyxl.load_workbook(io.BytesIO(full_file(subject='后置科目')))
    book.move_sheet('科目', offset=len(book.worksheets) - 3)
    output = io.BytesIO(); book.save(output)
    data = (await preview(client, output.getvalue())).json()['data']
    assert [i['kind'] for i in data['items']] == ['subject', 'hours', 'assignment', 'rule']
    assert all(i['status'] == 'ready' for i in data['items']), data
