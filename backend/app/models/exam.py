"""考试域模型
exam / paper / question
"""
from datetime import date, datetime
from sqlmodel import SQLModel, Field
from sqlalchemy import JSON, UniqueConstraint

from app.db.base import SoftDeleteMixin, TimestampMixin, TenantMixin
from app.models.enums import (
    ExamStatus, ExamType,
)


class Exam(TimestampMixin, TenantMixin, SQLModel, table=True):
    """考试（教务处统一组织）"""
    __table_args__ = {"comment": "考试"}
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, description="如 十月月考")
    exam_type: ExamType = Field(default=ExamType.monthly)
    academic_year: str = Field(max_length=20)
    term: str = Field(default="1", max_length=20)
    created_by: int | None = Field(default=None)
    status: ExamStatus = Field(default=ExamStatus.preparing)


class ExamSchedule(TimestampMixin, TenantMixin, SQLModel, table=True):
    """考试日期与监考安排"""
    __table_args__ = (
        UniqueConstraint("exam_id", "grade_id", "session_index", name="uq_examschedule_grade_session"),
        {"comment": "考试日程"},
    )
    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True)
    grade_id: int = Field(index=True)
    subject_id: int = Field(index=True)
    exam_date: date = Field(index=True)
    session_index: int = Field(default=1)
    start_time: str = Field(max_length=5)
    end_time: str = Field(max_length=5)
    room: str = Field(default="各班教室", max_length=100)
    invigilator_id: int | None = Field(default=None, index=True)


class ExamVenue(TimestampMixin, TenantMixin, SQLModel, table=True):
    """A confirmed physical venue available to one exam."""
    __table_args__ = (
        UniqueConstraint("tenant_id", "exam_id", "name", name="uq_examvenue_exam_name"),
        {"comment": "考试考场配置"},
    )
    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True)
    name: str = Field(max_length=100)
    capacity: int = Field(ge=1)
    source_type: str = Field(default="custom", max_length=20)
    source_class_id: int | None = Field(default=None, index=True)
    confirmed_at: datetime = Field(default_factory=datetime.utcnow)


class ExamRoom(TimestampMixin, TenantMixin, SoftDeleteMixin, SQLModel, table=True):
    """School-wide exam room resource managed before scheduling."""
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_examroom_tenant_name"),
        {"comment": "学校考场资源"},
    )
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    capacity: int = Field(default=40, ge=1)
    building: str | None = Field(default=None, max_length=100)
    room_type: str = Field(default="standard", max_length=20)
    status: str = Field(default="available", max_length=20, index=True)
    source_class_id: int | None = Field(default=None, index=True)


class ExamSchedulingConfig(TimestampMixin, TenantMixin, SQLModel, table=True):
    """Persisted scope and calendar settings for one exam scheduling task."""
    __table_args__ = (UniqueConstraint("tenant_id", "exam_id", name="uq_examschedulingconfig_exam"),)
    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True)
    grade_ids: list[int] = Field(default_factory=list, sa_type=JSON)
    start_date: date | None = Field(default=None)
    excluded_dates: list[str] = Field(default_factory=list, sa_type=JSON)
    sessions: list[dict] = Field(default_factory=list, sa_type=JSON)
    invigilators_per_room: int = Field(default=1, ge=1, le=3)


class ExamInvigilatorAvailability(TimestampMixin, TenantMixin, SQLModel, table=True):
    """One teacher's availability constraints for a specific exam."""
    __table_args__ = (UniqueConstraint("tenant_id", "exam_id", "teacher_id", name="uq_examinvigilator_exam_teacher"),)
    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True)
    teacher_id: int = Field(index=True)
    enabled: bool = Field(default=True)
    leave_start: date | None = Field(default=None)
    leave_end: date | None = Field(default=None)
    unavailable_slots: list[str] = Field(default_factory=list, sa_type=JSON)
    note: str | None = Field(default=None, max_length=200)


class ExamRoomAssignment(TimestampMixin, TenantMixin, SQLModel, table=True):
    """A physical room opened for one paper session."""
    __table_args__ = (
        UniqueConstraint("exam_schedule_id", "room_name", name="uq_examroom_schedule_room"),
        {"comment": "考试考场安排"},
    )
    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True)
    exam_schedule_id: int = Field(index=True)
    grade_id: int = Field(index=True)
    subject_id: int = Field(index=True)
    exam_date: date = Field(index=True)
    session_index: int = Field(index=True)
    room_name: str = Field(max_length=100)
    capacity: int = Field(ge=1)
    candidate_count: int = Field(default=0, ge=0)
    invigilator_ids: list[int] = Field(default_factory=list, sa_type=JSON)


class ExamCandidateAssignment(TimestampMixin, TenantMixin, SQLModel, table=True):
    """The auditable result: who takes which subject, when, where and in which seat."""
    __table_args__ = (
        UniqueConstraint("exam_id", "grade_id", "subject_id", "student_id", name="uq_examcandidate_subject_student"),
        {"comment": "考试考生座位安排"},
    )
    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True)
    exam_schedule_id: int = Field(index=True)
    exam_room_assignment_id: int = Field(index=True)
    grade_id: int = Field(index=True)
    subject_id: int = Field(index=True)
    student_id: int = Field(index=True)
    exam_date: date = Field(index=True)
    session_index: int = Field(index=True)
    start_time: str = Field(max_length=5)
    end_time: str = Field(max_length=5)
    room_name: str = Field(max_length=100)
    seat_no: int = Field(ge=1)
