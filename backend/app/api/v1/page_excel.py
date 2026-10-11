"""Excel previews are read-only. Only a separately confirmed plan can write."""
import hashlib
import re
import time
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from jose import JWTError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.excel_config import MAX_FILE_BYTES, read_rows, prepare_rows, inspect_item
from app.ai.excel_rules import prepare_rules, integers
from app.ai.write_lock import lock_tenant_write
from app.api.deps import get_current_tenant, get_current_user, require_management_user
from app.core.security import create_access_token, decode_access_token
from app.db.session import get_session
from app.models.org import Class, Grade, Tenant

router = APIRouter(prefix='/page-agent/excel', tags=['Excel页面配置'])


async def authorize(session, user, tenant_id):
    if user.tenant_id != tenant_id:
        raise HTTPException(403, '学校与当前账号不一致')
    await require_management_user(user=user, session=session)


def scoped_token(token, scope, user, tenant_id):
    try:
        task = decode_access_token(token)
    except JWTError as exc:
        raise HTTPException(403, '任务已过期，请重新解析并确认') from exc
    if task.get('scope') != scope or task.get('sub') != str(user.id) or task.get('tid') != tenant_id:
        raise HTTPException(403, '任务不属于当前学校和账号')
    return task


def fields_for(item):
    form, kind = item['form'], item['kind']
    labels = {
        'subject_name': '科目名称', 'class_name': '班级名称', 'teacher_name': '教师姓名',
        'course_type': '课程类型', 'evening_study_allowed': '晚自习资格',
        'weekday_periods': '工作日课时', 'saturday_periods': '周六课时',
        'weekly_periods': '周课时合计', 'week_parity': '周类型',
        'evening_periods_odd': '单周晚课', 'evening_periods_even': '双周晚课',
    }
    translations = {'subject': '学科课', 'activity': '活动课', 'all': '每周', 'odd': '单周', 'even': '双周'}
    if kind == 'rule':
        group = form['group']
        summaries = []
        for rule in group['rules']:
            reference = form.get('references', {}).get(rule['id'], {})
            parts = [rule['title'], '必须满足' if rule['priority'] == 'hard' else '尽量满足']
            if reference.get('name'): parts.append('适用对象：' + reference['name'])
            if rule['weekdays']: parts.append('星期：' + '、'.join(map(str, rule['weekdays'])))
            if rule['periods']: parts.append('节次：' + '、'.join(map(str, rule['periods'])))
            params = rule['params']
            if 'max_lessons_per_day' in params: parts.append(f"每天最多{params['max_lessons_per_day']}节")
            if 'minimum_block_length' in params: parts.append(f"每次至少连排{params['minimum_block_length']}节，每周至少{params['minimum_days']}次")
            if params.get('alternatives'):
                slot = params['alternatives'][0][0]
                parts.append(f"星期{slot['weekdays'][0]}第{slot['periods'][0]}节固定安排1次")
            summaries.append('；'.join(parts))
        summary = '\n'.join(summaries)
        return [{'key': 'name', 'label': '规则组名称', 'value': group['name']},
                {'key': 'summary', 'label': '规则明细', 'value': summary}]
    keys = ['subject_name']
    if kind == 'subject': keys += ['course_type', 'evening_study_allowed']
    else:
        keys += ['class_name']
        keys += ['weekday_periods', 'saturday_periods', 'week_parity', 'evening_periods_odd', 'evening_periods_even'] if kind == 'hours' else ['teacher_name', 'weekly_periods']
    result = []
    for key in keys:
        value = form[key]
        text = ('允许' if value else '不允许') if key == 'evening_study_allowed' else translations.get(str(value), str(value))
        result.append({'key': key, 'label': labels[key], 'value': text})
    return result


async def normalize_rows(session, tenant_id, rows, year, term, distribute, half_parity, clean_names, selected_class):
    classes = list((await session.execute(select(Class).where(Class.tenant_id == tenant_id,
        Class.academic_year == year, Class.term == term))).scalars().all())
    grades = {g.id: g.name for g in (await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all()}
    result, excluded = [], 0
    for original in rows:
        row = dict(original)
        if not row.get('teacher_totals'):
            if selected_class and not row.get('rule_type') and row.get('class') and row['class'] != selected_class:
                excluded += 1
                continue
            result.append(row)
            continue
        if not distribute:
            raise ValueError('教师表是多个班级的总课时，请明确勾选按班级均分，或使用标准模板填写每班真实课时')
        numbers = integers(row.get('class'), 100)
        if not numbers:
            raise ValueError(f"{row['source']}缺少所教班级")
        for number in numbers:
            matches = [c for c in classes if grades.get(c.grade_id, '').removesuffix('年级') == '高一'
                and re.sub(r'[（）()\s]', '', c.name) == f'高一{number}班']
            if selected_class and (not matches or all(c.name != selected_class for c in matches)):
                excluded += 1
                continue
            if len(matches) != 1:
                raise ValueError(f"{row['source']}的高一{number}班未唯一匹配，请先创建班级或选择已存在的目标班级")
            converted = {**row, 'class': matches[0].name, 'grade': grades[matches[0].grade_id], 'parity': '每周'}
            if clean_names:
                converted['teacher'] = re.sub(r'\s+', '', row.get('teacher', '').lstrip('*'))
            for key in ('weekday', 'saturday'):
                value = float(row.get(key) or 0) / len(numbers)
                if value % 0.5:
                    raise ValueError(f"{row['source']}均分后不是0.5的倍数，请改用标准模板")
                converted[key] = str(value)
                if value % 1:
                    if half_parity not in ('单周', '双周'):
                        raise ValueError('出现半课时，请明确0.5课时所在单周或双周')
                    converted['parity'] = half_parity
            evening = float(row.get('evening_total') or 0) / len(numbers)
            if evening not in (0, 0.5, 1):
                raise ValueError(f"{row['source']}每班晚课不是0、0.5或1，请填写标准模板")
            if evening == 0.5 and half_parity not in ('单周', '双周'):
                raise ValueError('半节晚课需明确单周或双周')
            converted['evening_odd'] = str(int(evening == 1 or (evening == 0.5 and half_parity == '单周')))
            converted['evening_even'] = str(int(evening == 1 or (evening == 0.5 and half_parity == '双周')))
            result.append(converted)
    if len(result) > 200:
        raise ValueError('展开后超过200行，请选择目标班级或拆分文件')
    return result, excluded


async def inspect_rule(session, tenant_id, form):
    from app.api.v1.scheduling import _load_rule_catalog
    from app.services.scheduling.rules import RuleGroupDocument, compile_rule_group
    group = RuleGroupDocument.model_validate(form['group'])
    grade = await session.get(Grade, group.grade_id)
    if not grade or grade.tenant_id != tenant_id:
        raise HTTPException(409, '规则年级已变更')
    groups, _ = await _load_rule_catalog(session, tenant_id, group.academic_year, group.term)
    from app.models.org import Subject, User
    for rule in group.rules:
        reference = form.get('references', {}).get(rule.id)
        if reference:
            model = {'teacher': User, 'subject': Subject, 'class': Class}[reference['type']]
            matches = list((await session.execute(select(model).where(model.tenant_id == tenant_id, model.name == reference['name']))).scalars().all())
            if len(matches) != 1:
                if model is Subject and not matches:
                    raise HTTPException(409, '请先完成依赖科目的创建')
                raise HTTPException(409, '规则对象名称已变更或重名')
            rule.target.ids = [matches[0].id]
            if model is User and (matches[0].status != 'active' or matches[0].frozen):
                raise HTTPException(409, '规则教师已停用或冻结，请重新解析')
    existing = next((g for g in groups if g.id == group.id), None)
    if existing and existing.model_dump(mode='json') == group.model_dump(mode='json'):
        return group, existing
    if (existing.model_dump(mode='json') if existing else None) != form['before']:
        raise HTTPException(409, '规则组在预览后已变更，请重新解析')
    # All referenced objects must still belong to this school.
    for rule in group.rules:
        model = {'teacher': User, 'subject': Subject, 'class': Class}.get(rule.target.type)
        if model:
            valid = list((await session.execute(select(model.id).where(model.tenant_id == tenant_id, model.id.in_(rule.target.ids)))).scalars().all())
            if set(valid) != set(rule.target.ids):
                raise HTTPException(409, '规则对象已变更')
    if any(r.status != 'ready' for r in compile_rule_group(group)):
        raise HTTPException(422, '包含无法执行的规则')
    return group, None


async def inspect(session, tenant_id, item):
    if item['kind'] == 'rule':
        return await inspect_rule(session, tenant_id, item['form'])
    return await inspect_item(session, tenant_id, item['kind'], item['form'])


@router.post('/preview')
async def preview(
    file: UploadFile = File(...), academic_year: str = Form(...), term: str = Form('1'),
    distribute: bool = Form(False), half_parity: str = Form(''), clean_names: bool = Form(False),
    selected_class: str = Form(''), default_type: str = Form(''), default_evening: str = Form(''),
    session: AsyncSession = Depends(get_session), user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    await authorize(session, user, tenant_id)
    if (not re.fullmatch(r'\d{4}-\d{4}', academic_year)
        or int(academic_year.split('-')[1]) != int(academic_year.split('-')[0]) + 1
        or term not in ('1', '2')):
        raise HTTPException(422, '请明确填写学年（如2026-2027）和学期1或2')
    content = await file.read(MAX_FILE_BYTES + 1)
    try:
        rows = read_rows(file.filename or '', content)
        rows, excluded = await normalize_rows(session, tenant_id, rows, academic_year, term, distribute, half_parity, clean_names, selected_class)
        defaults = {'允许': True, '不允许': False}
        items = await prepare_rows(session, tenant_id, rows, academic_year, term,
            {'学科课': 'subject', '活动课': 'activity'}.get(default_type), defaults.get(default_evening))
        items.extend(await prepare_rules(session, tenant_id, rows, academic_year, term,
            [i['form']['subject_name'] for i in items if i['kind'] == 'subject' and i['status'] == 'ready']))
    except (ValueError, TypeError, KeyError, OverflowError, BadZipFile, ParseError) as exc:
        raise HTTPException(422, str(exc)) from exc
    for index, item in enumerate(items):
        item['id'] = str(index + 1)
        if item['status'] == 'ready':
            try:
                _, existing = await inspect(session, tenant_id, item)
                if existing:
                    item.update(status='exists', message='已有相同配置，将跳过')
            except HTTPException as exc:
                # A new subject is an explicit dependency, resolved again at save.
                if exc.detail != '请先完成依赖科目的创建':
                    item.update(status='blocked', message=exc.detail)
            if item['status'] != 'blocked':
                item['fields'] = fields_for(item)
    school = await session.get(Tenant, tenant_id)
    plan = {'scope': 'excel-preview', 'tid': tenant_id, 'items': items, 'academic_year': academic_year,
            'term': term, 'file_hash': hashlib.sha256(content).hexdigest(), 'exp': int(time.time()) + 1800}
    return {'code': 0, 'data': {'items': items, 'excluded_rows': excluded, 'school_name': school.name,
        'academic_year': academic_year, 'term': term, 'plan_token': create_access_token(user.id, plan)}, 'message': '仅预览，尚未写入'}


class ConfirmIn(BaseModel):
    plan_token: str = Field(max_length=800000)
    confirmed: Literal[True]


@router.post('/confirm')
async def confirm(body: ConfirmIn, session: AsyncSession = Depends(get_session), user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant)):
    await authorize(session, user, tenant_id)
    plan = scoped_token(body.plan_token, 'excel-preview', user, tenant_id)
    if not plan['items'] or any(i['status'] == 'blocked' for i in plan['items']):
        raise HTTPException(409, '存在未解决项或无配置，不能执行；请修正后重新解析')
    items = []
    for original in plan['items']:
        item = dict(original)
        if item['status'] == 'ready':
            item['task_token'] = create_access_token(user.id, {'scope': 'page-agent-excel', 'tid': tenant_id,
                'item': item, 'file_hash': plan['file_hash'], 'exp': int(time.time()) + 7200})
        items.append(item)
    return {'code': 0, 'data': {'items': items}, 'message': '已二次确认，可以开始页面操作'}


class ItemIn(BaseModel):
    task_token: str = Field(max_length=150000)
    values: dict[str, str] = Field(default_factory=dict)


@router.post('/status')
async def item_status(body: ItemIn, session: AsyncSession = Depends(get_session), user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant)):
    await authorize(session, user, tenant_id)
    task = scoped_token(body.task_token, 'page-agent-excel', user, tenant_id)
    _, existing = await inspect(session, tenant_id, task['item'])
    return {'code': 0, 'data': {'saved': existing is not None}, 'message': 'ok'}


@router.post('/save')
async def save_item(body: ItemIn, session: AsyncSession = Depends(get_session), user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant)):
    await authorize(session, user, tenant_id)
    task = scoped_token(body.task_token, 'page-agent-excel', user, tenant_id)
    item = task['item']
    expected = {f['key']: f['value'] for f in fields_for(item)}
    if body.values != expected:
        raise HTTPException(422, '页面填写内容与二次确认内容不一致，未保存')
    await lock_tenant_write(session, tenant_id)
    validated, existing = await inspect(session, tenant_id, item)
    if existing:
        return {'code': 0, 'data': {'saved': True, 'skipped': True}, 'message': '已有相同配置，未重复创建'}
    from app.api.v1.scheduling import create_subject, upsert_course_hour, upsert_assignment, save_rule_group
    handler = {'subject': create_subject, 'hours': upsert_course_hour, 'assignment': upsert_assignment, 'rule': save_rule_group}[item['kind']]
    await handler(validated, session=session, user=user, tenant_id=tenant_id)
    return {'code': 0, 'data': {'saved': True, 'skipped': False}, 'message': '已保存'}
