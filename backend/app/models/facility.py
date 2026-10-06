"""Campus, building and room resources."""
from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.base import TenantMixin, TimestampMixin


class Campus(TimestampMixin, TenantMixin, SQLModel, table=True):
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_campus_tenant_name"),)
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    address: str | None = Field(default=None, max_length=200)
    student_capacity: int | None = Field(default=None, ge=1, le=100000)
    status: str = Field(default="active", max_length=20, index=True)


class Building(TimestampMixin, TenantMixin, SQLModel, table=True):
    __table_args__ = (UniqueConstraint("tenant_id", "campus_id", "name", name="uq_building_campus_name"),)
    id: int | None = Field(default=None, primary_key=True)
    campus_id: int = Field(index=True)
    name: str = Field(max_length=100)
    code: str | None = Field(default=None, max_length=30)
    floor_count: int = Field(default=1, ge=1, le=100)
    status: str = Field(default="active", max_length=20, index=True)


class Room(TimestampMixin, TenantMixin, SQLModel, table=True):
    __table_args__ = (UniqueConstraint("tenant_id", "building_id", "name", name="uq_room_building_name"),)
    id: int | None = Field(default=None, primary_key=True)
    building_id: int = Field(index=True)
    name: str = Field(max_length=100)
    code: str | None = Field(default=None, max_length=30, index=True)
    floor: int = Field(default=1)
    capacity: int = Field(default=40, ge=1, le=5000)
    room_type: str = Field(default="classroom", max_length=30, index=True)
    features: list[str] = Field(default_factory=list, sa_type=JSON)
    is_schedulable: bool = Field(default=True)
    is_exam_enabled: bool = Field(default=False)
    status: str = Field(default="available", max_length=20, index=True)


class ResourceAllocationRule(TimestampMixin, TenantMixin, SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    cohort_label: str = Field(max_length=30, index=True)
    academic_year: str = Field(default="2026-2027", max_length=20, index=True)
    term: str = Field(default="1", max_length=20, index=True)
    campus_id: int = Field(index=True)
    building_id: int | None = Field(default=None, index=True)
    building_ids: list[int] | None = Field(default=None, sa_type=JSON)
    floor_from: int | None = Field(default=None)
    floor_to: int | None = Field(default=None)
    room_type: str | None = Field(default=None, max_length=30, index=True)
    min_capacity: int | None = Field(default=None)
    required_feature: str | None = Field(default=None, max_length=50)
    allocation_mode: str = Field(default="shared", max_length=20, index=True)
    status: str = Field(default="active", max_length=20, index=True)
    created_by: int | None = Field(default=None, index=True)


class RoomCohortAllocation(TimestampMixin, TenantMixin, SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("tenant_id", "rule_id", "room_id", name="uq_roomcohortallocation_rule_room"),
    )
    id: int | None = Field(default=None, primary_key=True)
    rule_id: int = Field(index=True)
    room_id: int = Field(index=True)
    cohort_label: str = Field(max_length=30, index=True)
    academic_year: str = Field(default="2026-2027", max_length=20, index=True)
    term: str = Field(default="1", max_length=20, index=True)
    allocation_mode: str = Field(default="shared", max_length=20, index=True)
    status: str = Field(default="active", max_length=20, index=True)
