"""Arithmetic for proposed classes and staffing; never reads current inventory."""
from decimal import Decimal, ROUND_CEILING
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ai.tools.school.common import _tool_response


class StaffingSubject(BaseModel):
    model_config = ConfigDict(extra='forbid')
    subject: str = Field(min_length=1, max_length=30)
    weekly_periods: float = Field(gt=0, le=100, allow_inf_nan=False)
    teacher_weekly_periods: float = Field(gt=0, le=100, allow_inf_nan=False)
    week_parity: Literal['all', 'odd', 'even'] = Field(default='all',
        description='all每周，odd单周，even双周；weekly_periods填开课周实际节数，隔周1节填1而非0.5。')


class ResourcePlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    student_count: int = Field(gt=0, le=100000, strict=True)
    minimum_class_size: int = Field(gt=0, le=1000, strict=True)
    maximum_class_size: int = Field(gt=0, le=1000, strict=True)
    preferred_class_count: int | None = Field(default=None, gt=0, strict=True)
    subjects: list[StaffingSubject] = Field(default_factory=list, max_length=30)
    basis: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def validate_sizes(self):
        if self.minimum_class_size > self.maximum_class_size:
            raise ValueError('班额下限不能大于上限')
        names = [s.subject.strip() for s in self.subjects]
        if len(names) != len(set(names)):
            raise ValueError('科目不能重复')
        return self


def calculate_resource_plan(arguments: str) -> str:
    try:
        q = ResourcePlan.model_validate_json(arguments)
    except ValidationError:
        return _tool_response('calculate_resource_plan', ok=False, code='INVALID_ARGUMENT',
            message='请提供正整数学生数、班额范围，以及课时和教师周工作量的来源或假设；科目不能重复。')
    low = (q.student_count + q.maximum_class_size - 1) // q.maximum_class_size
    high = q.student_count // q.minimum_class_size
    if low > high:
        return _tool_response('calculate_resource_plan', ok=False, code='INFEASIBLE_CLASS_SIZE',
            message='该人数无法在指定班额上下限内分班，请调整班额范围。')
    selected = q.preferred_class_count or low
    if not low <= selected <= high:
        return _tool_response('calculate_resource_plan', ok=False, code='INVALID_CLASS_COUNT',
            message=f'可行班级数为{low}至{high}个，请在此范围内选择。')
    def distribution(count):
        size, extra = divmod(q.student_count, count)
        return {'class_count': count, 'rooms_required': count,
                'distribution': [{'class_size': size, 'classes': count - extra}]
                    + ([{'class_size': size + 1, 'classes': extra}] if extra else [])}
    teachers = []
    totals = {'odd': Decimal(0), 'even': Decimal(0)}
    for subject in q.subjects:
        total = Decimal(str(subject.weekly_periods)) * selected
        workload = Decimal(str(subject.teacher_weekly_periods))
        count = int((total / workload).to_integral_value(rounding=ROUND_CEILING))
        by_week = {leg: subject.weekly_periods if subject.week_parity in ('all', leg) else 0 for leg in totals}
        for leg, hours in by_week.items():
            totals[leg] += Decimal(str(hours))
        teachers.append({'subject': subject.subject.strip(), 'weekly_periods_per_class': subject.weekly_periods,
            'total_weekly_periods': float(total), 'teacher_weekly_periods': subject.teacher_weekly_periods,
            'week_parity': subject.week_parity, 'periods_per_class_by_week': by_week,
            'average_weekly_periods_per_class': sum(by_week.values()) / 2,
            'teachers_required': count})
    return _tool_response('calculate_resource_plan', message='已按输入人数、班额和课时假设验算；不是学校现有资源统计。',
        scope={'source': 'proposed_plan', 'basis': q.basis}, data={
            'student_count': q.student_count, 'minimum_classes': low, 'maximum_classes': high,
            'class_options': [distribution(n) for n in range(low, min(high, low + 19) + 1)],
            'options_truncated': high - low >= 20, 'selected': distribution(selected),
            'subjects': teachers, 'teachers_required': sum(s['teachers_required'] for s in teachers) if teachers else None,
            'weekly_periods_per_class': float(sum(totals.values()) / 2),
            'periods_per_class_by_week': {leg: float(value) for leg, value in totals.items()},
            'missing_data': [] if teachers else ['各科每班周课时', '各科教师周授课量'],
            'limitations': ['按行政班一班一室估算；走班需另核对教学班和同时使用量',
                '教师按各科开课周峰值向上取整；隔周课程不能用平均课时替代峰值，未考虑跨科兼任、同时排课冲突、代课储备',
                '专用教室与体育场地需按同时开课数另算', '仅覆盖所列科目，不代表完整课程方案']})


TOOL = {'type': 'function', 'function': {
    'name': 'calculate_resource_plan',
    'description': '根据用户提供的学生人数和班额范围计算班级/普通教室数；按明确的科目周课时、教师周工作量假设逐科计算师资并向上取整。隔周用week_parity标记，weekly_periods填写开课周实际节数，教师按峰值计算。用于需要多少的规划，不查询学校现有数量。缺课时可先仅计算班级，不能编造来源。',
    'parameters': ResourcePlan.model_json_schema(),
}}
