"""New-gaokao scheme, subject choice, teaching class, and walk schedule models."""
from datetime import datetime

from sqlalchemy import CheckConstraint, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.base import TimestampMixin, TenantMixin


class WalkSchedulingPlan(TimestampMixin, TenantMixin, SQLModel, table=True):
    __tablename__ = "walk_scheduling_plan"
    __table_args__ = (UniqueConstraint("tenant_id", "grade_id", "academic_year", "term", name="uq_walk_plan_scope"),
                     CheckConstraint("term IN ('1', '2')", name="ck_walk_plan_term"))
    id: int | None = Field(default=None, primary_key=True)
    grade_id: int = Field(foreign_key="grade.id", ondelete="RESTRICT")
    academic_year: str = Field(max_length=20)
    term: str = Field(max_length=1)
    revision: int = Field(default=1)


class WalkSchedulingSlot(SQLModel, table=True):
    __tablename__ = "walk_scheduling_slot"
    __table_args__ = (UniqueConstraint("plan_id", "weekday", "period", name="uq_walk_plan_slot"),
                     CheckConstraint("weekday BETWEEN 1 AND 7 AND period BETWEEN 1 AND 12", name="ck_walk_slot_range"))
    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="walk_scheduling_plan.id", ondelete="CASCADE", index=True)
    weekday: int
    period: int


class WalkSchedulingRoom(SQLModel, table=True):
    __tablename__ = "walk_scheduling_room"
    __table_args__ = (UniqueConstraint("plan_id", "room_id", name="uq_walk_plan_room"),)
    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="walk_scheduling_plan.id", ondelete="CASCADE", index=True)
    room_id: int = Field(foreign_key="room.id", ondelete="RESTRICT")


class GaokaoScheme(TimestampMixin, TenantMixin, SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("tenant_id", "entry_year", name="uq_gaokaoscheme_tenant_entry_year"),
        {"comment": "新高考方案"},
    )
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    province: str | None = Field(default=None, max_length=50)
    mode: str = Field(default="3+1+2", max_length=20)
    entry_year: int = Field(index=True)
    required_subject_ids: list[int] = Field(default_factory=list, sa_type=JSON)
    primary_subject_ids: list[int] = Field(default_factory=list, sa_type=JSON)
    secondary_subject_ids: list[int] = Field(default_factory=list, sa_type=JSON)
    strategy_config: dict = Field(default_factory=dict, sa_type=JSON)
    is_active: bool = Field(default=True, index=True)


class StudentSubjectChoice(TimestampMixin, TenantMixin, SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "student_id", "academic_year", "effective_term",
            name="uq_studentchoice_student_term",
        ),
        {"comment": "学生新高考选科"},
    )
    id: int | None = Field(default=None, primary_key=True)
    student_id: int = Field(index=True)
    scheme_id: int = Field(index=True)
    academic_year: str = Field(max_length=20, index=True)
    effective_term: str = Field(default="1", max_length=20)
    round_no: int = Field(default=1)
    primary_subject_id: int | None = Field(default=None, index=True)
    secondary_subject_ids: list[int] = Field(default_factory=list, sa_type=JSON)
    selected_subject_ids: list[int] = Field(default_factory=list, sa_type=JSON)
    stream: str | None = Field(default=None, max_length=20)
    status: str = Field(default="confirmed", max_length=20, index=True)
    confirmed_at: datetime | None = Field(default_factory=datetime.utcnow)


class StudentCredential(TimestampMixin, TenantMixin, SQLModel, table=True):
    """学生端登录凭证，与教职工 User 账号隔离。"""
    __table_args__ = (
        UniqueConstraint("tenant_id", "student_id", name="uq_studentcredential_student"),
        UniqueConstraint("tenant_id", "login_name", name="uq_studentcredential_login"),
        {"comment": "学生端登录凭证"},
    )
    id: int | None = Field(default=None, primary_key=True)
    student_id: int = Field(index=True, foreign_key="student.id", ondelete="CASCADE")
    login_name: str = Field(max_length=50, index=True)
    password_hash: str = Field(max_length=255)
    status: str = Field(default="active", max_length=20, index=True)
    last_login_at: datetime | None = Field(default=None)


class TeachingSubjectHourPlan(TimestampMixin, TenantMixin, SQLModel, table=True):
    """A subject's default weekly hours for one grade and semester."""
    __tablename__ = "teaching_subject_hour_plan"
    __table_args__ = (
        UniqueConstraint("tenant_id", "grade_id", "academic_year", "term", "subject_id",
                         name="uq_teaching_subject_hour_plan_scope"),
        CheckConstraint("weekly_periods BETWEEN 1 AND 12", name="ck_teaching_subject_hours_range"),
        CheckConstraint("term IN ('1', '2')", name="ck_teaching_subject_hours_term"),
        {"comment": "走班科目课时方案：先定科目课时，再生成教学班"},
    )
    id: int | None = Field(default=None, primary_key=True)
    grade_id: int = Field(foreign_key="grade.id", ondelete="RESTRICT", index=True)
    subject_id: int = Field(foreign_key="subject.id", ondelete="RESTRICT", index=True)
    academic_year: str = Field(max_length=20, index=True)
    term: str = Field(max_length=20)
    weekly_periods: int = Field(ge=1, le=12)
    weekday_periods: int | None = Field(default=None, ge=0, le=12)
    weekend_periods: int | None = Field(default=None, ge=0, le=12)


class TeachingClass(TimestampMixin, TenantMixin, SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "grade_id", "subject_id", "academic_year", "term", "sequence",
            name="uq_teachingclass_subject_sequence",
        ),
        {"comment": "新高考走班教学班"},
    )
    id: int | None = Field(default=None, primary_key=True)
    grade_id: int = Field(index=True)
    subject_id: int = Field(index=True)
    name: str = Field(max_length=100)
    academic_year: str = Field(max_length=20, index=True)
    term: str = Field(default="1", max_length=20)
    sequence: int = Field(default=1)
    capacity: int = Field(default=40)
    weekly_periods: int = Field(default=3)
    weekday_periods: int | None = Field(default=None, ge=0, le=12)
    weekend_periods: int | None = Field(default=None, ge=0, le=12)
    hour_plan_id: int | None = Field(default=None, foreign_key="teaching_subject_hour_plan.id",
                                     ondelete="SET NULL", index=True)
    hours_overridden: bool = Field(default=False, nullable=False,
                                    description="是否单独调整课时；weekly_periods为教学班实际课时")
    teacher_id: int | None = Field(default=None, index=True)
    room: str | None = Field(default=None, max_length=100)
    source: str = Field(default="selection", max_length=20)
    status: str = Field(default="draft", max_length=20, index=True)


class TeachingClassStudent(TenantMixin, SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("teaching_class_id", "student_id", name="uq_teachingclassstudent_member"),
        {"comment": "教学班学生成员"},
    )
    id: int | None = Field(default=None, primary_key=True)
    teaching_class_id: int = Field(index=True)
    student_id: int = Field(index=True)


class TeachingClassSchedule(TimestampMixin, TenantMixin, SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "teaching_class_id", "weekday", "period",
            name="uq_teachingclassschedule_slot",
        ),
        {"comment": "走班教学班课表"},
    )
    id: int | None = Field(default=None, primary_key=True)
    teaching_class_id: int = Field(index=True)
    teacher_id: int | None = Field(default=None, index=True)
    subject_id: int = Field(index=True)
    academic_year: str = Field(max_length=20, index=True)
    term: str = Field(default="1", max_length=20)
    weekday: int = Field(index=True)
    period: int = Field(index=True)
    room: str | None = Field(default=None, max_length=100)
