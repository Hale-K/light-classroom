"""Validation shared by exam adjustments and printable documents."""
from collections import defaultdict
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import select
from app.models.exam import (Exam, ExamSchedule, ExamRoomAssignment, ExamCandidateAssignment,
                             ExamRoom, ExamVenue, ExamInvigilatorAvailability, ExamSchedulingConfig)
from app.models.org import Class, CourseHourPlan, Student, Subject, TeachingAssignment, User
from app.models.gaokao import StudentSubjectChoice
from app.services.exam_rules import ExamRules, calendar_violations, exam_seat_capacity
from app.services.exam_availability import teacher_time_blocked
from app.services.exam_resources import exam_room_catalog


async def lock_exam(session, exam_id, tenant_id):
    # Serialize changes to resources across exams in one school.
    from app.models.org import Tenant
    await session.execute(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    exam = (await session.execute(select(Exam).where(
        Exam.id == exam_id, Exam.tenant_id == tenant_id).with_for_update())).scalar_one_or_none()
    if not exam:
        raise HTTPException(404, "考试不存在")
    if exam.status in {"finished", "archived"}:
        raise HTTPException(409, "考试已结束或归档，不能调整安排")
    return exam


def overlaps(a, b):
    return a.exam_date == b.exam_date and a.start_time < b.end_time and b.start_time < a.end_time


async def context(session, tenant_id, exam_id=None, dates=None):
    if exam_id is not None and dates is None:
        dates = set((await session.execute(select(ExamSchedule.exam_date).where(
            ExamSchedule.tenant_id == tenant_id, ExamSchedule.exam_id == exam_id))).scalars().all())
    async def rows(model):
        if model == ExamRoom:
            return await exam_room_catalog(session, tenant_id)
        stmt = select(model).where(model.tenant_id == tenant_id)
        if model in {ExamSchedule, ExamRoomAssignment} and dates is not None:
            stmt = stmt.where(model.exam_date.in_(dates))
        if model == ExamCandidateAssignment and exam_id is not None:
            stmt = stmt.where(model.exam_id == exam_id)
        return list((await session.execute(stmt)).scalars().all())
    return {model.__name__: await rows(model) for model in (
        ExamSchedule, ExamRoomAssignment, ExamCandidateAssignment, ExamRoom, ExamVenue,
        ExamInvigilatorAvailability, ExamSchedulingConfig, User, Exam, Class, CourseHourPlan, TeachingAssignment)}


def room_issues(room, ctx):
    issues = []
    def issue(code, message, suggestion):
        issues.append(dict(code=code, message=f"{room.exam_date} · {room.room_name}：{message}",
                           suggestion=suggestion, room_assignment_id=room.id))
    schedule = next((s for s in ctx['ExamSchedule'] if s.id == room.exam_schedule_id), None)
    if not schedule:
        issue('missing_schedule', '缺少考试日程', '重新生成安排')
        return issues
    catalog = next((r for r in ctx['ExamRoom'] if r.name == room.room_name and not r.is_deleted), None)
    venue = next((r for r in ctx['ExamVenue'] if r.exam_id == room.exam_id and r.name == room.room_name), None)
    if any(v.exam_id == room.exam_id for v in ctx['ExamVenue']) and not venue:
        issue('room_outside_scope', '考场不在本次确认范围', '更换考场或重新确认考场范围')
    if (catalog and catalog.status != 'available') or (ctx['ExamRoom'] and not catalog):
        issue('room_unavailable', '考场已停用或维修', '更换可用考场')
    config = next((c for c in ctx['ExamSchedulingConfig'] if c.exam_id == room.exam_id), None)
    rules = ExamRules.model_validate(config.rules if config else {})
    capacity = exam_seat_capacity(min(room.capacity, catalog.capacity if catalog else room.capacity,
                   venue.capacity if venue else room.capacity), rules)
    candidates = [c for c in ctx['ExamCandidateAssignment'] if c.exam_room_assignment_id == room.id]
    if len(candidates) > capacity or any(c.seat_no > capacity or c.seat_no < 1 for c in candidates):
        issue('room_capacity', f'座位超出考试容量 {capacity}', '拆分考场或调整考生座位')
    if room.candidate_count != len(candidates):
        issue('count_mismatch', '考生人数与座位明细不一致', '重新生成安排')
    seats = defaultdict(list)
    for candidate in candidates:
        seats[candidate.seat_no].append(candidate.student_id)
        if candidate.exam_schedule_id != room.exam_schedule_id or candidate.room_name != room.room_name:
            issue('candidate_mismatch', '考生与考场信息不一致', '调整考生座位或重新生成')
        if (candidate.exam_date, candidate.start_time, candidate.end_time) != (schedule.exam_date, schedule.start_time, schedule.end_time):
            issue('candidate_time_mismatch', '准考证时间与考试日程不一致', '重新生成安排')
    for seat, students in seats.items():
        if len(students) > 1:
            issue('seat_collision', f'{seat} 号座位安排了 {len(students)} 名考生', '把其中一名考生移到空座位')
    config = next((c for c in ctx['ExamSchedulingConfig'] if c.exam_id == room.exam_id), None)
    rules = ExamRules.model_validate(config.rules if config else {})
    required = config.invigilators_per_room if config else 1
    if rules.room_mode == 'gaokao':
        required = max(2, required)
    if len(set(room.invigilator_ids)) != required or len(room.invigilator_ids) != required:
        issue('teacher_count', f'需要 {required} 名不同的监考教师', '补齐监考教师')
    for teacher_id in room.invigilator_ids:
        teacher = next((u for u in ctx['User'] if u.id == teacher_id), None)
        setting = next((a for a in ctx['ExamInvigilatorAvailability']
                        if a.teacher_id == teacher_id and a.exam_id == room.exam_id), None)
        if not teacher or teacher.role != 'teacher' or teacher.status != 'active' or teacher.frozen:
            issue('teacher_unavailable', '监考教师账号不可用', '更换在职教师')
        elif teacher_time_blocked(setting, schedule):
            issue('teacher_unavailable', f'{teacher.name} 在该场次不能监考', '更换教师或修改其可用时间')
        daily_count = 1 + sum(teacher_id in other.invigilator_ids for other in ctx['ExamRoomAssignment']
                              if other.id != room.id and other.exam_date == room.exam_date)
        if daily_count > rules.teacher_daily_limit:
            issue('teacher_daily_limit', f'{teacher.name if teacher else teacher_id} 当天承担 {daily_count} 场监考，超过 {rules.teacher_daily_limit} 场上限（含其他考试）',
                  '更换当天工作量较少的教师，或调整每日监考上限')
        exam = next((e for e in ctx['Exam'] if e.id == room.exam_id), None)
        classes = {c.id for c in ctx['Class'] if c.grade_id == room.grade_id}
        if rules.avoid_own_subject and exam:
            expected = {p.class_id for p in ctx['CourseHourPlan'] if p.class_id in classes and p.subject_id == room.subject_id
                        and p.academic_year == exam.academic_year and p.term == exam.term and p.weekly_periods > 0}
            known = {a.class_id for a in ctx['TeachingAssignment'] if a.class_id in classes and a.subject_id == room.subject_id
                     and a.academic_year == exam.academic_year and a.term == exam.term and a.teacher_id is not None}
            if expected - known:
                issue('own_subject_unknown', '任教关系不完整，无法核验学科回避', '补齐班级任教关系或关闭回避规则')
        if rules.avoid_own_subject and exam and any(p.teacher_id == teacher_id and p.subject_id == room.subject_id
                and p.class_id in classes and p.academic_year == exam.academic_year and p.term == exam.term for p in ctx['TeachingAssignment']):
            issue('own_subject', f'{teacher.name if teacher else teacher_id} 任教本年级该学科，需要回避', '更换其他学科教师，或关闭任教学科回避')
    schedules = {s.id: s for s in ctx['ExamSchedule']}
    for other in ctx['ExamRoomAssignment']:
        other_schedule = schedules.get(other.exam_schedule_id)
        if other.id == room.id or not other_schedule or not overlaps(schedule, other_schedule):
            continue
        if other.room_name == room.room_name:
            issue('room_collision', '考场在重叠时段被另一场考试占用', '更换考场或调整考试时间')
        if set(other.invigilator_ids) & set(room.invigilator_ids):
            issue('teacher_collision', '监考教师同时承担另一场监考', '更换空闲教师或调整考试时间')
    return issues


async def check_plan(session, exam_id, tenant_id):
    ctx = await context(session, tenant_id, exam_id)
    rooms = [r for r in ctx['ExamRoomAssignment'] if r.exam_id == exam_id]
    issues = [i for r in rooms for i in room_issues(r, ctx)]
    if not rooms:
        issues.append(dict(code='empty_plan', message='尚未生成考生与考场安排', suggestion='完成配置后生成安排'))
    schedules = {s.id: s for s in ctx['ExamSchedule']}
    own_schedules = [s for s in schedules.values() if s.exam_id == exam_id]
    config = next((c for c in ctx['ExamSchedulingConfig'] if c.exam_id == exam_id), None)
    daily_scope = [SimpleNamespace(grade_id=c.student_id, subject_id=c.subject_id, exam_date=c.exam_date,
                                  start_time=c.start_time, end_time=c.end_time)
                   for c in ctx['ExamCandidateAssignment'] if c.exam_id == exam_id] if config and config.candidate_mode == 'choices' else own_schedules
    for message in calendar_violations(daily_scope, ExamRules.model_validate(config.rules if config else {}),
                                       group_label='考生' if config and config.candidate_mode == 'choices' else '年级'):
        issues.append(dict(code='calendar_rule', message=message, suggestion='调整考试场次或规则后重新生成安排'))
    if config and own_schedules and config.updated_at and all(s.created_at for s in own_schedules):
        if config.updated_at > min(s.created_at for s in own_schedules):
            issues.append(dict(code='config_changed', message='排考配置已修改，当前结果尚未重新生成', suggestion='在准备步骤中检查并重新生成安排'))
    students = defaultdict(list)
    room_ids = {r.id for r in rooms}
    for candidate in ctx['ExamCandidateAssignment']:
        if candidate.exam_id == exam_id:
            students[candidate.student_id].append(candidate)
            if candidate.exam_room_assignment_id not in room_ids:
                issues.append(dict(code='missing_room', message=f'考生 {candidate.student_id} 没有有效考场', suggestion='重新生成安排'))
    for student_id, rows in students.items():
        for index, a in enumerate(rows):
            for b in rows[index + 1:]:
                if overlaps(a, b):
                    issues.append(dict(code='student_collision', message=f'考生 {student_id} 的两门考试时间重叠', suggestion='调整考试日程'))
        if any(c.exam_schedule_id not in schedules for c in rows):
            issues.append(dict(code='missing_schedule', message=f'考生 {student_id} 缺少考试日程', suggestion='重新生成安排'))
    if students:
        external = list((await session.execute(select(ExamCandidateAssignment).where(
            ExamCandidateAssignment.tenant_id == tenant_id, ExamCandidateAssignment.exam_id != exam_id,
            ExamCandidateAssignment.student_id.in_(students),
            ExamCandidateAssignment.exam_date.in_({s.exam_date for s in own_schedules})))).scalars().all())
        for other in external:
            if any(overlaps(c, other) for c in students[other.student_id]):
                issues.append(dict(code='student_other_exam', message=f'考生 {other.student_id} 同时参加另一场考试', suggestion='调整考试时间，避免跨考试冲突'))
    exam = (await session.execute(select(Exam).where(Exam.id == exam_id, Exam.tenant_id == tenant_id))).scalar_one()
    if own_schedules and exam.status == 'preparing':
        classes = list((await session.execute(select(Class).where(Class.tenant_id == tenant_id,
            Class.academic_year == exam.academic_year, Class.term == exam.term,
            Class.grade_id.in_({s.grade_id for s in own_schedules})))).scalars().all())
        grade_by_class = {c.id: c.grade_id for c in classes}
        roster = list((await session.execute(select(Student).where(Student.tenant_id == tenant_id,
            Student.class_id.in_(grade_by_class), Student.status == 'studying'))).scalars().all())
        choices = list((await session.execute(select(StudentSubjectChoice).where(
            StudentSubjectChoice.tenant_id == tenant_id, StudentSubjectChoice.academic_year == exam.academic_year,
            StudentSubjectChoice.effective_term == exam.term,
            StudentSubjectChoice.student_id.in_([s.id for s in roster]), StudentSubjectChoice.status == 'confirmed')
            .order_by(StudentSubjectChoice.confirmed_at))).scalars().all()) if config and config.candidate_mode == 'choices' else []
        selected = {c.student_id: set(c.selected_subject_ids) | set(c.secondary_subject_ids) | ({c.primary_subject_id} if c.primary_subject_id else set()) for c in choices}
        names = dict((await session.execute(select(Subject.id, Subject.name).where(Subject.tenant_id == tenant_id))).all())
        assigned = {(c.grade_id, c.subject_id, c.student_id) for c in ctx['ExamCandidateAssignment'] if c.exam_id == exam_id}
        missing = []
        subject_schedules = {(s.grade_id, s.subject_id): s for s in own_schedules}
        for schedule in subject_schedules.values():
            for student in roster:
                eligible = not config or config.candidate_mode == 'grade' or names.get(schedule.subject_id) in {'语文', '数学', '英语', '外语'} or schedule.subject_id in selected.get(student.id, set())
                if grade_by_class.get(student.class_id) == schedule.grade_id and eligible and (schedule.grade_id, schedule.subject_id, student.id) not in assigned:
                    missing.append(student.name)
        if missing:
            issues.append(dict(code='missing_candidate', message=f'有 {len(missing)} 个考生场次未分配座位（如 {missing[0]}）', suggestion='核对参考范围后重新生成安排'))
    return dict(ok=not issues, issues=issues)
