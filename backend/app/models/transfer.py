"""文件中心：导入 / 导出异步任务。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from app.db.base import TenantMixin, TimestampMixin


class FileTransferJob(TimestampMixin, TenantMixin, SQLModel, table=True):
    """导入导出任务（进度可查，产物落 MinIO）。"""

    __tablename__ = "file_transfer_job"
    __table_args__ = {"comment": "文件中心导入导出任务"}

    id: str = Field(primary_key=True, max_length=32, description="任务 ID")
    # export_timetable / import_students / import_course_hours / import_teaching_assignments
    job_type: str = Field(max_length=64, index=True)
    # import | export
    direction: str = Field(max_length=16, index=True)
    # queued | running | success | failed
    status: str = Field(default="queued", max_length=16, index=True)
    progress: int = Field(default=0, ge=0, le=100)
    processed: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    operator_id: int | None = Field(default=None, index=True)
    operator_name: str = Field(default="", max_length=100)
    scope: str = Field(default="", max_length=500, description="范围说明，如班级/全部")
    file_name: str | None = Field(default=None, max_length=255)
    object_key: str | None = Field(default=None, max_length=512)
    file_size: int = Field(default=0, ge=0)
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    meta_json: str | None = Field(default=None, sa_column=Column(Text, nullable=True), description="JSON 扩展参数")
