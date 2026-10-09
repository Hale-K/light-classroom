"""Preserve checked quantities on failure without another model or tool call."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import json

from app.ai.agent.models import AssistantTurn
from app.ai.tools.markdown import format_markdown


def blocked_plan(plan: dict | None, reason: str) -> dict | None:
    if not plan:
        return None
    result = deepcopy(plan)
    for step in result.get('steps', []):
        if step.get('status') in {'pending', 'running'}:
            step.update(status='blocked', summary=reason)
    return result


def checked_partial(scope, message: str) -> dict | None:
    """Copy the last authorized validator result; never reuse a rejected draft."""
    evidence = getattr(scope, 'checked_hour_evidence', None)
    if not isinstance(evidence, dict):
        return None
    data = evidence.get('data') or {}
    scenarios = data.get('scenarios') or []
    if not scenarios or not data.get('all_numeric_constraints_valid'):
        return None
    if len(scenarios) > 3 or any(not item.get('numeric_constraints_valid') for item in scenarios):
        return None

    def quantity(value) -> str:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise ValueError('Invalid checked quantity')
        return format(number.normalize(), 'f')

    try:
        sections = []
        checked_scope = evidence.get('scope') or {}
        scope_rows = [[label, str(checked_scope[key])] for key, label in (
            ('grade_name', '年级'), ('academic_year', '学年'), ('term', '学期'),
        ) if checked_scope.get(key) is not None]
        if scope_rows:
            sections.append({'type': 'table', 'title': '已查询范围',
                'columns': ['项目', '范围'], 'rows': scope_rows})
        missing = set()
        for scenario in scenarios:
            values: dict[str, dict[str, Decimal]] = {}
            for item in scenario['subjects']:
                subject = values.setdefault(item['subject'], {'odd': Decimal(0), 'even': Decimal(0)})
                parity = item.get('week_parity', 'all')
                for leg in ('odd', 'even') if parity == 'all' else (parity,):
                    subject[leg] += Decimal(quantity(item['periods']))
            totals = {leg: sum((item[leg] for item in values.values()), Decimal(0)) for leg in ('odd', 'even')}
            if any(totals[leg] != Decimal(quantity(scenario['total_periods_by_week'][leg])) for leg in totals):
                return None
            rows = [[subject, quantity(hours['odd']), quantity(hours['even'])] for subject, hours in values.items()]
            rows.append(['合计', quantity(totals['odd']), quantity(totals['even'])])
            sections.append({'type': 'table', 'title': scenario['name'] + '（数值验算记录，未实施）',
                'columns': ['科目', '单周课时', '双周课时'], 'rows': rows})
            missing.update(issue['subject'] for issue in scenario.get('errors', []) if issue.get('code') == 'UNKNOWN_SUBJECT')
        sections.append({'type': 'paragraph', 'title': '尚未完成', 'text':
            '以上只保留已通过程序验算的课量，最终规划未完成。教师与教室冲突、必排课位实际排满、完整规则和求解可行性仍待验证；未保存或修改业务数据。'})
        if missing:
            sections.append({'type': 'paragraph', 'text': '科目目录缺失：' + '、'.join(sorted(missing))
                + '。保留所列课时作为待实施记录，不能直接排课。'})
        formatted = json.loads(format_markdown(json.dumps({'summary': '任务未完成：' + message
            + ' 以下保留本轮已经取得的数值验算结果。', 'sections': sections}, ensure_ascii=False)))
        if not formatted.get('ok'):
            return None
        from dataclasses import asdict
        return asdict(AssistantTurn(text=formatted['data']['markdown'], model_visible=False))
    except (ValueError, KeyError, TypeError):
        return None
