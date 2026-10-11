"""排考 API：从考试试卷生成日期、场次、考场和监考安排。"""
from datetime import date
from dataclasses import replace
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.enums import BaseUserRole, StudentStatus, UserStatus
from app.models.exam import (
    Exam, ExamCandidateAssignment, ExamInvigilatorAvailability, ExamRoom, ExamRoomAssignment,
    ExamSchedule, ExamSchedulingConfig, ExamVenue,
)
from app.models.gaokao import StudentSubjectChoice
from app.models.org import Class, CourseHourPlan, Grade, Student, Subject, TeachingAssignment, Tenant, User
from app.services.exam_operations import lock_exam, check_plan, context, room_issues, overlaps
from app.services.exam_rules import ExamRules, calendar_violations, exam_seat_capacity, order_exam_rosters
from app.services.exam_availability import teacher_time_blocked, parse_weekly_window
from app.services.exam_time_slots import apply_subject_time_slots
from app.services.exam_context import exam_environment
from app.services.exam_resources import exam_room_catalog
from app.services.exam_rotation import build_rotation
from app.services.scheduling import (
    ExamRoomResource,
    arrange_exam_candidates,
    generate_exam_schedule,
    normalize_exam_room_resources,
    resolve_exam_candidates,
    select_invigilator_ids,
)

router = APIRouter(prefix="/exam-scheduling", tags=["排考管理"])


class SessionIn(BaseModel):
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")

    @model_validator(mode="after")
    def validate_range(self):
        if any(int(t[:2]) > 23 or int(t[3:]) > 59 for t in (self.start_time, self.end_time)):
            raise ValueError("请输入有效的考试时间")
        if self.start_time >= self.end_time:
            raise ValueError("场次结束时间必须晚于开始时间")
        return self


class ExamRoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    capacity: int = Field(default=40, ge=1, le=500)
    source_type: str = Field(default="custom", pattern=r"^(classroom|custom)$")
    source_class_id: int | None = None


class SaveExamVenuesIn(BaseModel):
    rooms: list[ExamRoomIn] = Field(min_length=1, max_length=5000)


class ExamSchedulingConfigIn(BaseModel):
    grade_ids: list[int] = Field(min_length=1, max_length=10)
    subject_ids: list[int] = Field(default_factory=list, max_length=100)
    candidate_mode: str = Field(default="grade", pattern=r"^(grade|choices)$")
    schedule_mode: str = Field(default="custom", pattern=r"^(custom|school)$")
    start_date: date | None = None
    excluded_dates: list[date] = Field(default_factory=list, max_length=30)
    sessions: list[SessionIn] = Field(default_factory=list, max_length=4)
    invigilators_per_room: int = Field(default=1, ge=1, le=3)
    rules: ExamRules | None = None

    @model_validator(mode="after")
    def validate_sessions(self):
        ordered = sorted(self.sessions, key=lambda s: s.start_time)
        if any(a.end_time > b.start_time for a, b in zip(ordered, ordered[1:])):
            raise ValueError("考试场次时间不能重叠")
        return self


class ExamInvigilatorAvailabilityIn(BaseModel):
    enabled: bool = True
    leave_start: date | None = None
    leave_end: date | None = None
    unavailable_slots: list[str] = Field(default_factory=list, max_length=100)
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_leave_range(self):
        for value in self.unavailable_slots:
            if value.startswith('weekly#') and not parse_weekly_window(value):
                raise ValueError('每周不可监考时段必须包含有效的星期及开始、结束时间')
        if bool(self.leave_start) != bool(self.leave_end):
            raise ValueError("请同时填写休假开始和结束日期")
        if self.leave_start and self.leave_end and self.leave_start > self.leave_end:
            raise ValueError("休假开始日期不能晚于结束日期")
        return self


class GenerateExamScheduleIn(BaseModel):
    exam_id: int
    grade_ids: list[int] = Field(default_factory=list, max_length=10)
    subject_ids: list[int] | None = Field(default=None, max_length=100)
    candidate_mode: str | None = Field(default=None, pattern=r"^(grade|choices)$")
    schedule_mode: str | None = Field(default=None, pattern=r"^(custom|school)$")
    start_date: date
    room: str = Field(default="各班教室", min_length=1, max_length=100)
    excluded_dates: list[date] = Field(default_factory=list, max_length=30)
    sessions: list[SessionIn] = Field(default_factory=lambda: [
        SessionIn(start_time="09:00", end_time="11:00"),
        SessionIn(start_time="14:30", end_time="16:30"),
    ], min_length=1, max_length=4)
    rooms: list[ExamRoomIn] = Field(default_factory=list, max_length=5000)
    invigilators_per_room: int = Field(default=1, ge=1, le=3)
    rules: ExamRules | None = None

    @model_validator(mode="after")
    def validate_sessions(self):
        ordered = sorted(self.sessions, key=lambda s: s.start_time)
        if any(a.end_time > b.start_time for a, b in zip(ordered, ordered[1:])):
            raise ValueError("考试场次时间不能重叠")
        return self


async def _output(session: AsyncSession, items: list[ExamSchedule]):
    subjects = list((await session.execute(select(Subject))).scalars().all())
    grades = list((await session.execute(select(Grade))).scalars().all())
    teachers = list((await session.execute(select(User))).scalars().all())
    subject_map = {item.id: item.name for item in subjects}
    grade_map = {item.id: item.name for item in grades}
    teacher_map = {item.id: item.name for item in teachers}
    result = []
    for item in items:
        data = item.model_dump()
        data.update(
            subject_name=subject_map.get(item.subject_id, "未知学科"),
            grade_name=grade_map.get(item.grade_id, "未知年级"),
            invigilator_name=teacher_map.get(item.invigilator_id, "待安排"),
        )
        result.append(data)
    return result


async def _room_resources(
    session: AsyncSession,
    tenant_id: int,
    exam_id: int,
    configured: list[ExamRoomIn],
) -> list[ExamRoomResource]:
    catalog = await exam_room_catalog(session, tenant_id)
    if configured:
        names = [item.name.strip() for item in configured]
        catalog = [room for room in catalog if room.name in names]
        blocked = [item.name for item in catalog if item.status != "available"]
        if blocked:
            raise ValueError(f"以下考场当前不可用：{', '.join(blocked)}")
        capacities = {item.name: item.capacity for item in catalog}
        missing = sorted(set(names) - capacities.keys())
        if missing:
            raise ValueError(f"考场资源不存在，请重新选择：{', '.join(missing)}")
        return normalize_exam_room_resources([
            ExamRoomResource(name=item.name.strip(), capacity=min(item.capacity, capacities.get(item.name.strip(), item.capacity)))
            for item in configured
        ])
    saved = list((await session.execute(select(ExamVenue).where(
        ExamVenue.tenant_id == tenant_id,
        ExamVenue.exam_id == exam_id,
    ).order_by(ExamVenue.id))).scalars().all())
    if saved:
        return await _room_resources(session, tenant_id, exam_id,
            [ExamRoomIn(name=item.name, capacity=item.capacity) for item in saved])
    catalog = [room for room in catalog if room.status == 'available']
    return normalize_exam_room_resources([
        ExamRoomResource(name=item.name, capacity=item.capacity) for item in catalog
    ])


async def _candidate_rosters(
    session: AsyncSession,
    tenant_id: int,
    exam: Exam,
    papers: list[dict],
    subject_names: dict[int, str],
    candidate_mode: str = "choices",
) -> tuple[dict[int, list[int]], int]:
    grade_ids = {int(item["grade_id"]) for item in papers}
    classes = list((await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.grade_id.in_(grade_ids),
        Class.academic_year == exam.academic_year,
        Class.term == exam.term,
    ))).scalars().all())
    grade_by_class = {item.id: item.grade_id for item in classes}
    students = list((await session.execute(select(Student).where(
        Student.tenant_id == tenant_id,
        Student.class_id.in_(grade_by_class),
        Student.status == StudentStatus.studying,
    ).order_by(Student.roster_order, Student.id))).scalars().all()) if grade_by_class else []
    student_ids_by_grade: dict[int, list[int]] = {grade_id: [] for grade_id in grade_ids}
    for student in students:
        student_ids_by_grade[grade_by_class[student.class_id]].append(student.id)

    if candidate_mode == "grade":
        return {int(p['id']): student_ids_by_grade.get(int(p['grade_id']), []) for p in papers}, 0

    choices = list((await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == tenant_id,
        StudentSubjectChoice.student_id.in_([item.id for item in students]),
        StudentSubjectChoice.academic_year == exam.academic_year,
        StudentSubjectChoice.effective_term == exam.term,
        StudentSubjectChoice.status == "confirmed",
    ).order_by(StudentSubjectChoice.confirmed_at))).scalars().all()) if students else []
    selected_by_student: dict[int, set[int]] = {}
    for choice in choices:
        selected = set(int(item) for item in choice.selected_subject_ids)
        if choice.primary_subject_id:
            selected.add(int(choice.primary_subject_id))
        selected.update(int(item) for item in choice.secondary_subject_ids)
        selected_by_student[choice.student_id] = selected

    rosters = resolve_exam_candidates(
        papers,
        student_ids_by_grade=student_ids_by_grade,
        selected_subject_ids_by_student=selected_by_student,
        subject_names=subject_names,
    )
    elective_subject_ids = {
        int(item["subject_id"]) for item in papers
        if subject_names.get(int(item["subject_id"])) not in {"语文", "数学", "英语", "外语"}
    }
    elective_grades = {int(p['grade_id']) for p in papers if int(p['subject_id']) in elective_subject_ids}
    missing_choice_count = sum(
        not selected_by_student.get(student.id)
        for student in students
        if grade_by_class.get(student.class_id) in elective_grades
    )
    return rosters, missing_choice_count


async def _plan_output(session: AsyncSession, exam_id: int, mode: str):
    schedules = list((await session.execute(select(ExamSchedule).where(
        ExamSchedule.exam_id == exam_id,
    ).order_by(ExamSchedule.exam_date, ExamSchedule.session_index, ExamSchedule.grade_id))).scalars().all())
    rooms = list((await session.execute(select(ExamRoomAssignment).where(
        ExamRoomAssignment.exam_id == exam_id,
    ).order_by(ExamRoomAssignment.exam_date, ExamRoomAssignment.session_index, ExamRoomAssignment.room_name))).scalars().all())
    if not rooms:
        schedules = []
    candidate_count = int((await session.execute(select(func.count(ExamCandidateAssignment.id)).where(
        ExamCandidateAssignment.exam_id == exam_id,
    ))).scalar_one())
    student_count = int((await session.execute(select(func.count(func.distinct(ExamCandidateAssignment.student_id))).where(
        ExamCandidateAssignment.exam_id == exam_id,
    ))).scalar_one())
    subject_map = dict((await session.execute(select(Subject.id, Subject.name))).all())
    grade_map = dict((await session.execute(select(Grade.id, Grade.name))).all())
    teachers = dict((await session.execute(select(User.id, User.name))).all())
    room_rows = []
    schedule_map = {s.id: s for s in schedules}
    for item in rooms:
        row = item.model_dump()
        row.update(
            start_time=schedule_map[item.exam_schedule_id].start_time if item.exam_schedule_id in schedule_map else None,
            end_time=schedule_map[item.exam_schedule_id].end_time if item.exam_schedule_id in schedule_map else None,
            subject_name=subject_map.get(item.subject_id, "未知学科"),
            grade_name=grade_map.get(item.grade_id, "未知年级"),
            invigilator_names=[teachers.get(teacher_id, "待安排") for teacher_id in item.invigilator_ids],
        )
        room_rows.append(row)
    return {
        "mode": mode,
        "schedules": await _output(session, schedules),
        "rooms": room_rows,
        "summary": {
            "day_count": len({item.exam_date for item in schedules}),
            "session_count": len({(item.exam_date, item.session_index) for item in schedules}),
            "room_count": len(rooms),
            "student_count": student_count,
            "candidate_assignment_count": candidate_count,
            "invigilator_count": len({teacher_id for item in rooms for teacher_id in item.invigilator_ids}),
        },
    }


async def _generate_full_plan(
    body: GenerateExamScheduleIn,
    session: AsyncSession,
    tenant_id: int,
    preview: bool = False,
    calendar_only: bool = False,
):
    exam = await _exam_or_404(session, body.exam_id, tenant_id) if preview or calendar_only else await lock_exam(session, body.exam_id, tenant_id)
    saved_config = (await session.execute(select(ExamSchedulingConfig).where(
        ExamSchedulingConfig.tenant_id == tenant_id,
        ExamSchedulingConfig.exam_id == body.exam_id,
    ))).scalar_one_or_none()
    effective_grade_ids = body.grade_ids or (saved_config.grade_ids if saved_config else [])
    effective_subject_ids = body.subject_ids if body.subject_ids is not None else (saved_config.subject_ids if saved_config else [])
    candidate_mode = body.candidate_mode or (saved_config.candidate_mode if saved_config else "grade")
    schedule_mode = body.schedule_mode or (saved_config.schedule_mode if saved_config else "custom")
    # Whole-grade exams require everyone to take each selected subject. The
    # high-school elective strategy may run physics/history simultaneously,
    # which is only valid for disjoint candidate rosters.
    if candidate_mode == 'grade':
        schedule_mode = 'custom'

    rules = body.rules or ExamRules.model_validate(saved_config.rules if saved_config else {})
    # Explicit legacy API requests remain explicit. The new UI sends auto/manual.
    explicit_scope = body.candidate_mode is not None and (body.rules is None or 'reference_mode' not in body.rules.model_fields_set)
    if explicit_scope:
        rules = rules.model_copy(update={'reference_mode': 'manual'})
    if rules.reference_mode == 'auto' and not explicit_scope:
        environment = await exam_environment(session, tenant_id, exam)
        candidate_mode = environment['recommended_candidate_mode']
        if candidate_mode == 'grade':
            schedule_mode = 'custom'
    if schedule_mode != 'custom' and rules.subject_time_slots:
        raise HTTPException(422, '学校固定排考策略不能指定科目时段，请切换普通学校考试或清除科目时段设置')
    invigilators_per_room = max(2, body.invigilators_per_room) if rules.room_mode == 'gaokao' else body.invigilators_per_room
    course_stmt = select(CourseHourPlan, Class.grade_id).join(
        Class, Class.id == CourseHourPlan.class_id,
    ).where(
        Class.tenant_id == tenant_id,
        CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.academic_year == exam.academic_year,
        CourseHourPlan.term == exam.term,
        CourseHourPlan.weekly_periods > 0,
    ).order_by(Class.grade_id, CourseHourPlan.subject_id)
    if effective_grade_ids:
        course_stmt = course_stmt.where(Class.grade_id.in_(effective_grade_ids))
    if effective_subject_ids:
        course_stmt = course_stmt.where(CourseHourPlan.subject_id.in_(effective_subject_ids))
    course_rows = (await session.execute(course_stmt)).all()
    course_pairs = sorted({(int(grade_id), int(plan.subject_id)) for plan, grade_id in course_rows})
    if schedule_mode == 'custom' and effective_subject_ids:
        rank = {subject_id: index for index, subject_id in enumerate(effective_subject_ids)}
        course_pairs.sort(key=lambda pair: (pair[0], rank.get(pair[1], len(rank)), pair[1]))
    # The optimizer uses an in-memory identity for each grade/subject course;
    # no paper row or persisted paper mapping is required.
    courses = [
        {"id": index, "grade_id": grade_id, "subject_id": subject_id}
        for index, (grade_id, subject_id) in enumerate(course_pairs, start=1)
    ]
    if not courses:
        raise HTTPException(status_code=422, detail="所选年级在该学年尚未配置课程，请先检查课时方案")
    school = await session.get(Tenant, tenant_id)
    if school is None:
        raise HTTPException(status_code=404, detail="学校不存在")
    subjects = list((await session.execute(select(Subject))).scalars().all())
    subject_names = {item.id: item.name for item in subjects}
    teachers = list((await session.execute(select(User).where(
        User.tenant_id == tenant_id,
        User.status == UserStatus.active,
        User.role == BaseUserRole.teacher,
        User.frozen == False,
    ).order_by(User.id))).scalars().all())
    teacher_ids = select_invigilator_ids(teachers)
    try:
        teaching = list((await session.execute(select(TeachingAssignment, Class.grade_id).join(
            Class, Class.id == TeachingAssignment.class_id).where(TeachingAssignment.tenant_id == tenant_id,
            Class.tenant_id == tenant_id, TeachingAssignment.academic_year == exam.academic_year,
            TeachingAssignment.term == exam.term))).all()) if rules.avoid_own_subject else []
        if rules.avoid_own_subject:
            assigned_pairs = {(a.class_id, a.subject_id) for a, _ in teaching if a.teacher_id is not None}
            missing = {(p.class_id, p.subject_id) for p, _ in course_rows} - assigned_pairs
            if missing:
                raise ValueError(f'有 {len(missing)} 项班级任教关系未配置，无法检查任教学科回避；请补齐任教关系或关闭回避规则')
        rotating = candidate_mode == 'choices' and schedule_mode == 'school' and school.gaokao_mode == '3+1+2'
        candidate_rosters = None
        synchronized = schedule_mode == 'custom' and rules.same_subject_same_time
        calendar_courses = list({c['subject_id']: c for c in courses}.values()) if synchronized else courses
        generated = generate_exam_schedule(
            calendar_courses,
            start_date=body.start_date,
            teacher_ids=teacher_ids,
            sessions=tuple((item.start_time, item.end_time) for item in sorted(body.sessions, key=lambda s: s.start_time)[:rules.student_daily_limit]),
            room=body.room,
            excluded_dates=set(body.excluded_dates),
            mode=school.gaokao_mode if schedule_mode == "school" else "custom",
            subject_names=subject_names,
        )
        if schedule_mode == 'custom':
            # Preview, preflight and generation all use the same student reservations.
            # Own previous results must not block a replacement of this exam.
            candidate_rosters, missing_choice_count = await _candidate_rosters(
                session, tenant_id, exam, courses, subject_names, candidate_mode)
            reserved = list((await session.execute(select(ExamCandidateAssignment).where(
                ExamCandidateAssignment.tenant_id == tenant_id,
                ExamCandidateAssignment.exam_id != body.exam_id,
                ExamCandidateAssignment.exam_date >= body.start_date,
                ExamCandidateAssignment.student_id.in_({sid for roster in candidate_rosters.values() for sid in roster})
            ))).scalars().all())
            reservations = {}
            for row in reserved:
                reservations.setdefault((row.exam_date, row.start_time, row.end_time), set()).add(row.student_id)
            course_students = {key: set(ids) for key, ids in candidate_rosters.items()}
            subject_students = {}
            for course in courses:
                subject_students.setdefault(course['subject_id'], set()).update(course_students.get(course['id'], set()))
            def unavailable(item, day, start, end):
                roster = subject_students.get(item.subject_id, set()) if synchronized else course_students.get(item.course_key, set())
                return any(d == day and start < finish and begin < end and roster.intersection(students)
                           for (d, begin, finish), students in reservations.items())
            generated = apply_subject_time_slots(generated, start_date=body.start_date,
                sessions=[(s.start_time, s.end_time) for s in body.sessions],
                excluded_dates=set(body.excluded_dates), rules=rules,
                unavailable=unavailable if reservations else None)
        if synchronized:
            by_subject = {s.subject_id: s for s in generated}
            generated = [replace(by_subject[c['subject_id']], course_key=c['id'], grade_id=c['grade_id']) for c in courses]
        if rotating:
            candidate_rosters, missing_choice_count = await _candidate_rosters(
                session, tenant_id, exam, courses, subject_names, candidate_mode)
            if missing_choice_count:
                raise ValueError(f'有 {missing_choice_count} 名考生未确认选科；请先完成选科确认')
            generated, courses, candidate_rosters, needs_batches = build_rotation(
                courses, candidate_rosters, subject_names, start_date=body.start_date,
                sessions=tuple((s.start_time, s.end_time) for s in sorted(body.sessions, key=lambda s: s.start_time)[:rules.student_daily_limit]),
                excluded_dates=set(body.excluded_dates), room=body.room,
                allow_batches=rules.allow_subject_batches)
            if needs_batches and rules.same_subject_same_time:
                raise ValueError('同步轮转需要同科目分批，与“同科目各年级同时考”冲突；请关闭同时考规则或改用普通学校考试')
        violations = calendar_violations(generated, rules, check_daily=candidate_mode == 'grade')
        if violations:
            raise ValueError(violations[0] + '；请调整考试场次或排考规则')
        if calendar_only:
            grades = dict((await session.execute(select(Grade.id, Grade.name).where(Grade.tenant_id == tenant_id))).all())
            return [{"id": index, "grade_id": s.grade_id, "grade_name": grades.get(s.grade_id, ""),
                     "subject_id": s.subject_id, "subject_name": subject_names.get(s.subject_id, ""),
                     "exam_date": s.exam_date, "session_index": s.session_index,
                     "start_time": s.start_time, "end_time": s.end_time} for index, s in enumerate(generated)]
        if candidate_rosters is None:
            candidate_rosters, missing_choice_count = await _candidate_rosters(
                session, tenant_id, exam, courses, subject_names, candidate_mode,
            )
        if missing_choice_count:
            raise ValueError(f"有 {missing_choice_count} 名考生未完成确认选科，不能生成选考科目考场")
        for index, first in enumerate(generated):
            first_roster = set(candidate_rosters.get(first.course_key, []))
            for second in generated[index + 1:]:
                if not overlaps(first, second):
                    continue
                duplicate = first_roster & set(candidate_rosters.get(second.course_key, []))
                if duplicate:
                    raise ValueError(f'{first.exam_date} {first.start_time}–{first.end_time}：'
                        f'{subject_names.get(first.subject_id, "科目")}与{subject_names.get(second.subject_id, "科目")}同时开考，'
                        f'有 {len(duplicate)} 名学生需参加两科；请改用普通学校考试分场安排，或核对已确认选科')
        if candidate_mode == 'choices':
            per_student = [replace(s, grade_id=sid) for s in generated for sid in candidate_rosters.get(s.course_key, [])]
            violations = calendar_violations(per_student, rules, group_label='考生')
            if violations:
                raise ValueError(violations[0] + '；请调整考试场次或排考规则')
        occupied_candidates = list((await session.execute(select(ExamCandidateAssignment).where(
            ExamCandidateAssignment.tenant_id == tenant_id, ExamCandidateAssignment.exam_id != body.exam_id,
            ExamCandidateAssignment.exam_date.in_({s.exam_date for s in generated}),
            ExamCandidateAssignment.student_id.in_({sid for roster in candidate_rosters.values() for sid in roster})
        ))).scalars().all())
        for proposed in generated:
            roster = set(candidate_rosters.get(proposed.course_key, []))
            conflicts = [c for c in occupied_candidates if c.student_id in roster and overlaps(c, proposed)]
            if conflicts:
                other_names = dict((await session.execute(select(Exam.id, Exam.name).where(
                    Exam.tenant_id == tenant_id, Exam.id.in_({c.exam_id for c in conflicts})
                ))).all())
                other_subjects = dict((await session.execute(select(Subject.id, Subject.name).where(
                    Subject.tenant_id == tenant_id, Subject.id.in_({c.subject_id for c in conflicts})
                ))).all())
                details = sorted({f'「{other_names.get(c.exam_id, "考试")}」'
                    f'{other_subjects.get(c.subject_id, "科目")} {c.start_time}–{c.end_time}' for c in conflicts})
                raise ValueError(f'{proposed.exam_date} {proposed.start_time} '
                    f'{subject_names.get(proposed.subject_id, "科目")}有 {len({c.student_id for c in conflicts})} 名考生'
                    f'同时参加另一场考试：{"；".join(details)}；请调整考试日期或场次')
        availability_rows = list((await session.execute(select(ExamInvigilatorAvailability).where(
            ExamInvigilatorAvailability.tenant_id == tenant_id,
            ExamInvigilatorAvailability.exam_id == body.exam_id,
        ))).scalars().all())
        availability_by_teacher = {item.teacher_id: item for item in availability_rows}
        teacher_ids = [teacher_id for teacher_id in teacher_ids if availability_by_teacher.get(teacher_id, None) is None or availability_by_teacher[teacher_id].enabled]
        unavailable_teacher_slots: dict[int, set[tuple[date, int]]] = {}
        for teacher_id in teacher_ids:
            setting = availability_by_teacher.get(teacher_id)
            if not setting:
                continue
            blocked = set()
            for item in generated:
                if teacher_time_blocked(setting, item):
                    blocked.add((item.exam_date, item.session_index))
            if blocked:
                unavailable_teacher_slots[teacher_id] = blocked
        room_resources = await _room_resources(session, tenant_id, body.exam_id, body.rooms)
        room_resources = [replace(r, capacity=exam_seat_capacity(r.capacity, rules)) for r in room_resources]
        candidate_rosters = order_exam_rosters(candidate_rosters, rules, body.exam_id)
        ctx = await context(session, tenant_id, body.exam_id, {s.exam_date for s in generated})
        schedules = {s.id: s for s in ctx['ExamSchedule']}
        unavailable_rooms = {}
        existing_daily_workload = Counter()
        for occupied in ctx['ExamRoomAssignment']:
            existing = schedules.get(occupied.exam_schedule_id)
            if occupied.exam_id == body.exam_id or not existing:
                continue
            existing_daily_workload.update((teacher, existing.exam_date) for teacher in occupied.invigilator_ids)
            for proposed in generated:
                if overlaps(existing, proposed):
                    slot = (proposed.exam_date, proposed.session_index)
                    unavailable_rooms.setdefault(occupied.room_name, set()).add(slot)
                    for teacher in occupied.invigilator_ids:
                        unavailable_teacher_slots.setdefault(teacher, set()).add(slot)
        arrangement = arrange_exam_candidates(
            generated,
            candidate_ids_by_course=candidate_rosters,
            rooms=room_resources,
            teacher_ids=teacher_ids,
            unavailable_teacher_slots=unavailable_teacher_slots,
            unavailable_room_slots=unavailable_rooms,
            invigilators_per_room=invigilators_per_room,
            teacher_daily_limit=rules.teacher_daily_limit,
            existing_daily_workload=existing_daily_workload,
            excluded_teachers_by_course={c['id']: {p.teacher_id for p, grade in teaching
                if grade == c['grade_id'] and p.subject_id == c['subject_id'] and p.teacher_id is not None}
                for c in courses} if rules.avoid_own_subject else {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not arrangement.seats:
        raise HTTPException(422, "所选范围没有参考学生，请检查学生学籍、年级和选科")
    if preview:
        return {"ok": True, "student_count": len({s.student_id for s in arrangement.seats}),
                "room_count": len(arrangement.rooms), "session_count": len(generated)}

    saved_config = saved_config or ExamSchedulingConfig(tenant_id=tenant_id, exam_id=body.exam_id)
    for field, value in {
        'grade_ids': effective_grade_ids, 'subject_ids': effective_subject_ids,
        'candidate_mode': candidate_mode, 'schedule_mode': schedule_mode,
        'start_date': body.start_date, 'excluded_dates': [d.isoformat() for d in body.excluded_dates],
        'sessions': [s.model_dump() for s in body.sessions],
        'invigilators_per_room': invigilators_per_room, 'rules': rules.model_dump(),
    }.items():
        setattr(saved_config, field, value)
    session.add(saved_config)
    await session.flush()

    await session.execute(delete(ExamCandidateAssignment).where(
        ExamCandidateAssignment.tenant_id == tenant_id,
        ExamCandidateAssignment.exam_id == body.exam_id,
    ))
    await session.execute(delete(ExamRoomAssignment).where(
        ExamRoomAssignment.tenant_id == tenant_id,
        ExamRoomAssignment.exam_id == body.exam_id,
    ))
    await session.execute(delete(ExamSchedule).where(
        ExamSchedule.tenant_id == tenant_id,
        ExamSchedule.exam_id == body.exam_id,
    ))
    records = [ExamSchedule(
        exam_id=body.exam_id,
        grade_id=item.grade_id,
        subject_id=item.subject_id,
        exam_date=item.exam_date,
        session_index=item.session_index,
        start_time=item.start_time,
        end_time=item.end_time,
        room=item.room,
        invigilator_id=item.invigilator_id,
        tenant_id=tenant_id,
    ) for item in generated]
    session.add_all(records)
    await session.flush()
    schedule_by_course = {source.course_key: record for source, record in zip(generated, records)}
    first_invigilator_by_course: dict[int, int] = {}
    room_records = []
    for item in arrangement.rooms:
        schedule = schedule_by_course[item.course_key]
        if item.invigilator_ids and item.course_key not in first_invigilator_by_course:
            first_invigilator_by_course[item.course_key] = item.invigilator_ids[0]
        room_records.append(ExamRoomAssignment(
            exam_id=body.exam_id,
            exam_schedule_id=schedule.id,
            grade_id=item.grade_id,
            subject_id=item.subject_id,
            exam_date=item.exam_date,
            session_index=item.session_index,
            room_name=item.room_name,
            capacity=item.capacity,
            candidate_count=item.candidate_count,
            invigilator_ids=list(item.invigilator_ids),
            tenant_id=tenant_id,
        ))
    for source, record in zip(generated, records):
        record.invigilator_id = first_invigilator_by_course.get(source.course_key)
    session.add_all(room_records)
    await session.flush()
    room_by_course_name = {
        (source.course_key, room.room_name): room
        for source, room in zip(arrangement.rooms, room_records)
    }
    session.add_all([
        ExamCandidateAssignment(
            exam_id=body.exam_id,
            exam_schedule_id=schedule_by_course[item.course_key].id,
            exam_room_assignment_id=room_by_course_name[(item.course_key, item.room_name)].id,
            grade_id=item.grade_id,
            subject_id=item.subject_id,
            student_id=item.student_id,
            exam_date=item.exam_date,
            session_index=item.session_index,
            start_time=item.start_time,
            end_time=item.end_time,
            room_name=item.room_name,
            seat_no=item.seat_no,
            tenant_id=tenant_id,
        )
        for item in arrangement.seats
    ])
    await session.commit()
    return await _plan_output(session, body.exam_id, school.gaokao_mode)


def _exam_room_output(room: ExamRoom) -> dict:
    return room.model_dump()


async def _exam_or_404(session: AsyncSession, exam_id: int, tenant_id: int) -> Exam:
    exam = await session.get(Exam, exam_id)
    if not exam or exam.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="考试不存在")
    return exam


@router.get("/exams/{exam_id}/config", summary="读取排考范围与日程配置")
async def get_exam_config(
    exam_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    exam = await _exam_or_404(session, exam_id, tenant_id)
    config = (await session.execute(select(ExamSchedulingConfig).where(
        ExamSchedulingConfig.tenant_id == tenant_id,
        ExamSchedulingConfig.exam_id == exam_id,
    ))).scalar_one_or_none()
    environment = await exam_environment(session, tenant_id, exam)
    if config:
        data = config.model_dump()
        if ExamRules.model_validate(config.rules or {}).reference_mode == 'auto':
            data['candidate_mode'] = environment['recommended_candidate_mode']
            if data['candidate_mode'] == 'grade':
                data['schedule_mode'] = 'custom'
        data['environment'] = environment
        return {"code": 0, "message": "ok", "data": data}
    grade_ids = list((await session.execute(
        select(Class.grade_id).join(CourseHourPlan, CourseHourPlan.class_id == Class.id).where(
            Class.tenant_id == tenant_id,
            CourseHourPlan.tenant_id == tenant_id,
            CourseHourPlan.academic_year == (await session.get(Exam, exam_id)).academic_year,
            CourseHourPlan.term == (await session.get(Exam, exam_id)).term,
            CourseHourPlan.weekly_periods > 0,
        ).distinct().order_by(Class.grade_id)
    )).scalars().all())
    return {"code": 0, "message": "ok", "data": {
        "exam_id": exam_id,
        "grade_ids": grade_ids,
        "subject_ids": [], "candidate_mode": environment['recommended_candidate_mode'], "schedule_mode": "custom",
        "environment": environment,
        "start_date": None,
        "excluded_dates": [],
        "sessions": [{"start_time": "09:00", "end_time": "11:00"}, {"start_time": "14:30", "end_time": "16:30"}],
        "invigilators_per_room": 1,
        "rules": ExamRules().model_dump(),
    }}


@router.put("/exams/{exam_id}/config", summary="保存排考范围与日程配置")
async def save_exam_config(
    exam_id: int,
    body: ExamSchedulingConfigIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    exam = await lock_exam(session, exam_id, tenant_id)
    available_grade_ids = set((await session.execute(
        select(Class.grade_id).join(CourseHourPlan, CourseHourPlan.class_id == Class.id).where(
            Class.tenant_id == tenant_id,
            CourseHourPlan.tenant_id == tenant_id,
            CourseHourPlan.academic_year == exam.academic_year,
            CourseHourPlan.term == exam.term,
            CourseHourPlan.weekly_periods > 0,
        ).distinct()
    )).scalars().all())
    invalid = sorted(set(body.grade_ids) - available_grade_ids)
    if invalid:
        raise HTTPException(status_code=422, detail=f"所选年级没有该学年的课时方案：{invalid}")
    available_subject_ids = set((await session.execute(select(CourseHourPlan.subject_id).join(
        Class, Class.id == CourseHourPlan.class_id).where(Class.tenant_id == tenant_id,
        CourseHourPlan.tenant_id == tenant_id, Class.grade_id.in_(body.grade_ids),
        CourseHourPlan.academic_year == exam.academic_year, CourseHourPlan.term == exam.term,
        CourseHourPlan.weekly_periods > 0).distinct())).scalars().all())
    if set(body.subject_ids) - available_subject_ids:
        raise HTTPException(422, "所选科目不在参考年级的课程方案中，请重新选择考试科目")
    config = (await session.execute(select(ExamSchedulingConfig).where(
        ExamSchedulingConfig.tenant_id == tenant_id,
        ExamSchedulingConfig.exam_id == exam_id,
    ))).scalar_one_or_none() or ExamSchedulingConfig(tenant_id=tenant_id, exam_id=exam_id)
    config.grade_ids = list(dict.fromkeys(body.grade_ids))
    if 'subject_ids' in body.model_fields_set:
        config.subject_ids = list(dict.fromkeys(body.subject_ids))
    if 'candidate_mode' in body.model_fields_set:
        config.candidate_mode = body.candidate_mode
    if 'schedule_mode' in body.model_fields_set:
        config.schedule_mode = body.schedule_mode
    config.start_date = body.start_date
    config.excluded_dates = [item.isoformat() for item in body.excluded_dates]
    config.sessions = [item.model_dump() for item in body.sessions]
    effective_rules = body.rules or ExamRules.model_validate(config.rules or {})
    if 'candidate_mode' in body.model_fields_set and (body.rules is None or 'reference_mode' not in body.rules.model_fields_set):
        effective_rules = effective_rules.model_copy(update={'reference_mode': 'manual'})
    if effective_rules.reference_mode == 'auto':
        environment = await exam_environment(session, tenant_id, exam)
        config.candidate_mode = environment['recommended_candidate_mode']
        if config.candidate_mode == 'grade':
            config.schedule_mode = 'custom'
    if set(effective_rules.subject_time_slots.values()) - {s.start_time for s in body.sessions}:
        raise HTTPException(422, '科目指定的考试时段不存在，请重新选择科目时段')
    if config.candidate_mode == 'choices' and config.schedule_mode == 'school' and effective_rules.subject_time_slots:
        raise HTTPException(422, '学校固定排考策略不能指定科目时段，请切换普通学校考试或清除科目时段设置')
    config.invigilators_per_room = max(2, body.invigilators_per_room) if effective_rules.room_mode == 'gaokao' else body.invigilators_per_room
    config.rules = effective_rules.model_dump()
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return {"code": 0, "message": "ok", "data": config.model_dump()}


@router.get("/exams/{exam_id}/invigilators", summary="监考教师状态与可用性")
async def list_exam_invigilators(
    exam_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    await _exam_or_404(session, exam_id, tenant_id)
    teachers = list((await session.execute(select(User).where(
        User.tenant_id == tenant_id,
        User.role == BaseUserRole.teacher,
    ).order_by(User.name, User.id))).scalars().all())
    settings = list((await session.execute(select(ExamInvigilatorAvailability).where(
        ExamInvigilatorAvailability.tenant_id == tenant_id,
        ExamInvigilatorAvailability.exam_id == exam_id,
    ))).scalars().all())
    setting_by_teacher = {item.teacher_id: item for item in settings}
    assignments = list((await session.execute(select(ExamRoomAssignment).where(
        ExamRoomAssignment.tenant_id == tenant_id,
        ExamRoomAssignment.exam_id == exam_id,
    ))).scalars().all())
    assigned_count: dict[int, int] = {}
    for assignment in assignments:
        for teacher_id in assignment.invigilator_ids:
            assigned_count[teacher_id] = assigned_count.get(teacher_id, 0) + 1
    items = []
    for teacher in teachers:
        setting = setting_by_teacher.get(teacher.id)
        enabled = setting.enabled if setting else True
        on_leave = bool(setting and setting.leave_start and setting.leave_end)
        state = "disabled" if teacher.status != UserStatus.active or teacher.frozen else "excluded" if not enabled else "leave" if on_leave else "assigned" if assigned_count.get(teacher.id, 0) else "available"
        items.append({
            "teacher_id": teacher.id, "teacher_name": teacher.name,
            "account_status": "disabled" if teacher.frozen else teacher.status.value, "enabled": enabled,
            "leave_start": setting.leave_start if setting else None,
            "leave_end": setting.leave_end if setting else None,
            "unavailable_slots": setting.unavailable_slots if setting else [],
            "note": setting.note if setting else None,
            "assigned_count": assigned_count.get(teacher.id, 0), "state": state,
        })
    return {"code": 0, "message": "ok", "data": items}


@router.put("/exams/{exam_id}/invigilators/{teacher_id}", summary="设置教师本次监考可用性")
async def save_exam_invigilator(
    exam_id: int,
    teacher_id: int,
    body: ExamInvigilatorAvailabilityIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    await lock_exam(session, exam_id, tenant_id)
    teacher = await session.get(User, teacher_id)
    if not teacher or teacher.tenant_id != tenant_id or teacher.role != BaseUserRole.teacher:
        raise HTTPException(status_code=404, detail="教师不存在")
    setting = (await session.execute(select(ExamInvigilatorAvailability).where(
        ExamInvigilatorAvailability.tenant_id == tenant_id,
        ExamInvigilatorAvailability.exam_id == exam_id,
        ExamInvigilatorAvailability.teacher_id == teacher_id,
    ))).scalar_one_or_none() or ExamInvigilatorAvailability(tenant_id=tenant_id, exam_id=exam_id, teacher_id=teacher_id)
    for key, value in body.model_dump().items():
        setattr(setting, key, value)
    session.add(setting)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"teacher_id": teacher_id}}


@router.get("/rooms", summary="分页查询学校考场资源")
async def list_exam_rooms(
    keyword: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=300),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    catalog = await exam_room_catalog(session, tenant_id)
    if keyword.strip():
        catalog = [room for room in catalog if keyword.strip().lower() in room.name.lower()]
    total = len(catalog)
    items = catalog[(page - 1) * page_size:page * page_size]
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": [_exam_room_output(item) for item in items],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
        },
    }


@router.get("/exams/{exam_id}/venues", summary="查询本次考试已确认考场")
async def get_exam_venues(
    exam_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    exam = await session.get(Exam, exam_id)
    if not exam or exam.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="考试不存在")
    venues = list((await session.execute(select(ExamVenue).where(
        ExamVenue.tenant_id == tenant_id,
        ExamVenue.exam_id == exam_id,
    ).order_by(ExamVenue.id))).scalars().all())
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "confirmed": bool(venues),
            "rooms": [item.model_dump() for item in venues],
            "summary": {
                "room_count": len(venues),
                "seat_count": sum(item.capacity for item in venues),
            },
        },
    }


@router.put("/exams/{exam_id}/venues", summary="创建并确认本次考试考场")
async def save_exam_venues(
    exam_id: int,
    body: SaveExamVenuesIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    await lock_exam(session, exam_id, tenant_id)
    try:
        normalized = normalize_exam_room_resources([
            ExamRoomResource(name=item.name, capacity=item.capacity) for item in body.rooms
        ])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    catalog = await exam_room_catalog(session, tenant_id)
    names = {item.name.strip() for item in body.rooms}
    catalog = [room for room in catalog if room.name in names]
    blocked = [item.name for item in catalog if item.status != "available"]
    if blocked:
        raise HTTPException(status_code=422, detail=f"以下考场处于维护或停用状态：{', '.join(blocked)}")
    input_by_name = {item.name.strip(): item for item in body.rooms}
    catalog_by_name = {item.name: item for item in catalog}
    missing = sorted(input_by_name.keys() - catalog_by_name.keys())
    if missing:
        raise HTTPException(422, f"考场资源不存在，请重新选择：{', '.join(missing)}")
    await session.execute(delete(ExamVenue).where(
        ExamVenue.tenant_id == tenant_id,
        ExamVenue.exam_id == exam_id,
    ))
    venues = [ExamVenue(
        exam_id=exam_id,
        name=item.name,
        capacity=min(item.capacity, catalog_by_name[item.name].capacity),
        source_type=input_by_name[item.name].source_type,
        source_class_id=input_by_name[item.name].source_class_id,
        tenant_id=tenant_id,
    ) for item in normalized]
    session.add_all(venues)
    await session.commit()
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "confirmed": True,
            "rooms": [item.model_dump() for item in venues],
            "summary": {
                "room_count": len(venues),
                "seat_count": sum(item.capacity for item in venues),
            },
        },
    }


@router.post("/generate", summary="兼容生成考试日期表")
async def generate(
    body: GenerateExamScheduleIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    plan = await _generate_full_plan(body, session, tenant_id)
    return {"code": 0, "message": "ok", "data": plan["schedules"]}


@router.post("/plans", summary="按高考模式生成完整人员排考方案")
async def generate_plan(
    body: GenerateExamScheduleIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    return {"code": 0, "message": "ok", "data": await _generate_full_plan(body, session, tenant_id)}


@router.get("/plans/{exam_id}", summary="查询完整人员排考方案")
async def get_plan(
    exam_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    await _exam_or_404(session, exam_id, tenant_id)
    school = await session.get(Tenant, tenant_id)
    return {
        "code": 0,
        "message": "ok",
        "data": await _plan_output(session, exam_id, school.gaokao_mode if school else "3+1+2"),
    }


@router.get("/plans/{exam_id}/candidates", summary="分页查询考生考场座位")
async def get_plan_candidates(
    exam_id: int,
    room_assignment_id: int | None = None,
    grade_id: int | None = None,
    subject_id: int | None = None,
    exam_date: date | None = None,
    keyword: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=10, le=100),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    await _exam_or_404(session, exam_id, tenant_id)
    filters = [ExamCandidateAssignment.exam_id == exam_id, ExamCandidateAssignment.tenant_id == tenant_id, Student.tenant_id == tenant_id]
    if room_assignment_id is not None:
        filters.append(ExamCandidateAssignment.exam_room_assignment_id == room_assignment_id)
    if grade_id is not None:
        filters.append(ExamCandidateAssignment.grade_id == grade_id)
    if subject_id is not None:
        filters.append(ExamCandidateAssignment.subject_id == subject_id)
    if exam_date is not None:
        filters.append(ExamCandidateAssignment.exam_date == exam_date)
    if keyword.strip():
        filters.append(
            Student.name.ilike(f"%{keyword.strip()}%")
            | Student.student_no.ilike(f"%{keyword.strip()}%")
        )
    base = select(ExamCandidateAssignment).join(
        Student, Student.id == ExamCandidateAssignment.student_id,
    ).where(*filters)
    total = int((await session.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one())
    assignments = list((await session.execute(
        base.order_by(
            ExamCandidateAssignment.exam_date,
            ExamCandidateAssignment.session_index,
            ExamCandidateAssignment.room_name,
            ExamCandidateAssignment.seat_no,
        ).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all())
    student_map = {
        item.id: item for item in (await session.execute(select(Student).where(
            Student.id.in_([row.student_id for row in assignments]),
        ))).scalars().all()
    } if assignments else {}
    subject_map = dict((await session.execute(select(Subject.id, Subject.name))).all())
    grade_map = dict((await session.execute(select(Grade.id, Grade.name))).all())
    items = []
    for row in assignments:
        student = student_map.get(row.student_id)
        data = row.model_dump()
        data.update(
            student_name=student.name if student else "未知考生",
            student_no=student.student_no if student else None,
            subject_name=subject_map.get(row.subject_id, "未知学科"),
            grade_name=grade_map.get(row.grade_id, "未知年级"),
        )
        items.append(data)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
        },
    }


@router.get("/{exam_id}", summary="查询考试日期表")
async def get_schedule(
    exam_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    await _exam_or_404(session, exam_id, tenant_id)
    items = list((await session.execute(select(ExamSchedule).where(
        ExamSchedule.exam_id == exam_id,
    ).order_by(ExamSchedule.exam_date, ExamSchedule.session_index, ExamSchedule.grade_id))).scalars().all())
    return {"code": 0, "message": "ok", "data": await _output(session, items)}


class AdjustRoomIn(BaseModel):
    room_name: str | None = Field(default=None, min_length=1, max_length=100)
    invigilator_ids: list[int] | None = Field(default=None, min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_adjustment(self):
        if self.room_name is None and self.invigilator_ids is None:
            raise ValueError("请选择考场或监考教师")
        if self.invigilator_ids and len(set(self.invigilator_ids)) != len(self.invigilator_ids):
            raise ValueError("监考教师不能重复")
        return self


class AdjustSeatIn(BaseModel):
    room_assignment_id: int
    seat_no: int = Field(ge=1)
    swap: bool = False


class SwapInvigilatorsIn(BaseModel):
    first_room_id: int
    first_teacher_id: int
    second_room_id: int
    second_teacher_id: int

    @model_validator(mode='after')
    def distinct_assignments(self):
        if self.first_room_id == self.second_room_id or self.first_teacher_id == self.second_teacher_id:
            raise ValueError('请选择两位不同教师的两个监考安排')
        return self


@router.post('/plans/{exam_id}/invigilators/swap', summary='校验后原子交换两位教师的监考场次')
async def swap_invigilators(exam_id: int, body: SwapInvigilatorsIn,
                           session: AsyncSession = Depends(get_session), user=Depends(get_current_user),
                           tenant_id: int = Depends(get_current_tenant)):
    await lock_exam(session, exam_id, tenant_id)
    ctx = await context(session, tenant_id, exam_id)
    own = {r.id: r for r in ctx['ExamRoomAssignment'] if r.exam_id == exam_id}
    first, second = own.get(body.first_room_id), own.get(body.second_room_id)
    if not first or not second:
        raise HTTPException(404, '监考安排不存在')
    if body.first_teacher_id not in first.invigilator_ids or body.second_teacher_id not in second.invigilator_ids:
        raise HTTPException(409, '教师监考安排已变化，请刷新后重新选择')
    proposed = [first.model_copy(update={'invigilator_ids': [body.second_teacher_id if t == body.first_teacher_id else t for t in first.invigilator_ids]}),
                second.model_copy(update={'invigilator_ids': [body.first_teacher_id if t == body.second_teacher_id else t for t in second.invigilator_ids]})]
    replacements = {r.id: r for r in proposed}
    proposed_ctx = {**ctx, 'ExamRoomAssignment': [replacements.get(r.id, r) for r in ctx['ExamRoomAssignment']]}
    issues = [issue for r in proposed for issue in room_issues(r, proposed_ctx)]
    if issues:
        raise HTTPException(409, issues[0]['message'] + '；' + issues[0]['suggestion'])
    for original, changed in zip((first, second), proposed):
        original.invigilator_ids = changed.invigilator_ids
        session.add(original)
    for schedule in ctx['ExamSchedule']:
        if schedule.id in {first.exam_schedule_id, second.exam_schedule_id}:
            primary = next(r for r in proposed_ctx['ExamRoomAssignment'] if r.exam_schedule_id == schedule.id)
            schedule.invigilator_id = primary.invigilator_ids[0]
            session.add(schedule)
    await session.commit()
    return {'code': 0, 'data': {'swapped': True}}


@router.post('/plans/check', summary='检查配置是否能生成安排，不改变现有结果')
async def preflight(body: GenerateExamScheduleIn, session: AsyncSession = Depends(get_session),
                    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant)):
    return {'code': 0, 'data': await _generate_full_plan(body, session, tenant_id, preview=True)}


@router.get('/plans/{exam_id}/preview', summary='预览待生成日程，用于提前设置教师可用场次')
async def preview_calendar(exam_id: int, session: AsyncSession = Depends(get_session),
                           user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant)):
    await _exam_or_404(session, exam_id, tenant_id)
    config = (await session.execute(select(ExamSchedulingConfig).where(
        ExamSchedulingConfig.exam_id == exam_id, ExamSchedulingConfig.tenant_id == tenant_id))).scalar_one_or_none()
    if not config or not config.start_date:
        return {'code': 0, 'data': []}
    body = GenerateExamScheduleIn(exam_id=exam_id, grade_ids=config.grade_ids, start_date=config.start_date,
                                 subject_ids=config.subject_ids, candidate_mode=config.candidate_mode, schedule_mode=config.schedule_mode,
                                 excluded_dates=config.excluded_dates, sessions=config.sessions or
                                 [{'start_time': '09:00', 'end_time': '11:00'}, {'start_time': '14:30', 'end_time': '16:30'}],
                                 invigilators_per_room=config.invigilators_per_room,
                                 rules=ExamRules.model_validate(config.rules or {}).model_dump())
    return {'code': 0, 'data': await _generate_full_plan(body, session, tenant_id, calendar_only=True)}


@router.get('/exams/{exam_id}/subjects', summary='本次考试可选择的教学科目')
async def exam_subjects(exam_id: int, session: AsyncSession = Depends(get_session),
                        user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant)):
    exam = await _exam_or_404(session, exam_id, tenant_id)
    rows = (await session.execute(select(Subject.id, Subject.name, Class.grade_id).join(
        CourseHourPlan, CourseHourPlan.subject_id == Subject.id).join(Class, Class.id == CourseHourPlan.class_id).where(
        Subject.tenant_id == tenant_id, Class.tenant_id == tenant_id, CourseHourPlan.tenant_id == tenant_id,
        CourseHourPlan.academic_year == exam.academic_year, CourseHourPlan.term == exam.term,
        CourseHourPlan.weekly_periods > 0).distinct().order_by(Subject.id))).all()
    options = {}
    for subject_id, name, grade_id in rows:
        options.setdefault(subject_id, {'id': subject_id, 'name': name, 'grade_ids': []})['grade_ids'].append(grade_id)
    return {'code': 0, 'data': list(options.values())}


@router.get('/plans/{exam_id}/checks', summary='检查已生成安排，返回具体冲突与处理建议')
async def plan_checks(exam_id: int, session: AsyncSession = Depends(get_session),
                      user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant)):
    await _exam_or_404(session, exam_id, tenant_id)
    return {'code': 0, 'data': await check_plan(session, exam_id, tenant_id)}


@router.get('/plans/{exam_id}/overview', summary='统筹同日期学校考试的日程、考场与监考占用')
async def planning_overview(exam_id: int, session: AsyncSession = Depends(get_session),
                           user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant)):
    await _exam_or_404(session, exam_id, tenant_id)
    own = list((await session.execute(select(ExamSchedule).where(
        ExamSchedule.tenant_id == tenant_id, ExamSchedule.exam_id == exam_id))).scalars().all())
    config = (await session.execute(select(ExamSchedulingConfig).where(
        ExamSchedulingConfig.tenant_id == tenant_id, ExamSchedulingConfig.exam_id == exam_id))).scalar_one_or_none()
    preview = []
    if not own and config and config.start_date:
        result = await preview_calendar(exam_id, session, user, tenant_id)
        preview = result['data']
    dates = {s.exam_date for s in own} | {s['exam_date'] for s in preview}
    ctx = await context(session, tenant_id, exam_id, dates)
    exams = {e.id: e.name for e in ctx['Exam']}
    grades = dict((await session.execute(select(Grade.id, Grade.name).where(Grade.tenant_id == tenant_id))).all())
    subjects = dict((await session.execute(select(Subject.id, Subject.name).where(Subject.tenant_id == tenant_id))).all())
    staff = {u.id: u.name for u in ctx['User']}
    schedules = {s.id: s for s in ctx['ExamSchedule']}
    calendar = [{**s.model_dump(), 'exam_name': exams.get(s.exam_id, ''),
                 'grade_name': grades.get(s.grade_id, ''), 'subject_name': subjects.get(s.subject_id, '')}
                for s in schedules.values()]
    calendar.extend({**s, 'id': -s['id']-1, 'exam_id': exam_id, 'exam_name': exams[exam_id], 'preview': True} for s in preview)
    rooms = [{**r.model_dump(), 'exam_name': exams.get(r.exam_id, ''),
              'grade_name': grades.get(r.grade_id, ''), 'subject_name': subjects.get(r.subject_id, ''),
              'start_time': schedules[r.exam_schedule_id].start_time, 'end_time': schedules[r.exam_schedule_id].end_time,
              'invigilator_names': [staff.get(t, '未知教师') for t in r.invigilator_ids]}
             for r in ctx['ExamRoomAssignment'] if r.exam_schedule_id in schedules]
    availability = {a.teacher_id: a for a in ctx['ExamInvigilatorAvailability'] if a.exam_id == exam_id}
    return {'code': 0, 'data': {'schedules': calendar, 'rooms': rooms,
        'venues': [{'name': v.name, 'capacity': exam_seat_capacity(min(v.capacity, next((r.capacity for r in ctx['ExamRoom'] if r.name == v.name and not r.is_deleted), v.capacity)), ExamRules.model_validate(config.rules if config else {})),
                    'status': next((r.status for r in ctx['ExamRoom'] if r.name == v.name and not r.is_deleted), 'disabled')}
                   for v in ctx['ExamVenue'] if v.exam_id == exam_id],
        'teachers': [{'id': u.id, 'name': u.name,
                      'leave_start': availability[u.id].leave_start if u.id in availability else None,
                      'leave_end': availability[u.id].leave_end if u.id in availability else None,
                      'unavailable_slots': availability[u.id].unavailable_slots if u.id in availability else []}
                     for u in ctx['User'] if u.role == 'teacher' and u.status == 'active'
                     and not u.frozen and (u.id not in availability or availability[u.id].enabled)],
        'rules': ExamRules.model_validate(config.rules if config else {}).model_dump()}}


@router.patch('/plans/{exam_id}/rooms/{assignment_id}', summary='更换考场或监考教师')
async def adjust_room(exam_id: int, assignment_id: int, body: AdjustRoomIn,
                      session: AsyncSession = Depends(get_session), user=Depends(get_current_user),
                      tenant_id: int = Depends(get_current_tenant)):
    await lock_exam(session, exam_id, tenant_id)
    ctx = await context(session, tenant_id, exam_id)
    room = next((r for r in ctx['ExamRoomAssignment'] if r.id == assignment_id and r.exam_id == exam_id), None)
    if not room:
        raise HTTPException(404, '考场安排不存在')
    # Validate a detached copy before touching persisted rows.
    proposed = room.model_copy()
    if body.room_name is not None:
        name = body.room_name.strip()
        venue = next((v for v in ctx['ExamVenue'] if v.exam_id == exam_id and v.name == name), None)
        catalog = next((r for r in ctx['ExamRoom'] if r.name == name and not r.is_deleted), None)
        if not venue or not catalog or catalog.status != 'available':
            raise HTTPException(409, '请在已确认的可用考场中选择')
        proposed.room_name = name
        config = next((c for c in ctx['ExamSchedulingConfig'] if c.exam_id == exam_id), None)
        rules = ExamRules.model_validate(config.rules if config else {})
        proposed.capacity = exam_seat_capacity(min(venue.capacity, catalog.capacity), rules)
    if body.invigilator_ids is not None:
        proposed.invigilator_ids = body.invigilator_ids
    # Candidate names change with the room, so validate their prospective values.
    proposed_ctx = dict(ctx)
    proposed_ctx['ExamCandidateAssignment'] = [c.model_copy(update={'room_name': proposed.room_name})
        if c.exam_room_assignment_id == room.id else c for c in ctx['ExamCandidateAssignment']]
    issues = room_issues(proposed, proposed_ctx)
    if issues:
        raise HTTPException(409, issues[0]['message'] + '；' + issues[0]['suggestion'])
    room.room_name, room.capacity, room.invigilator_ids = proposed.room_name, proposed.capacity, proposed.invigilator_ids
    session.add(room)
    for candidate in ctx['ExamCandidateAssignment']:
        if candidate.exam_room_assignment_id == room.id:
            candidate.room_name = room.room_name
            session.add(candidate)
    schedule = next(s for s in ctx['ExamSchedule'] if s.id == room.exam_schedule_id)
    schedule.invigilator_id = room.invigilator_ids[0]
    session.add(schedule)
    await session.commit()
    return {'code': 0, 'data': room.model_dump()}


@router.patch('/plans/{exam_id}/candidates/{assignment_id}', summary='移动考生座位或明确交换两名考生')
async def adjust_seat(exam_id: int, assignment_id: int, body: AdjustSeatIn,
                      session: AsyncSession = Depends(get_session), user=Depends(get_current_user),
                      tenant_id: int = Depends(get_current_tenant)):
    await lock_exam(session, exam_id, tenant_id)
    ctx = await context(session, tenant_id, exam_id)
    candidate = next((c for c in ctx['ExamCandidateAssignment'] if c.id == assignment_id and c.exam_id == exam_id), None)
    target = next((r for r in ctx['ExamRoomAssignment'] if r.id == body.room_assignment_id and r.exam_id == exam_id), None)
    if not candidate or not target:
        raise HTTPException(404, '考生或考场安排不存在')
    if target.exam_schedule_id != candidate.exam_schedule_id:
        raise HTTPException(409, '只能调整到同年级、同科目、同场次的考场')
    catalog = next((r for r in ctx['ExamRoom'] if r.name == target.room_name and not r.is_deleted), None)
    venue = next((v for v in ctx['ExamVenue'] if v.exam_id == exam_id and v.name == target.room_name), None)
    if not catalog or catalog.status != 'available' or not venue:
        raise HTTPException(409, '目标考场已不可用或不在本次考场范围，请更换考场')
    config = next((c for c in ctx['ExamSchedulingConfig'] if c.exam_id == exam_id), None)
    rules = ExamRules.model_validate(config.rules if config else {})
    capacity = exam_seat_capacity(min(target.capacity, catalog.capacity, venue.capacity), rules)
    if body.seat_no > capacity:
        raise HTTPException(409, f'座位号不能超过考场容量 {capacity}')
    occupant = next((c for c in ctx['ExamCandidateAssignment'] if c.exam_room_assignment_id == target.id
                     and c.seat_no == body.seat_no and c.id != candidate.id), None)
    if occupant and not body.swap:
        raise HTTPException(409, '座位已有考生，请选择空座位或启用交换座位')
    old_room_id, old_seat, old_name = candidate.exam_room_assignment_id, candidate.seat_no, candidate.room_name
    if occupant:
        source = next(r for r in ctx['ExamRoomAssignment'] if r.id == old_room_id)
        source_catalog = next((r for r in ctx['ExamRoom'] if r.name == source.room_name and not r.is_deleted), None)
        if not source_catalog or source_catalog.status != 'available' or old_seat > min(source.capacity, source_catalog.capacity):
            raise HTTPException(409, '原座位已不可用，不能交换；请将考生移到空座位')
        occupant.exam_room_assignment_id, occupant.seat_no, occupant.room_name = old_room_id, old_seat, old_name
        session.add(occupant)
    candidate.exam_room_assignment_id, candidate.seat_no, candidate.room_name = target.id, body.seat_no, target.room_name
    session.add(candidate)
    for room in ctx['ExamRoomAssignment']:
        if room.id in {old_room_id, target.id}:
            room.candidate_count = sum(c.exam_room_assignment_id == room.id for c in ctx['ExamCandidateAssignment'])
            session.add(room)
    await session.commit()
    return {'code': 0, 'data': candidate.model_dump()}


@router.get('/plans/{exam_id}/admission-tickets', summary='按考生分页的准考证，包含所有科目')
async def admission_tickets(exam_id: int, grade_id: int | None = None, class_id: int | None = None,
                            keyword: str = '', page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200),
                            session: AsyncSession = Depends(get_session), user=Depends(get_current_user),
                            tenant_id: int = Depends(get_current_tenant)):
    exam = await _exam_or_404(session, exam_id, tenant_id)
    # A stable read against the same lock used by seat/resource changes.
    await session.execute(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    check = await check_plan(session, exam_id, tenant_id)
    if not check['ok']:
        raise HTTPException(409, '打印前请处理冲突：' + check['issues'][0]['message'])
    filters = [ExamCandidateAssignment.exam_id == exam_id, ExamCandidateAssignment.tenant_id == tenant_id,
               Student.tenant_id == tenant_id]
    if grade_id: filters.append(ExamCandidateAssignment.grade_id == grade_id)
    if class_id: filters.append(Student.class_id == class_id)
    if keyword.strip(): filters.append(Student.name.ilike(f'%{keyword.strip()}%') | Student.student_no.ilike(f'%{keyword.strip()}%'))
    student_query = select(Student).join(ExamCandidateAssignment, Student.id == ExamCandidateAssignment.student_id).where(*filters).distinct()
    total = (await session.execute(select(func.count()).select_from(student_query.subquery()))).scalar_one()
    students = list((await session.execute(student_query.order_by(Student.class_id, Student.roster_order, Student.id)
        .offset((page - 1) * page_size).limit(page_size))).scalars().all())
    assignments = list((await session.execute(select(ExamCandidateAssignment).where(
        ExamCandidateAssignment.tenant_id == tenant_id, ExamCandidateAssignment.exam_id == exam_id,
        ExamCandidateAssignment.student_id.in_([s.id for s in students])).order_by(
        ExamCandidateAssignment.exam_date, ExamCandidateAssignment.start_time))).scalars().all())
    subjects = dict((await session.execute(select(Subject.id, Subject.name).where(Subject.tenant_id == tenant_id))).all())
    classes = dict((await session.execute(select(Class.id, Class.name).where(Class.tenant_id == tenant_id))).all())
    grades = dict((await session.execute(select(Grade.id, Grade.name).where(Grade.tenant_id == tenant_id))).all())
    school = await session.get(Tenant, tenant_id)
    items = [dict(student_id=s.id, student_name=s.name, student_no=s.student_no,
                  candidate_no=f'E{exam_id:06d}{s.id:08d}', class_name=classes.get(s.class_id, ''),
                  grade_name=grades.get(s.grade_id, ''), sessions=[dict(subject_name=subjects.get(c.subject_id, ''),
                  exam_date=c.exam_date, start_time=c.start_time, end_time=c.end_time, room_name=c.room_name,
                  seat_no=c.seat_no) for c in assignments if c.student_id == s.id]) for s in students]
    import hashlib
    snapshot = list((await session.execute(select(ExamCandidateAssignment).where(
        ExamCandidateAssignment.exam_id == exam_id, ExamCandidateAssignment.tenant_id == tenant_id)
        .order_by(ExamCandidateAssignment.id))).scalars().all())
    revision = hashlib.sha256(repr([(c.id, c.student_id, c.exam_date, c.start_time, c.end_time,
                                     c.room_name, c.seat_no) for c in snapshot]).encode()).hexdigest()
    class_options = (await session.execute(select(Class.id, Class.name, Class.grade_id).join(
        Student, Student.class_id == Class.id).join(ExamCandidateAssignment, ExamCandidateAssignment.student_id == Student.id).where(
        Class.tenant_id == tenant_id, Student.tenant_id == tenant_id,
        ExamCandidateAssignment.tenant_id == tenant_id, ExamCandidateAssignment.exam_id == exam_id).distinct().order_by(Class.id))).all()
    return {'code': 0, 'data': dict(exam_name=exam.name, school_name=school.name if school else '', revision=revision, items=items,
        class_options=[dict(id=id, name=name, grade_id=grade) for id, name, grade in class_options],
        pagination=dict(page=page, page_size=page_size, total=total, total_pages=(total + page_size - 1) // page_size))}
