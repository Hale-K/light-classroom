"""排考 API：从考试试卷生成日期、场次、考场和监考安排。"""
from datetime import date

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
from app.models.org import Class, CourseHourPlan, Grade, Student, Subject, Tenant, User
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
        if self.start_time >= self.end_time:
            raise ValueError("场次结束时间必须晚于开始时间")
        return self


class ExamRoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    capacity: int = Field(default=40, ge=1, le=500)
    source_type: str = Field(default="custom", pattern=r"^(classroom|custom)$")
    source_class_id: int | None = None


class SaveExamVenuesIn(BaseModel):
    rooms: list[ExamRoomIn] = Field(min_length=1, max_length=300)


class ExamRoomCatalogIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    capacity: int = Field(default=40, ge=1, le=500)
    building: str | None = Field(default=None, max_length=100)
    room_type: str = Field(default="standard", pattern=r"^(standard|special|reserve)$")
    status: str = Field(default="available", pattern=r"^(available|maintenance|disabled)$")


class ExamRoomCatalogUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    capacity: int | None = Field(default=None, ge=1, le=500)
    building: str | None = Field(default=None, max_length=100)
    room_type: str | None = Field(default=None, pattern=r"^(standard|special|reserve)$")
    status: str | None = Field(default=None, pattern=r"^(available|maintenance|disabled)$")


class ExamSchedulingConfigIn(BaseModel):
    grade_ids: list[int] = Field(min_length=1, max_length=10)
    start_date: date | None = None
    excluded_dates: list[date] = Field(default_factory=list, max_length=30)
    sessions: list[SessionIn] = Field(default_factory=list, max_length=4)
    invigilators_per_room: int = Field(default=1, ge=1, le=3)


class ExamInvigilatorAvailabilityIn(BaseModel):
    enabled: bool = True
    leave_start: date | None = None
    leave_end: date | None = None
    unavailable_slots: list[str] = Field(default_factory=list, max_length=100)
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_leave_range(self):
        if self.leave_start and self.leave_end and self.leave_start > self.leave_end:
            raise ValueError("休假开始日期不能晚于结束日期")
        return self


class GenerateExamScheduleIn(BaseModel):
    exam_id: int
    grade_ids: list[int] = Field(default_factory=list, max_length=10)
    start_date: date
    room: str = Field(default="各班教室", min_length=1, max_length=100)
    excluded_dates: list[date] = Field(default_factory=list, max_length=30)
    sessions: list[SessionIn] = Field(default_factory=lambda: [
        SessionIn(start_time="09:00", end_time="11:00"),
        SessionIn(start_time="14:30", end_time="16:30"),
    ], min_length=1, max_length=4)
    rooms: list[ExamRoomIn] = Field(default_factory=list, max_length=300)
    invigilators_per_room: int = Field(default=1, ge=1, le=3)


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
    if configured:
        names = [item.name.strip() for item in configured]
        catalog = list((await session.execute(select(ExamRoom).where(
            ExamRoom.tenant_id == tenant_id,
            ExamRoom.name.in_(names),
            ExamRoom.is_deleted == False,  # noqa: E712
        ))).scalars().all())
        blocked = [item.name for item in catalog if item.status != "available"]
        if blocked:
            raise ValueError(f"以下考场当前不可用：{', '.join(blocked)}")
        return normalize_exam_room_resources([
            ExamRoomResource(name=item.name, capacity=item.capacity) for item in configured
        ])
    saved = list((await session.execute(select(ExamVenue).where(
        ExamVenue.tenant_id == tenant_id,
        ExamVenue.exam_id == exam_id,
    ).order_by(ExamVenue.id))).scalars().all())
    if saved:
        return [ExamRoomResource(name=item.name, capacity=item.capacity) for item in saved]
    classes = list((await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
    ).order_by(Class.grade_id, Class.id))).scalars().all())
    return [ExamRoomResource(name=f"{item.name}教室", capacity=40) for item in classes]


async def _candidate_rosters(
    session: AsyncSession,
    tenant_id: int,
    exam: Exam,
    papers: list[dict],
    subject_names: dict[int, str],
) -> tuple[dict[int, list[int]], int]:
    grade_ids = {int(item["grade_id"]) for item in papers}
    classes = list((await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.grade_id.in_(grade_ids),
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

    choices = list((await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == tenant_id,
        StudentSubjectChoice.student_id.in_([item.id for item in students]),
        StudentSubjectChoice.academic_year == exam.academic_year,
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
    missing_choice_count = sum(
        not selected_by_student.get(student.id)
        for student in students
        if elective_subject_ids
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
    for item in rooms:
        row = item.model_dump()
        row.update(
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
):
    exam = await session.get(Exam, body.exam_id)
    if not exam or exam.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="考试不存在")
    saved_config = (await session.execute(select(ExamSchedulingConfig).where(
        ExamSchedulingConfig.tenant_id == tenant_id,
        ExamSchedulingConfig.exam_id == body.exam_id,
    ))).scalar_one_or_none()
    effective_grade_ids = body.grade_ids or (saved_config.grade_ids if saved_config else [])
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
    course_rows = (await session.execute(course_stmt)).all()
    course_pairs = sorted({(int(grade_id), int(plan.subject_id)) for plan, grade_id in course_rows})
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
    ).order_by(User.id))).scalars().all())
    teacher_ids = select_invigilator_ids(teachers)
    try:
        generated = generate_exam_schedule(
            courses,
            start_date=body.start_date,
            teacher_ids=teacher_ids,
            sessions=tuple((item.start_time, item.end_time) for item in body.sessions),
            room=body.room,
            excluded_dates=set(body.excluded_dates),
            mode=school.gaokao_mode,
            subject_names=subject_names,
        )
        candidate_rosters, missing_choice_count = await _candidate_rosters(
            session, tenant_id, exam, courses, subject_names,
        )
        if missing_choice_count:
            raise ValueError(f"有 {missing_choice_count} 名考生未完成确认选科，不能生成选考科目考场")
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
                slot_key = f"{item.exam_date.isoformat()}#{item.session_index}"
                on_leave = bool(setting.leave_start and setting.leave_end and setting.leave_start <= item.exam_date <= setting.leave_end)
                if on_leave or slot_key in setting.unavailable_slots:
                    blocked.add((item.exam_date, item.session_index))
            if blocked:
                unavailable_teacher_slots[teacher_id] = blocked
        room_resources = await _room_resources(session, tenant_id, body.exam_id, body.rooms)
        arrangement = arrange_exam_candidates(
            generated,
            candidate_ids_by_paper=candidate_rosters,
            rooms=room_resources,
            teacher_ids=teacher_ids,
            unavailable_teacher_slots=unavailable_teacher_slots,
            invigilators_per_room=body.invigilators_per_room,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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


async def _ensure_exam_room_catalog(session: AsyncSession, tenant_id: int) -> None:
    existing_count = int((await session.execute(select(func.count(ExamRoom.id)).where(
        ExamRoom.tenant_id == tenant_id,
    ))).scalar_one())
    if existing_count:
        return
    classes = list((await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
    ).order_by(Class.grade_id, Class.id))).scalars().all())
    session.add_all([ExamRoom(
        tenant_id=tenant_id,
        name=f"{item.name}教室",
        capacity=40,
        room_type="standard",
        source_class_id=item.id,
    ) for item in classes])
    await session.commit()


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
    await _exam_or_404(session, exam_id, tenant_id)
    config = (await session.execute(select(ExamSchedulingConfig).where(
        ExamSchedulingConfig.tenant_id == tenant_id,
        ExamSchedulingConfig.exam_id == exam_id,
    ))).scalar_one_or_none()
    if config:
        return {"code": 0, "message": "ok", "data": config.model_dump()}
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
        "start_date": None,
        "excluded_dates": [],
        "sessions": [{"start_time": "09:00", "end_time": "11:00"}, {"start_time": "14:30", "end_time": "16:30"}],
        "invigilators_per_room": 1,
    }}


@router.put("/exams/{exam_id}/config", summary="保存排考范围与日程配置")
async def save_exam_config(
    exam_id: int,
    body: ExamSchedulingConfigIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    await _exam_or_404(session, exam_id, tenant_id)
    exam = await _exam_or_404(session, exam_id, tenant_id)
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
    config = (await session.execute(select(ExamSchedulingConfig).where(
        ExamSchedulingConfig.tenant_id == tenant_id,
        ExamSchedulingConfig.exam_id == exam_id,
    ))).scalar_one_or_none() or ExamSchedulingConfig(tenant_id=tenant_id, exam_id=exam_id)
    config.grade_ids = list(dict.fromkeys(body.grade_ids))
    config.start_date = body.start_date
    config.excluded_dates = [item.isoformat() for item in body.excluded_dates]
    config.sessions = [item.model_dump() for item in body.sessions]
    config.invigilators_per_room = body.invigilators_per_room
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
        state = "disabled" if teacher.status != UserStatus.active else "excluded" if not enabled else "leave" if on_leave else "assigned" if assigned_count.get(teacher.id, 0) else "available"
        items.append({
            "teacher_id": teacher.id, "teacher_name": teacher.name,
            "account_status": teacher.status.value, "enabled": enabled,
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
    await _exam_or_404(session, exam_id, tenant_id)
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
    await _ensure_exam_room_catalog(session, tenant_id)
    filters = [ExamRoom.tenant_id == tenant_id, ExamRoom.is_deleted == False]  # noqa: E712
    if keyword.strip():
        filters.append(ExamRoom.name.ilike(f"%{keyword.strip()}%"))
    total = int((await session.execute(select(func.count(ExamRoom.id)).where(*filters))).scalar_one())
    items = list((await session.execute(select(ExamRoom).where(*filters).order_by(
        ExamRoom.source_class_id.is_(None), ExamRoom.id,
    ).offset((page - 1) * page_size).limit(page_size))).scalars().all())
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


@router.post("/rooms", status_code=201, summary="新建考场资源")
async def create_exam_room(
    body: ExamRoomCatalogIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    name = body.name.strip()
    existing = (await session.execute(select(ExamRoom).where(
        ExamRoom.tenant_id == tenant_id,
        ExamRoom.name == name,
    ))).scalars().first()
    if existing and not existing.is_deleted:
        raise HTTPException(status_code=409, detail="考场名称已存在")
    room = existing or ExamRoom(tenant_id=tenant_id, name=name)
    room.name = name
    room.capacity = body.capacity
    room.building = body.building.strip() if body.building else None
    room.room_type = body.room_type
    room.status = body.status
    room.source_class_id = None
    room.is_deleted = False
    session.add(room)
    await session.commit()
    await session.refresh(room)
    return {"code": 0, "message": "ok", "data": _exam_room_output(room)}


@router.patch("/rooms/{room_id}", summary="修改考场资源")
async def update_exam_room(
    room_id: int,
    body: ExamRoomCatalogUpdate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    room = await session.get(ExamRoom, room_id)
    if not room or room.tenant_id != tenant_id or room.is_deleted:
        raise HTTPException(status_code=404, detail="考场不存在")
    values = body.model_dump(exclude_unset=True)
    if "name" in values:
        name = values["name"].strip()
        duplicate = (await session.execute(select(ExamRoom.id).where(
            ExamRoom.tenant_id == tenant_id,
            ExamRoom.name == name,
            ExamRoom.id != room_id,
            ExamRoom.is_deleted == False,  # noqa: E712
        ))).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="考场名称已存在")
        values["name"] = name
    if "building" in values and values["building"]:
        values["building"] = values["building"].strip()
    for key, value in values.items():
        setattr(room, key, value)
    session.add(room)
    await session.commit()
    await session.refresh(room)
    return {"code": 0, "message": "ok", "data": _exam_room_output(room)}


@router.delete("/rooms/{room_id}", summary="删除考场资源")
async def delete_exam_room(
    room_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    room = await session.get(ExamRoom, room_id)
    if not room or room.tenant_id != tenant_id or room.is_deleted:
        raise HTTPException(status_code=404, detail="考场不存在")
    room.is_deleted = True
    session.add(room)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"id": room_id}}


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
    exam = await session.get(Exam, exam_id)
    if not exam or exam.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="考试不存在")
    try:
        normalized = normalize_exam_room_resources([
            ExamRoomResource(name=item.name, capacity=item.capacity) for item in body.rooms
        ])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    catalog = list((await session.execute(select(ExamRoom).where(
        ExamRoom.tenant_id == tenant_id,
        ExamRoom.name.in_([item.name.strip() for item in body.rooms]),
        ExamRoom.is_deleted == False,  # noqa: E712
    ))).scalars().all())
    blocked = [item.name for item in catalog if item.status != "available"]
    if blocked:
        raise HTTPException(status_code=422, detail=f"以下考场处于维护或停用状态：{', '.join(blocked)}")
    input_by_name = {item.name.strip(): item for item in body.rooms}
    await session.execute(delete(ExamVenue).where(
        ExamVenue.tenant_id == tenant_id,
        ExamVenue.exam_id == exam_id,
    ))
    venues = [ExamVenue(
        exam_id=exam_id,
        name=item.name,
        capacity=item.capacity,
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
):
    filters = [ExamCandidateAssignment.exam_id == exam_id]
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
):
    items = list((await session.execute(select(ExamSchedule).where(
        ExamSchedule.exam_id == exam_id,
    ).order_by(ExamSchedule.exam_date, ExamSchedule.session_index, ExamSchedule.grade_id))).scalars().all())
    return {"code": 0, "message": "ok", "data": await _output(session, items)}
