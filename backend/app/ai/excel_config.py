"""Bounded Excel planning and exact, tenant-bound form contracts for Page Agent."""
from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation
from pathlib import PurePath
from zipfile import ZipFile

from fastapi import HTTPException
from sqlalchemy import select

from app.models.org import Class, Subject, User, CourseHourPlan, TeachingAssignment, Grade

MAX_ROWS = 200
MAX_FILE_BYTES = 5 * 1024 * 1024
HEADERS = {
    '科目': 'subject', '学科': 'subject', '科目名称': 'subject', '课程名称': 'subject',
    '班级': 'class', '行政班': 'class', '班级名称': 'class', '年级': 'grade',
    '教师': 'teacher', '任课教师': 'teacher', '教师姓名': 'teacher', '老师': 'teacher',
    '周课时': 'weekly', '每周课时': 'weekly', '周课时数': 'weekly', '课时': 'weekly',
    '工作日课时': 'weekday', '周末课时': 'saturday', '周六课时': 'saturday',
    '课程类型': 'course_type', '科目类型': 'course_type', '晚自习资格': 'evening',
    '允许晚自习': 'evening', '单双周': 'parity', '周类型': 'parity',
    '单周晚课': 'evening_odd', '双周晚课': 'evening_even',
    '姓名': 'teacher', '所教班级': 'class', '周一到周五课时': 'weekday',
    '周一到周六晚课课时': 'evening_total',
    '规则类型': 'rule_type', '适用对象类型': 'target_type', '适用对象名称': 'target_name',
    '星期': 'weekdays', '节次': 'periods', '数量': 'quantity', '约束强度': 'priority',
    '规则说明': 'description', '每周次数': 'minimum_days',
}


def read_rows(filename: str, content: bytes) -> list[dict]:
    suffix = PurePath(filename).suffix.lower()
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('文件为空或超过5 MB')
    sheets = []
    if suffix == '.xlsx':
        from openpyxl import load_workbook
        with ZipFile(io.BytesIO(content)) as archive:
            if len(archive.infolist()) > 1000 or sum(item.file_size for item in archive.infolist()) > 30 * 1024 * 1024:
                raise ValueError('Excel 解压体积过大')
        workbook = load_workbook(io.BytesIO(content), read_only=False, data_only=False)
        try:
            if len(workbook.worksheets) > 10:
                raise ValueError('最多处理10个工作表')
            for sheet in workbook.worksheets:
                if sheet.title in ('填写说明', '示例_请勿导入'):
                    continue
                if sheet.max_column > 30:
                    raise ValueError(f'「{sheet.title}」超过30列，请使用标准模板')
                # Expand only genuine merged cells, never fill arbitrary blanks.
                if sheet.max_row > MAX_ROWS + 10:
                    raise ValueError('工作表过大，请拆分为每批最多200行')
                for merged in list(sheet.merged_cells.ranges):
                    value = sheet.cell(merged.min_row, merged.min_col).value
                    sheet.unmerge_cells(str(merged))
                    for cells in sheet.iter_rows(min_row=merged.min_row, max_row=merged.max_row,
                                                 min_col=merged.min_col, max_col=merged.max_col):
                        for cell in cells:
                            cell.value = value
                sheets.append((sheet.title, list(sheet.iter_rows(max_row=sheet.max_row, max_col=sheet.max_column, values_only=True))))
        finally:
            workbook.close()
    elif suffix == '.csv':
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = content.decode('gb18030')
        sheets = [('CSV', list(csv.reader(io.StringIO(text))))]
    else:
        raise ValueError('请使用 .xlsx 或 .csv；旧版 .xls 请先另存为 .xlsx')
    result = []
    for title, rows in sheets:
        if any(len(row) > 30 for row in rows):
            raise ValueError(f'「{title}」超过30列，请使用标准模板')
        if not any(any(cell is not None and str(cell).strip() for cell in row) for row in rows):
            continue
        headers = None
        teacher_totals = False
        for row_number, row in enumerate(rows, 1):
            labels = [re.sub(r'\s+', '', str(cell or '')) for cell in row]
            mapping = {index: HEADERS[label] for index, label in enumerate(labels) if label in HEADERS}
            if headers is None:
                if 'subject' in mapping.values() or 'rule_type' in mapping.values():
                    if len(set(mapping.values())) != len(mapping):
                        raise ValueError(f'「{title}」第{row_number}行存在重复列含义')
                    headers = mapping
                    teacher_totals = '所教班级' in labels and '周一到周五课时' in labels
                elif row_number >= 10:
                    raise ValueError(f'「{title}」未找到科目列，请使用模板表头')
                continue
            values = {key: str(row[index] if index < len(row) and row[index] is not None else '').strip()
                      for index, key in headers.items()}
            if not any(values.values()):
                continue
            if any(value.startswith('=') for value in values.values()):
                raise ValueError(f'「{title}」第{row_number}行包含公式，请粘贴为数值后上传')
            result.append({'source': f'{title} · 第{row_number}行', 'sheet': title,
                           'teacher_totals': teacher_totals, **values})
            if len(result) > MAX_ROWS:
                raise ValueError('每批最多200行，请拆分文件；不会静默截断导入')
        if headers is None and any(any(cell is not None and str(cell).strip() for cell in row) for row in rows):
            raise ValueError(f'「{title}」未找到科目列，请使用模板表头')
    if not result:
        raise ValueError('未识别到数据行，请使用科目、班级、教师、周课时等表头')
    return result


def number(value: str, label: str, maximum=20) -> float:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f'{label}需要填写数字') from exc
    if not result.is_finite() or result < 0 or result > maximum or result % Decimal('0.5'):
        raise ValueError(f'{label}需为0～{maximum}，以0.5为步长')
    return float(result)


def boolean(value: str) -> bool:
    if value in ('允许', '是', 'true', 'True', '1'):
        return True
    if value in ('不允许', '否', 'false', 'False', '0'):
        return False
    raise ValueError('晚自习资格需填写允许或不允许')


async def prepare_rows(session, tenant_id, rows, year, term, default_type=None, default_evening=None):
    from app.api.v1.scheduling import CourseHourIn
    subjects = list((await session.execute(select(Subject).where(Subject.tenant_id == tenant_id))).scalars().all())
    classes = list((await session.execute(select(Class).where(Class.tenant_id == tenant_id,
        Class.academic_year == year, Class.term == term))).scalars().all())
    teachers = list((await session.execute(select(User).where(User.tenant_id == tenant_id,
        User.role.in_(['teacher', 'director']), User.status == 'active', User.frozen.is_(False)))).scalars().all())
    grades = {item.id: item.name for item in (await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all()}
    items, planned_subjects, seen = [], {}, {}

    def add(kind, form, source, problem=None):
        key = (kind, form.get('subject_name'), form.get('class_id'), form.get('week_parity', 'all'))
        if key in seen:
            previous = seen[key]
            if previous['form'] != form:
                previous.update(status='blocked', message='同一对象在Excel中出现相互冲突的配置')
                problem = '同一对象在Excel中出现相互冲突的配置'
            else:
                return
        item = {'id': str(len(items) + 1), 'kind': kind, 'source': source, 'form': form,
                'status': 'blocked' if problem else 'ready', 'message': problem or '待页面执行'}
        seen[key] = item
        items.append(item)

    # Resolve the whole subject list before creating dependent rows.
    for row in sorted(rows, key=lambda r: not (r.get('course_type') and r.get('evening'))):
        if row.get('rule_type'):
            continue
        name = row.get('subject', '')
        try:
            if not name or len(name) > 20:
                raise ValueError('科目名称需为1～20个字')
            matched = [item for item in subjects if item.name == name]
            if len(matched) > 1:
                raise ValueError('科目重名，请先在科目管理中处理')
            if matched:
                if row.get('course_type') and row['course_type'] not in (
                    matched[0].course_type, '学科课' if matched[0].course_type == 'subject' else '活动课'):
                    raise ValueError('已有科目类型与Excel不一致，不会自动修改')
                if row.get('evening') and boolean(row['evening']) != bool(matched[0].evening_study_allowed):
                    raise ValueError('已有科目晚自习资格与Excel不一致，不会自动修改')
                planned_subjects[name] = matched[0]
                continue
            approved = planned_subjects.get(name)
            course_type = {'学科课': 'subject', '活动课': 'activity'}.get(row.get('course_type'),
                row.get('course_type') or (approved.get('course_type') if isinstance(approved, dict) else default_type))
            evening = boolean(row['evening']) if row.get('evening') else (
                approved.get('evening_study_allowed') if isinstance(approved, dict) else default_evening)
            if course_type not in ('subject', 'activity') or evening is None:
                raise ValueError('新科目缺少课程类型或晚自习资格，请补充列或选择缺列默认值')
            form = {'subject_name': name, 'course_type': course_type, 'evening_study_allowed': evening}
            add('subject', form, row['source'])
            planned_subjects[name] = form
        except ValueError as exc:
            add('subject', {'subject_name': name}, row['source'], str(exc))
            planned_subjects.pop(name, None)

    for row in rows:
        if row.get('rule_type'):
            continue
        if not any(row.get(key) for key in ('class', 'teacher', 'weekly', 'weekday', 'saturday')):
            continue
        name = row.get('subject', '')
        base = {'subject_name': name, 'academic_year': year, 'term': term}
        try:
            if name not in planned_subjects or any(i['kind'] == 'subject' and i['form'].get('subject_name') == name and i['status'] == 'blocked' for i in items):
                raise ValueError('科目未匹配或存在冲突，请先修正科目数据')
            matching = [item for item in classes if item.name == row.get('class')
                and (not row.get('grade') or grades.get(item.grade_id) == row['grade']
                     or grades.get(item.grade_id, '').removesuffix('年级') == row['grade'])]
            if len(matching) != 1:
                raise ValueError('班级未唯一匹配当前学期，请补充完整班级名和年级；不会自动创建班级')
            base.update(class_id=matching[0].id, class_name=matching[0].name)
            if row.get('teacher') and not any(row.get(key) for key in ('weekly', 'weekday', 'saturday')):
                hour_rows = [r for r in rows if r.get('class') == row.get('class') and r.get('subject') == name
                             and any(r.get(key) for key in ('weekly', 'weekday', 'saturday'))]
                if len(hour_rows) != 1:
                    raise ValueError('任课关系需有唯一对应班级课时行，请填写班级课时工作表')
                row = {**hour_rows[0], **{k: v for k, v in row.items() if v not in ('', None)}}
            saturday = number(row.get('saturday') or '0', '周末课时', 10)
            if row.get('weekday'):
                weekday = number(row['weekday'], '工作日课时')
                if row.get('weekly') and number(row['weekly'], '周课时') != weekday + saturday:
                    raise ValueError('周课时不等于工作日课时与周末课时之和')
            else:
                weekday = number(row.get('weekly') or '', '周课时') - saturday
            if weekday + saturday > 20:
                raise ValueError('工作日加周六课时合计不能超过20')
            parity = {'每周': 'all', '单周': 'odd', '双周': 'even'}.get(row.get('parity'), row.get('parity') or 'all')
            odd = number(row.get('evening_odd') or '0', '单周晚课', 1)
            even = number(row.get('evening_even') or '0', '双周晚课', 1)
            if odd % 1 or even % 1:
                raise ValueError('晚课额度需为0或1')
            existing_subject = planned_subjects[name]
            evening_allowed = (existing_subject.get('evening_study_allowed') if isinstance(existing_subject, dict)
                               else existing_subject.evening_study_allowed)
            if (odd or even) and not evening_allowed:
                raise ValueError('该科目当前不允许晚自习，与Excel晚课要求冲突；请先明确修改科目资格，再重新解析')
            validated = CourseHourIn(class_id=base['class_id'], subject_id=1, academic_year=year, term=term,
                weekday_periods=weekday, saturday_periods=saturday, week_parity=parity,
                evening_periods_odd=int(odd), evening_periods_even=int(even))
            hours = {**base, **validated.model_dump(mode='json', exclude={'id', 'class_id', 'subject_id', 'academic_year', 'term'})}
            add('hours', hours, row['source'])
            if row.get('teacher'):
                matching_teachers = [item for item in teachers if item.name == row['teacher'] or item.phone == row['teacher']]
                if len(matching_teachers) != 1:
                    raise ValueError('教师未唯一匹配，请使用现有教师姓名或登录账号；不会自动创建账号')
                add('assignment', {**base, 'teacher_id': matching_teachers[0].id,
                    'teacher_name': matching_teachers[0].name, 'weekly_periods': validated.weekly_periods}, row['source'])
        except ValueError as exc:
            add('assignment' if row.get('teacher') else 'hours', base, row['source'], str(exc))
    items.sort(key=lambda item: {'subject': 0, 'hours': 1, 'assignment': 2}[item['kind']])
    return items


async def inspect_item(session, tenant_id, kind, form):
    """Re-resolve dependencies and detect existing/conflicting writes every time."""
    from app.api.v1.scheduling import CourseHourIn, AssignmentIn, SubjectIn
    subject_rows = list((await session.execute(select(Subject).where(Subject.tenant_id == tenant_id,
        Subject.name == form['subject_name']))).scalars().all())
    if len(subject_rows) > 1:
        raise HTTPException(409, '科目重名，请先处理')
    subject = subject_rows[0] if subject_rows else None
    if kind == 'subject':
        body = SubjectIn(name=form['subject_name'], course_type=form['course_type'], evening_study_allowed=form['evening_study_allowed'])
        if subject and (subject.course_type != body.course_type or bool(subject.evening_study_allowed) != body.evening_study_allowed):
            raise HTTPException(409, '已有科目配置不同，不会覆盖')
        return body, subject
    if not subject:
        raise HTTPException(409, '请先完成依赖科目的创建')
    classroom = await session.get(Class, form['class_id'])
    if not classroom or classroom.tenant_id != tenant_id or classroom.name != form['class_name'] or (
        classroom.academic_year, classroom.term) != (form['academic_year'], form['term']):
        raise HTTPException(409, '班级或学期已变更，请重新解析Excel')
    scope = {key: form[key] for key in ('class_id', 'academic_year', 'term')}
    scope['subject_id'] = subject.id
    if kind == 'hours':
        body = CourseHourIn(**scope, **{key: form[key] for key in ('weekly_periods', 'weekday_periods',
            'saturday_periods', 'week_parity', 'evening_periods_odd', 'evening_periods_even', 'evening_parity')})
        existing = list((await session.execute(select(CourseHourPlan).where(
            CourseHourPlan.tenant_id == tenant_id, *[getattr(CourseHourPlan, key) == value for key, value in scope.items()]))).scalars().all())
        if any((item.week_parity == 'all') != (body.week_parity == 'all') for item in existing):
            raise HTTPException(409, '已有每周与单双周方案冲突，不会自动覆盖')
        existing = [item for item in existing if item.week_parity == body.week_parity]
        fields = ('weekly_periods', 'weekday_periods', 'saturday_periods', 'week_parity',
                  'evening_periods_odd', 'evening_periods_even', 'evening_parity')
        same = [item for item in existing if all(getattr(item, key) == getattr(body, key) for key in fields)]
    else:
        teacher = await session.get(User, form['teacher_id'])
        if not teacher or teacher.tenant_id != tenant_id or teacher.status != 'active' or teacher.frozen or teacher.name != form['teacher_name']:
            raise HTTPException(409, '教师状态已变更，请重新解析Excel')
        body = AssignmentIn(**scope, teacher_id=teacher.id, weekly_periods=form['weekly_periods'])
        existing = list((await session.execute(select(TeachingAssignment).where(
            TeachingAssignment.tenant_id == tenant_id, *[getattr(TeachingAssignment, key) == value for key, value in scope.items()]))).scalars().all())
        same = [item for item in existing if item.teacher_id == body.teacher_id and item.weekly_periods == body.weekly_periods]
    if existing and (len(existing) != 1 or not same):
        raise HTTPException(409, '已有课时或任课关系与Excel不同，不会自动覆盖，请先人工处理')
    return body, same[0] if same else None
