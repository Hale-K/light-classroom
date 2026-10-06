"""Grade and semester scoped time structure, independent of school settings JSON."""
from datetime import date

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.base import TenantMixin, TimestampMixin


class SchedulingGridPlan(TimestampMixin, TenantMixin, SQLModel, table=True):
    __tablename__ = "scheduling_grid_plan"
    __table_args__ = (
        UniqueConstraint("tenant_id", "grade_id", "academic_year", "term", name="uq_grid_plan_scope"),
        CheckConstraint("term IN ('1', '2')", name="ck_grid_plan_term"),
        CheckConstraint("first_week_parity IN ('odd', 'even')", name="ck_grid_plan_parity"),
    )
    id: int | None = Field(default=None, primary_key=True)
    grade_id: int = Field(foreign_key="grade.id", ondelete="RESTRICT", index=True)
    academic_year: str = Field(max_length=20)
    term: str = Field(max_length=1)
    first_week_parity: str = Field(default="odd", max_length=4)
    term_start_monday: date | None = None
    evening_start_period: int | None = None


class SchedulingGridDay(SQLModel, table=True):
    __tablename__ = "scheduling_grid_day"
    __table_args__ = (
        UniqueConstraint("plan_id", "weekday", name="uq_grid_plan_day"),
        CheckConstraint("weekday BETWEEN 1 AND 7", name="ck_grid_day_weekday"),
        CheckConstraint("daytime_periods BETWEEN 0 AND 12", name="ck_grid_day_periods"),
        CheckConstraint("evening_odd BETWEEN 0 AND 3 AND evening_even BETWEEN 0 AND 3", name="ck_grid_day_evening"),
    )
    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="scheduling_grid_plan.id", ondelete="CASCADE", index=True)
    weekday: int
    daytime_periods: int
    evening_odd: int = 0
    evening_even: int = 0


class SchedulingGridSubject(SQLModel, table=True):
    """Existing evening subject restrictions; weekday=0 means the entire parity."""
    __tablename__ = "scheduling_grid_subject"
    __table_args__ = (
        UniqueConstraint("plan_id", "parity", "weekday", "subject_id", name="uq_grid_subject_scope"),
        CheckConstraint("weekday BETWEEN 0 AND 7", name="ck_grid_subject_weekday"),
        CheckConstraint("parity IN ('odd', 'even')", name="ck_grid_subject_parity"),
    )
    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="scheduling_grid_plan.id", ondelete="CASCADE", index=True)
    parity: str = Field(max_length=4)
    weekday: int = 0
    subject_id: int = Field(foreign_key="subject.id", ondelete="RESTRICT")


class SchedulingGridSlot(SQLModel, table=True):
    """Overrides to a slider-generated slot, stored independently for each parity."""
    __tablename__ = "scheduling_grid_slot"
    __table_args__ = (
        UniqueConstraint("plan_id", "weekday", "period", "week_parity", name="uq_grid_slot_leg"),
        CheckConstraint("weekday BETWEEN 1 AND 7 AND period BETWEEN 1 AND 12", name="ck_grid_slot_position"),
        CheckConstraint("week_parity IN ('odd', 'even')", name="ck_grid_slot_parity"),
        CheckConstraint("slot_type IN ('daytime', 'evening', 'disabled')", name="ck_grid_slot_type"),
    )
    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="scheduling_grid_plan.id", ondelete="CASCADE", index=True)
    weekday: int
    period: int
    week_parity: str = Field(max_length=4)
    slot_type: str = Field(max_length=8)
