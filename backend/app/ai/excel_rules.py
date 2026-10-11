"""Deterministic template rules: unsupported prose remains a visible blocker."""
import hashlib
import json
import re
from types import SimpleNamespace

from sqlalchemy import select
from app.models.org import Class, Grade, Subject, User
from app.services.scheduling.rules import RuleDefinition, RuleGroupDocument, compile_rule_group


def integers(value, maximum, weekdays=False):
    text = str(value or '').strip()
    if weekdays:
        for label, index in [('周一', 1), ('周二', 2), ('周三', 3), ('周四', 4), ('周五', 5), ('周六', 6), ('周日', 7), ('周天', 7)]:
            text = text.replace(label, str(index))
    result = set()
    for part in re.split(r'[、,，\s]+', text):
        if not part:
            continue
        if re.fullmatch(r'\d+-\d+', part):
            first, last = map(int, part.split('-'))
            if first > last or first < 1 or last > maximum:
                raise ValueError('范围无效')
            result.update(range(first, last + 1))
        elif part.isdigit() and 1 <= int(part) <= maximum:
            result.add(int(part))
        else:
            raise ValueError('时间需使用周一至周日或数字，节次支持1、2和1-3')
    return sorted(result)


async def prepare_rules(session, tenant_id, rows, year, term, new_subject_names=()):
    from app.api.v1.scheduling import _load_rule_catalog
    groups, _ = await _load_rule_catalog(session, tenant_id, year, term)
    grades = list((await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars().all())
    subjects = list((await session.execute(select(Subject).where(Subject.tenant_id == tenant_id))).scalars().all())
    for index, name in enumerate(sorted(set(new_subject_names))):
        if all(s.name != name for s in subjects):
            subjects.append(SimpleNamespace(id=2147480000 + index, name=name))
    teachers = list((await session.execute(select(User).where(User.tenant_id == tenant_id, User.status == 'active', User.frozen.is_(False)))).scalars().all())
    classes = list((await session.execute(select(Class).where(Class.tenant_id == tenant_id, Class.academic_year == year, Class.term == term))).scalars().all())
    items, assembled = [], {}
    references = {}
    for row in rows:
        if not row.get('rule_type'):
            continue
        try:
            grade_matches = [g for g in grades if g.name == row.get('grade') or g.name.removesuffix('年级') == row.get('grade')]
            if len(grade_matches) != 1:
                raise ValueError('规则需填写唯一年级，避免无意应用到全校')
            grade = grade_matches[0]
            if row.get('class'):
                raise ValueError('当前规则导入按年级生效；填写了班级的规则需在规则工作台人工配置，不能忽略班级范围')
            target_type = {'教师': 'teacher', '科目': 'subject', '班级': 'class'}.get(row.get('target_type'))
            choices = {'teacher': teachers, 'subject': subjects, 'class': [c for c in classes if c.grade_id == grade.id]}.get(target_type, [])
            targets = [v for v in choices if v.name == row.get('target_name') or (target_type == 'teacher' and v.phone == row.get('target_name'))]
            if len(targets) != 1:
                raise ValueError('规则适用对象需唯一匹配已有名称；新增科目请先完成创建后重新解析规则')
            priority = {'必须满足': 'hard', '尽量满足': 'soft'}.get(row.get('priority'))
            if not priority:
                raise ValueError('请明确规则是必须满足还是尽量满足')
            kind = row['rule_type']
            code, params = '', {}
            days = integers(row.get('weekdays'), 7, True)
            periods = integers(row.get('periods'), 12)
            if kind in ('教师禁排', '科目禁排'):
                expected = 'teacher' if kind == '教师禁排' else 'subject'
                if target_type != expected:
                    raise ValueError('禁排规则类型与对象类型不一致')
                code = 'slot_forbidden'
            elif kind == '每天课时上限':
                code = 'teacher_daily_limit'
                params = {'max_lessons_per_day': int(row.get('quantity', ''))}
            elif kind == '连堂':
                code = 'subject_consecutive' if target_type == 'subject' else 'teacher_consecutive'
                if not row.get('minimum_days'):
                    raise ValueError('连堂需填写每周次数；不会从文字说明猜测次数')
                params = {'minimum_block_length': int(row.get('quantity', '')), 'minimum_days': int(row['minimum_days'])}
            elif kind == '固定课节':
                # The solver supports subject slot patterns with explicit counts.
                if target_type != 'subject' or len(days) != 1 or len(periods) != 1 or priority != 'hard':
                    raise ValueError('固定课节需为科目、一个星期一个节次、必须满足')
                code = 'class_slot_pattern'
                params = {'alternatives': [[{'weekdays': days, 'periods': periods, 'count': 1}]]}
                days, periods = [], []
            else:
                raise ValueError('该规则类型尚不能自动转换，请使用规则工作台；文字说明不会当作已生效规则')
            rule_data = dict(title=row.get('description') or kind, code=code, priority=priority,
                schedule_scope='admin', rule_scope='individual', target={'type': target_type, 'ids': [targets[0].id]},
                weekdays=days, periods=periods, params=params)
            fingerprint = {**rule_data, 'target': {'type': target_type, 'name': targets[0].name}}
            rule_id = 'EX-' + hashlib.sha256(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
            rule = RuleDefinition(id=rule_id, **rule_data)
            group_id = f'excel-config-{grade.id}'
            if group_id not in assembled:
                existing = next((g for g in groups if g.id == group_id), None)
                group = existing.model_copy(deep=True) if existing else RuleGroupDocument(id=group_id, name=f'{grade.name} Excel配置规则', academic_year=year, term=term, grade_id=grade.id)
                assembled[group_id] = (group, existing.model_dump(mode='json') if existing else None, [])
            group, before, sources = assembled[group_id]
            references[rule_id] = {'type': target_type, 'name': targets[0].name}
            if all(r.id != rule.id for r in group.rules):
                group.rules.append(rule)
            sources.append(row['source'])
            compiled = compile_rule_group(group)
            invalid = [r for r in compiled if r.status != 'ready']
            if invalid:
                raise ValueError(invalid[-1].reason or '规则无法编译')
        except (ValueError, TypeError) as exc:
            items.append({'id': 'rule-' + str(len(items)), 'kind': 'rule', 'source': row['source'],
                          'form': {'rule_name': row.get('description') or row.get('rule_type')}, 'status': 'blocked', 'message': str(exc)})
    for group, before, sources in assembled.values():
        if any(r.status != 'ready' for r in compile_rule_group(group)):
            continue
        items.append({'id': group.id, 'kind': 'rule', 'source': '；'.join(sources),
                      'form': {'group': group.model_dump(mode='json'), 'before': before,
                               'references': {r.id: references[r.id] for r in group.rules if r.id in references}},
                      'status': 'ready', 'message': '新增到Excel规则组并设为该学期当前规则组；原有规则组保留'})
    return items
