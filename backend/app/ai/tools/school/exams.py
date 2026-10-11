"""Tenant-scoped read-only exam evidence; shares the product's real checks."""
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, func

from app.ai.tools.school.common import _tool_response
from app.models.exam import (Exam, ExamSchedule, ExamSchedulingConfig, ExamVenue,
    ExamRoomAssignment, ExamCandidateAssignment, ExamInvigilatorAvailability)
from app.models.org import Grade, Subject, User
from app.services.exam_operations import check_plan

NAME = 'lookup_exam_operations'


class ExamCapacity(BaseModel):
    model_config = ConfigDict(extra='forbid')
    simultaneous_candidates: int = Field(gt=0, le=100000, strict=True,
        description='同一考试时段的去重参考人数，不能填全校人数或累计考生场次代替。')
    usable_seats_per_room: int = Field(gt=0, le=500, strict=True,
        description='应用本次考试座位规则后的每间可用座位数，不能直接用教室班额代替。')
    invigilators_per_room: int = Field(gt=0, le=3, strict=True)
    basis: str = Field(min_length=1, max_length=500)


def calculate_capacity(arguments):
    try:
        q = ExamCapacity.model_validate_json(arguments)
    except ValidationError:
        return _tool_response('calculate_exam_capacity', message='请明确同场参考人数、考试可用座位数、每场监考人数和依据。',
                              ok=False, code='INVALID_ARGUMENT')
    rooms = (q.simultaneous_candidates + q.usable_seats_per_room - 1) // q.usable_seats_per_room
    return _tool_response('calculate_exam_capacity', message='已按同场人数验算峰值考场和监考需求。',
        scope={'source':'proposed_exam_plan','basis':q.basis}, data={
            'simultaneous_candidates': q.simultaneous_candidates, 'rooms_required': rooms,
            'usable_seats_per_room': q.usable_seats_per_room,
            'invigilators_per_room': q.invigilators_per_room,
            'simultaneous_invigilators_required': rooms * q.invigilators_per_room,
            'unused_seats': rooms * q.usable_seats_per_room - q.simultaneous_candidates,
            'limitations':['同一场次的最低需求，不是全考试去重教师数',
                '未校验现有库存、教师可用时间、学科回避、每日监考上限和跨考试冲突',
                '各考场容量不同时不能套用统一容量，需按实际可用座位汇总']})


class ExamQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    view: Literal['exams', 'overview', 'calendar', 'rooms', 'teachers', 'candidates', 'checks'] = 'exams'
    exam_id: int | None = Field(default=None, gt=0, strict=True)
    exam_name: str | None = Field(default=None, min_length=1, max_length=100)
    academic_year: str | None = Field(default=None, max_length=20)
    term: Literal['1', '2'] | None = None
    student_id: int | None = Field(default=None, gt=0, strict=True)
    offset: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=20, ge=1, le=50, strict=True)


def page(items, q, total=None):
    total = len(items) if total is None else total
    visible = items[q.offset:q.offset + q.limit]
    more = q.offset + len(visible) < total
    return dict(items=visible, total=total, returned=len(visible), has_more=more,
                next_offset=q.offset + len(visible) if more else None)


async def execute(arguments, *, session, tenant_id):
    def reply(message, **kw):
        return _tool_response(NAME, message=message, **kw)
    try:
        q = ExamQuery.model_validate_json(arguments)
    except ValidationError:
        return reply('排考查询参数无效，请明确考试和查询类型。', ok=False, code='INVALID_ARGUMENT')
    stmt = select(Exam).where(Exam.tenant_id == tenant_id)
    for field in ('exam_id', 'exam_name', 'academic_year', 'term'):
        value = getattr(q, field)
        if value is not None:
            column = {'exam_id': Exam.id, 'exam_name': Exam.name,
                      'academic_year': Exam.academic_year, 'term': Exam.term}[field]
            stmt = stmt.where(column == value)
    exams = list((await session.execute(stmt.order_by(Exam.id))).scalars().all())
    scope = {'academic_year': q.academic_year, 'term': q.term, 'domain': 'exam'}
    if q.view == 'exams':
        return reply('本校考试列表；未指定学期时包含本校历史考试，不能当作当前学期统计。', scope=scope,
            data=page([{'exam_id': e.id, 'name': e.name, 'academic_year': e.academic_year,
                        'term': e.term, 'status': e.status} for e in exams], q))
    if q.exam_id is None and q.exam_name is None:
        return reply('请先明确考试名称或ID；可先查询考试列表，再给待确认计划。',
                     ok=False, code='MISSING_SCOPE', scope=scope)
    if len(exams) != 1:
        return reply('未唯一匹配本校指定考试，请核对考试名称、学年学期；不能代选其他考试。',
                     ok=False, code='MISSING_SCOPE', scope=scope)
    exam = exams[0]
    scope.update(exam_id=exam.id, exam_name=exam.name, academic_year=exam.academic_year, term=exam.term)
    async def rows(model):
        return list((await session.execute(select(model).where(
            model.tenant_id == tenant_id, model.exam_id == exam.id).order_by(model.id))).scalars().all())
    config = (await rows(ExamSchedulingConfig))
    settings = config[0] if config else None
    if q.view == 'checks':
        report = await check_plan(session, exam.id, tenant_id)
        return reply('已使用排考页面同一检查器核对保存结果；检查通过不等于生成或保存新方案。', scope=scope,
            data={**page(report['issues'], q), 'passed': report['ok'],
                  'counts_by_code': dict(Counter(i['code'] for i in report['issues']))})
    schedules, rooms = await rows(ExamSchedule), await rows(ExamRoomAssignment)
    if q.view == 'overview':
        candidate_stmt = select(ExamCandidateAssignment).where(ExamCandidateAssignment.tenant_id == tenant_id,
            ExamCandidateAssignment.exam_id == exam.id)
        count = (await session.execute(select(func.count()).select_from(candidate_stmt.subquery()))).scalar_one()
        distinct = (await session.execute(select(func.count(func.distinct(ExamCandidateAssignment.student_id))).where(
            ExamCandidateAssignment.tenant_id == tenant_id, ExamCandidateAssignment.exam_id == exam.id))).scalar_one()
        return reply('排考概况：考场场次与物理考场分别统计；考生场次不是去重人数。', scope=scope, data={
            'exam_status': exam.status, 'configuration': settings.model_dump(mode='json', exclude={'id','tenant_id','created_at','updated_at'}) if settings else None,
            'confirmed_venues': [{'name': v.name, 'capacity': v.capacity} for v in await rows(ExamVenue)],
            'schedule_count': len(schedules), 'room_session_count': len(rooms),
            'distinct_rooms': len({r.room_name for r in rooms}), 'candidate_assignment_count': count,
            'distinct_candidates': distinct, 'distinct_invigilators': len({t for r in rooms for t in r.invigilator_ids}),
            'missing_data': ([] if settings else ['考试配置']) + ([] if schedules else ['考试日程']) + ([] if rooms else ['考场与考生安排'])})
    async def names(model):
        return dict((await session.execute(select(model.id, model.name).where(model.tenant_id == tenant_id))).all())
    grades, subjects = await names(Grade), await names(Subject)
    if q.view == 'calendar':
        items = [{**s.model_dump(mode='json', exclude={'tenant_id','created_at','updated_at'}),
                  'grade_name': grades.get(s.grade_id), 'subject_name': subjects.get(s.subject_id)} for s in schedules]
    elif q.view == 'rooms':
        items = [{**r.model_dump(mode='json', exclude={'tenant_id','created_at','updated_at'}),
                  'grade_name': grades.get(r.grade_id), 'subject_name': subjects.get(r.subject_id)} for r in rooms]
    elif q.view == 'teachers':
        teachers = await names(User)
        availability = {a.teacher_id: a for a in await rows(ExamInvigilatorAvailability)}
        workload = Counter(t for r in rooms for t in r.invigilator_ids)
        items = []
        for teacher_id in sorted(set(availability) | set(workload)):
            a = availability.get(teacher_id)
            items.append({'teacher_id': teacher_id, 'teacher_name': teachers.get(teacher_id),
                'assigned_sessions': workload[teacher_id], 'enabled': a.enabled if a else True,
                'leave_start': str(a.leave_start) if a and a.leave_start else None,
                'leave_end': str(a.leave_end) if a and a.leave_end else None,
                'unavailable_slots': a.unavailable_slots if a else [],
                'availability_source': 'exam_config' if a else 'not_configured'})
    else:
        stmt = select(ExamCandidateAssignment).where(ExamCandidateAssignment.tenant_id == tenant_id,
            ExamCandidateAssignment.exam_id == exam.id)
        if q.student_id is not None:
            stmt = stmt.where(ExamCandidateAssignment.student_id == q.student_id)
        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        values = (await session.execute(stmt.order_by(ExamCandidateAssignment.id).offset(q.offset).limit(q.limit))).scalars().all()
        items = [r.model_dump(mode='json', exclude={'tenant_id','created_at','updated_at'}) for r in values]
        more = q.offset + len(items) < total
        return reply('考生考试与座位明细；按考生ID过滤，不包含联系方式或学号。', scope=scope,
            data={'items': items, 'total': total, 'returned': len(items), 'has_more': more,
                  'next_offset': q.offset + len(items) if more else None})
    return reply('本校指定考试已保存数据；监考次数不是授课工作量，是否冲突需调用checks。',
                 scope=scope, data=page(items, q))


TOOL = {'type':'function', 'function': {'name': NAME,
    'description': '只读查询本校排考：exams考试列表；overview配置与统计；calendar日期场次；rooms考场容量及监考；teachers监考工作量和禁用请假时段；candidates考生座位；checks复用排考页面真实检查器检查座位容量、教师、学生、跨考试冲突与规则。列表外必须明确考试ID或名称，不能猜页面考试。区分全员参考grade与选科参考choices、自定义custom与学校策略school，以及考场room_mode规则，不能用课表行政走班模式代替排考模式。不生成、保存、调整或打印数据。',
    'parameters': ExamQuery.model_json_schema()}}
CAPACITY_TOOL = {'type':'function', 'function': {'name':'calculate_exam_capacity',
    'description':'只读程序计算同一场次考场与同时监考教师的最低需求，输入去重参考人数、应用规则后的每间可用座位、每间监考人数和来源。禁止将班额当考试座位、将累计考生场次当同场人数；不是实际排考可行性检查。',
    'parameters':ExamCapacity.model_json_schema()}}
