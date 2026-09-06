"""排课任务持久化模型。"""
from datetime import datetime

from sqlalchemy import JSON, Index
from sqlmodel import Field, SQLModel

from app.db.base import TenantMixin


class SchedulingGenerateJob(TenantMixin, SQLModel, table=True):
    """排课生成的持久状态；Redis 只承担实时事件分发。"""

    __tablename__ = "scheduling_generate_job"
    __table_args__ = (
        Index(
            "ix_scheduling_generate_job_scope_status",
            "tenant_id",
            "academic_year",
            "term",
            "status",
        ),
    )

    id: str = Field(primary_key=True, max_length=32)
    academic_year: str = Field(max_length=20, index=True)
    term: str = Field(max_length=20, index=True)
    payload: dict = Field(default_factory=dict, sa_type=JSON)
    status: str = Field(default="queued", max_length=20, index=True)
    stage: str = Field(default="queued", max_length=30)
    message: str = Field(default="已进入排课队列", max_length=300)
    percent: int = Field(default=0)
    attempt: int = Field(default=0)
    result: dict | None = Field(default=None, sa_type=JSON)
    error: dict | None = Field(default=None, sa_type=JSON)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    heartbeat_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = Field(default=None)
