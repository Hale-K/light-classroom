"""Read-only planning evidence and deterministic checks for temporary hour scenarios."""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select

from app.ai.tools.school.common import _term, _tool_response
from app.ai.tools.school.context import timetable_mode
from app.models.org import Class, CourseHourPlan, Grade, Subject, TeachingAssignment, Tenant
from app.models.gaokao import GaokaoScheme, TeachingClass, TeachingSubjectHourPlan, WalkSchedulingPlan, WalkSchedulingRoom, WalkSchedulingSlot
from app.services.scheduling.grid_slots import allowed_slots

Day = Annotated[int, Field(ge=1, le=7, strict=True)]
Period = Annotated[int, Field(ge=1, le=12, strict=True)]
Hours = Annotated[float, Field(ge=0, le=168, allow_inf_nan=False, strict=True)]


class PlanningScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    academic_year: str | None = Field(default=None, min_length=4, max_length=20)
    term: Literal['1', '2'] | None = None
    grade_id: int | None = Field(default=None, gt=0, strict=True)
    grade: str | None = Field(default=None, min_length=1, max_length=50)
    class_id: int | None = Field(default=None, gt=0, strict=True)
    class_name: str | None = Field(default=None, min_length=1, max_length=50)


class SubjectHours(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subject: str = Field(min_length=1, max_length=30)
    periods: Hours
    week_parity: Literal['all', 'odd', 'even'] = 'all'

    @field_validator('subject')
    @classmethod
    def clean_subject(cls, value):
        if not value.strip():
            raise ValueError('科目名不能为空')
        return value.strip()

    @field_validator('periods')
    @classmethod
    def half_period_steps(cls, value):
        if Decimal(str(value)) * 2 != (Decimal(str(value)) * 2).to_integral_value():
            raise ValueError('课时仅支持整数或半节，不能用任意比例小数直接排课')
        return value


class Scenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    subjects: list[SubjectHours] = Field(min_length=1, max_length=60)

    @model_validator(mode='after')
    def unique_subject_legs(self):
        keys = set()
        for row in self.subjects:
            for parity in ('odd', 'even') if row.week_parity == 'all' else (row.week_parity,):
                key = row.subject, parity
                if key in keys:
                    raise ValueError('同一科目同一周次不可重复；每周与单双周不可重叠')
                keys.add(key)
        return self


class ScenarioQuery(PlanningScope):
    weekdays: list[Day] = Field(default_factory=lambda: [1, 2, 3, 4, 5], min_length=1, max_length=7,
        description='方案内 periods 仅表示这些教学日的正式课时，默认周一到周五；周末或特殊课位须分别规划，不混加。')
    mandatory_periods: list[Period] = Field(default_factory=list, max_length=12,
        description='这些教学日每一天必须排满的节次，例如1至7；不填不验证必排下限。')
    optional_periods: list[Period] = Field(default_factory=list, max_length=12,
        description='每一天可排可不排的节次，例如8和9；两个节次集合均不填时使用所选教学日全部实际正式课位。')
    fixed_subject_hours: dict[str, Hours] = Field(default_factory=dict,
        description='用户已明确的每周固定课时，例如体育2音乐1心理1；每个方案单周双周均须满足。')
    scenarios: list[Scenario] = Field(min_length=1, max_length=3)

    @model_validator(mode='after')
    def check_roles(self):
        for values in (self.weekdays, self.mandatory_periods, self.optional_periods):
            if len(values) != len(set(values)):
                raise ValueError('星期和节次不可重复')
        if set(self.mandatory_periods) & set(self.optional_periods):
            raise ValueError('必排课位与可选课位不可重叠')
        if len({item.name for item in self.scenarios}) != len(self.scenarios):
            raise ValueError('方案名不可重复')
        if len(self.fixed_subject_hours) > 30 or any(not key.strip() or len(key) > 30 for key in self.fixed_subject_hours):
            raise ValueError('固定科目数量或名称无效')
        normalized = {key.strip(): value for key, value in self.fixed_subject_hours.items()}
        if len(normalized) != len(self.fixed_subject_hours):
            raise ValueError('固定科目不可重复')
        self.fixed_subject_hours = normalized
        return self


DESCRIPTIONS = {
    'lookup_planning_basis': '只读读取指定年级学期真实规划依据：年级课位结构与单双周实际可用节次、当前行政课时范围、任课缺口，走班模式额外返回科目默认课时与预留课位教室池。先调用本工具再生成多方案。学年学期和明确年级不可猜；未保存的默认课位不得称为已核实。选科方案与高考分值不同，本工具不提供已核实分值权重，需用户提供或可靠来源。',
    'validate_hour_scenarios': '只读程序验算1至3个临时课时方案：用真实年级单/双周课位核对各科合计、用户固定科目课时、指定教学日必排下限和可选上限。返回每方案错误与同日多节风险；不是全约束排课求解，不验证教师教室冲突，不修改数据。生成方案后必须调用，失败则只修正失败方案再验算。subjects.periods仅包含weekdays指定教学日正式课时。',
}
TOOLS = [{'type': 'function', 'function': {'name': name, 'description': description,
          'parameters': (PlanningScope if name == 'lookup_planning_basis' else ScenarioQuery).model_json_schema()}}
         for name, description in DESCRIPTIONS.items()]


async def _rows(session, model, *conditions):
    return list((await session.execute(select(model).where(*conditions))).scalars().all())


async def resolve_scope(session, tenant_id, query):
    """Resolve explicit tenant/term scope without inheriting a stale page class."""
    if not query.academic_year or not query.term:
        year, term = await _term(session, tenant_id)
        query = query.model_copy(update={'academic_year': query.academic_year or year, 'term': query.term or term})
    if not query.academic_year or query.term not in ('1', '2'):
        raise ValueError('请明确有效学年学期。')
    grades = await _rows(session, Grade, Grade.tenant_id == tenant_id)
    classes = await _rows(session, Class, Class.tenant_id == tenant_id,
        Class.academic_year == query.academic_year, Class.term == query.term)
    if query.class_name or query.class_id:
        matches = [item for item in classes if (query.class_id is None or item.id == query.class_id)
            and (not query.class_name or item.name == query.class_name.strip())
            and (query.grade_id is None or item.grade_id == query.grade_id)
            and (not query.grade or any(g.id == item.grade_id and query.grade.strip() in g.name for g in grades))]
        if len(matches) != 1:
            raise ValueError('未唯一匹配本校该学期的行政班，请明确年级及班级。')
        query = query.model_copy(update={'class_id': matches[0].id, 'grade_id': matches[0].grade_id})
    if query.grade_id is None and not query.grade:
        raise ValueError('请明确要规划的年级；不同年级的课位不可混用。')
    matches = [g for g in grades if (query.grade_id is None or g.id == query.grade_id)
        and (not query.grade or query.grade.strip() in g.name)]
    if len(matches) != 1:
        raise ValueError('本校年级未唯一匹配，请确认年级名称或ID。')
    grade = matches[0]
    query = query.model_copy(update={'grade_id': grade.id})
    classes = [item for item in classes if item.grade_id == grade.id and (query.class_id is None or item.id == query.class_id)]
    scope = {key: getattr(query, key) for key in ('academic_year', 'term', 'grade_id', 'class_id') if getattr(query, key) is not None}
    scope.update({'grade': grade.name, 'timetable_mode': await timetable_mode(session, tenant_id),
                  'mode_source': 'school_current_setting', 'historical_mode_verified': False})
    return query, scope, classes


def _grid_view(grid):
    daytime, evening = allowed_slots(grid, 'daytime'), allowed_slots(grid, 'evening')
    return {'configured': grid['configured'], 'source': 'grade_semester_grid',
        'daily_periods': grid['daily_periods'],
        'daytime_capacity_by_week': {leg: len(slots) for leg, slots in daytime.items()},
        'weekday_capacity_by_week': {leg: sum(day <= 5 for day, _ in slots) for leg, slots in daytime.items()},
        'weekend_capacity_by_week': {leg: sum(day >= 6 for day, _ in slots) for leg, slots in daytime.items()},
        'evening_capacity_by_week': {leg: len(slots) for leg, slots in evening.items()},
        'daytime_slots_by_week': {leg: [{'weekday': day, 'periods': sorted(p for d, p in slots if d == day)} for day in range(1, 8)] for leg, slots in daytime.items()},
        'evening_daily_periods_odd': grid['evening_daily_periods_odd'],
        'evening_daily_periods_even': grid['evening_daily_periods_even'],
        'first_week_parity': grid['first_week_parity'], 'term_start_monday': str(grid['term_start_monday']) if grid.get('term_start_monday') else None}


async def _basis(session, tenant_id, query, scope, classes, grid):
    subjects = {item.id: item.name for item in await _rows(session, Subject,
        (Subject.tenant_id == tenant_id) | Subject.tenant_id.is_(None))}
    class_ids = [item.id for item in classes]
    plans = await _rows(session, CourseHourPlan, CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.academic_year == query.academic_year, CourseHourPlan.term == query.term,
        CourseHourPlan.class_id.in_(class_ids))
    assignments = await _rows(session, TeachingAssignment, TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.academic_year == query.academic_year, TeachingAssignment.term == query.term,
        TeachingAssignment.class_id.in_(class_ids))
    by_class = {item.id: {'class_id': item.id, 'class_name': item.name,
        'daytime_periods_by_week': {'odd': 0.0, 'even': 0.0}, 'subjects': []} for item in classes}
    for row in plans:
        leg = getattr(row.week_parity, 'value', row.week_parity)
        for parity in ('odd', 'even') if leg == 'all' else (leg,):
            by_class[row.class_id]['daytime_periods_by_week'][parity] += row.weekday_periods + row.saturday_periods
        by_class[row.class_id]['subjects'].append({'subject': subjects.get(row.subject_id),
            'weekday_periods': row.weekday_periods, 'saturday_periods': row.saturday_periods,
            'week_parity': leg, 'evening_periods_odd': row.evening_periods_odd, 'evening_periods_even': row.evening_periods_even})
    pairs = {(row.class_id, row.subject_id) for row in assignments}
    missing = {(row.class_id, row.subject_id) for row in plans if row.weekday_periods + row.saturday_periods > 0} - pairs
    cohorts = {int(item.cohort_label) for item in classes if item.cohort_label and item.cohort_label.isdigit()}
    schemes = await _rows(session, GaokaoScheme, GaokaoScheme.tenant_id == tenant_id,
        GaokaoScheme.entry_year.in_(cohorts)) if cohorts else []
    school = (await _rows(session, Tenant, Tenant.id == tenant_id))
    policy = {'scope_verified': bool(cohorts), 'schemes': [{
        'name': scheme.name, 'entry_year': scheme.entry_year, 'mode': scheme.mode, 'is_active': scheme.is_active,
        'required_subjects': [subjects.get(sid, f'未知科目{sid}') for sid in scheme.required_subject_ids],
        'primary_subjects': [subjects.get(sid, f'未知科目{sid}') for sid in scheme.primary_subject_ids],
        'secondary_subjects': [subjects.get(sid, f'未知科目{sid}') for sid in scheme.secondary_subject_ids],
    } for scheme in schemes]}
    walk = {'applicable': scope['timetable_mode'] == 'walk_class'}
    if walk['applicable']:
        def conditions(model):
            return (model.tenant_id == tenant_id, model.grade_id == query.grade_id,
                    model.academic_year == query.academic_year, model.term == query.term)
        defaults = await _rows(session, TeachingSubjectHourPlan, *conditions(TeachingSubjectHourPlan))
        teaching_classes = await _rows(session, TeachingClass, *conditions(TeachingClass))
        pools = await _rows(session, WalkSchedulingPlan, *conditions(WalkSchedulingPlan))
        slots = await _rows(session, WalkSchedulingSlot, WalkSchedulingSlot.plan_id.in_([pool.id for pool in pools]))
        rooms = await _rows(session, WalkSchedulingRoom, WalkSchedulingRoom.plan_id.in_([pool.id for pool in pools]))
        walk.update({'scope': 'grade_semester', 'resource_pool_configured': bool(pools),
            'subject_hour_defaults': [{'subject': subjects.get(item.subject_id), 'weekly_periods': item.weekly_periods,
                'weekday_periods': item.weekday_periods, 'weekend_periods': item.weekend_periods} for item in defaults],
            'teaching_class_count': len(teaching_classes), 'overridden_class_count': sum(item.hours_overridden for item in teaching_classes),
            'teaching_class_hours': [{'class_id': item.id, 'class_name': item.name, 'subject': subjects.get(item.subject_id),
                'weekly_periods': item.weekly_periods, 'weekday_periods': item.weekday_periods,
                'weekend_periods': item.weekend_periods, 'hours_overridden': item.hours_overridden,
                'teacher_assigned': item.teacher_id is not None} for item in teaching_classes[:5]],
            'teaching_class_hours_truncated': len(teaching_classes) > 5,
            'reserved_slots': [{'weekday': item.weekday, 'period': item.period} for item in slots],
            'room_ids': sorted({item.room_id for item in rooms}),
            'joint_feasibility_verified': False})
    ranges = {leg: [item['daytime_periods_by_week'][leg] for item in by_class.values()] for leg in ('odd', 'even')}
    return {'grid': _grid_view(grid), 'class_count': len(classes),
        'current_hours': list(by_class.values())[:3], 'current_hours_truncated': len(classes) > 3,
        'current_hours_detail_message': '最多显示3个班配置详情；完整明细请用lookup_teaching_assignments分页核对。',
        'current_hours_range_by_week': {leg: {'minimum': min(values, default=0), 'maximum': max(values, default=0)} for leg, values in ranges.items()},
        'current_hours_source': 'configured_hour_plans_not_saved_timetable',
        'unplanned_class_count': sum(not item['subjects'] for item in by_class.values()),
        'missing_assignment_count': len(missing), 'unassigned_teacher_count': sum(row.teacher_id is None for row in assignments),
        'subjects': sorted(subjects.values()), 'walk_resources': walk, 'selection_policy': policy,
        'score_weights': {'verified': False, 'values': None, 'source': 'not_stored',
            'province': school[0].province if school else None,
            'message': '选科方案没有存储可核实高考分值权重。需用户明确提供权重或核对官方来源，不能把常识当作本届证据。'}}


def _validate_scenarios(query, grid, known_subjects):
    actual = allowed_slots(grid, 'daytime')
    requested_mandatory = {(day, period) for day in query.weekdays for period in query.mandatory_periods}
    chosen_periods = set(query.mandatory_periods) | set(query.optional_periods)
    slots = {leg: {(day, period) for day, period in available if day in query.weekdays
        and (not chosen_periods or period in chosen_periods)} for leg, available in actual.items()}
    required = {leg: len(requested_mandatory) for leg in actual}
    maximum = {leg: len(available) for leg, available in slots.items()}
    results = []
    for scenario in query.scenarios:
        values = {leg: defaultdict(Decimal) for leg in actual}
        for row in scenario.subjects:
            for leg in ('odd', 'even') if row.week_parity == 'all' else (row.week_parity,):
                values[leg][row.subject] += Decimal(str(row.periods))
        errors, risks = [], []
        unknown = set(row.subject for row in scenario.subjects) | set(query.fixed_subject_hours)
        for subject in sorted(unknown - known_subjects):
            errors.append({'code': 'UNKNOWN_SUBJECT', 'subject': subject})
        totals = {leg: sum(hours.values(), Decimal(0)) for leg, hours in values.items()}
        for leg, total in totals.items():
            if requested_mandatory - actual[leg]:
                errors.append({'code': 'MANDATORY_SLOT_UNAVAILABLE', 'week_parity': leg,
                    'slots': [list(item) for item in sorted(requested_mandatory - actual[leg])]})
            if total > maximum[leg]:
                errors.append({'code': 'CAPACITY_EXCEEDED', 'week_parity': leg, 'excess_periods': float(total - maximum[leg])})
            if total < required[leg]:
                errors.append({'code': 'MANDATORY_UNFILLED', 'week_parity': leg, 'missing_periods': float(required[leg] - total)})
            for subject, expected in query.fixed_subject_hours.items():
                if values[leg][subject] != Decimal(str(expected)):
                    errors.append({'code': 'FIXED_SUBJECT_MISMATCH', 'week_parity': leg,
                        'subject': subject, 'expected': expected, 'actual': float(values[leg][subject])})
            teaching_days = len({day for day, _ in slots[leg]})
            for subject, hours in values[leg].items():
                if hours > teaching_days:
                    risks.append({'code': 'SAME_DAY_MULTIPLE_LESSONS', 'week_parity': leg, 'subject': subject,
                        'message': '至少一天同科多节；不代表必须相邻连堂。'})
        results.append({'name': scenario.name, 'valid': not errors,
            'numeric_constraints_valid': not any(issue['code'] != 'UNKNOWN_SUBJECT' for issue in errors),
            'subject_catalog_valid': not any(issue['code'] == 'UNKNOWN_SUBJECT' for issue in errors),
            'subjects': [row.model_dump() for row in scenario.subjects],
            'total_periods_by_week': {leg: float(total) for leg, total in totals.items()},
            'remaining_periods_by_week': {leg: float(maximum[leg] - total) for leg, total in totals.items()},
            'errors': errors, 'risks': risks})
    return {'mandatory_capacity_by_week': required, 'maximum_capacity_by_week': maximum,
        'weekdays': query.weekdays, 'fixed_subject_hours': query.fixed_subject_hours,
        'scenarios': results, 'all_valid': all(item['valid'] for item in results),
        'all_numeric_constraints_valid': all(item['numeric_constraints_valid'] for item in results),
        'coverage': {'check': 'aggregate_daytime_capacity_and_user_constraints',
            'teacher_conflicts_verified': False, 'room_conflicts_verified': False,
            'mandatory_slot_placement_verified': False, 'all_rules_verified': False,
            'solver_feasibility_verified': False, 'saved': False}}


async def execute(name, arguments, *, session, tenant_id, page_context):
    try:
        raw = json.loads(arguments or '{}')
        if not isinstance(raw, dict):
            raise ValueError('参数必须为对象')
        context = page_context or {}
        for key in ('academic_year', 'term'):
            if key not in raw and context.get(key) is not None:
                raw[key] = context[key]
        if not any(key in raw for key in ('grade_id', 'grade', 'class_id', 'class_name')):
            for key in ('grade_id', 'class_id'):
                if context.get(key) is not None:
                    raw[key] = context[key]
        query = (PlanningScope if name == 'lookup_planning_basis' else ScenarioQuery).model_validate(raw)
    except (ValueError, ValidationError) as exc:
        return _tool_response(name, ok=False, code='INVALID_ARGUMENT', message=f'规划参数无效：{str(exc)[:500]}')
    try:
        query, scope, classes = await resolve_scope(session, tenant_id, query)
    except ValueError as exc:
        return _tool_response(name, ok=False, code='MISSING_SCOPE', message=str(exc))
    from app.api.v1.scheduling import _load_grid_config
    grid = await _load_grid_config(session, tenant_id, query.academic_year, query.term, grade_id=query.grade_id)
    if name == 'lookup_planning_basis':
        data = await _basis(session, tenant_id, query, scope, classes, grid)
        return _tool_response(name, scope=scope, data=data,
            message='已读取年级学期规划依据；单双周分列。未保存课位仅为系统默认值，不能视为真实容量。课时是配置值，不是已排课表；走班资源按年级展示。')
    if not grid['configured']:
        return _tool_response(name, ok=False, code='MISSING_DATA', scope=scope,
            message='该年级学期尚未保存课位结构，不能用默认网格宣称方案已通过验算。')
    subjects = await _rows(session, Subject, (Subject.tenant_id == tenant_id) | Subject.tenant_id.is_(None))
    data = _validate_scenarios(query, grid, {item.name for item in subjects})
    return _tool_response(name, scope=scope, data=data,
        message='已程序核对合计、容量及用户硬约束。numeric_constraints_valid与subject_catalog_valid分开：缺少科目可展示已验算临时建议，但不可说已可执行。valid也不代表教师教室冲突或全约束通过。未保存或修改数据。')
