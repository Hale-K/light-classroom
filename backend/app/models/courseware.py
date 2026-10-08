"""课件管理：上传文件 / AI 生成的互动网页课件 / 收藏的外部链接。"""
from __future__ import annotations

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel

from app.db.base import TenantMixin, TimestampMixin


class Courseware(TimestampMixin, TenantMixin, SQLModel, table=True):
    """课件（courseware_type: file=上传文档, html=AI 互动课件, link=外部链接）。"""

    __tablename__ = "courseware"
    __table_args__ = {"comment": "课件库"}

    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(max_length=120, index=True, description="课件名称")
    courseware_type: str = Field(default="file", max_length=10, index=True)
    stage: str = Field(default="", max_length=10, index=True, description="学段：小学/初中/高中")
    grade_name: str = Field(default="", max_length=20, index=True, description="年级")
    subject_name: str = Field(default="", max_length=20, index=True, description="学科")
    textbook_version: str = Field(default="", max_length=30, description="教材版本")
    chapter: str = Field(default="", max_length=160, description="章节/课题")
    # 上传文件（courseware_type=file）
    file_name: str = Field(default="", max_length=255)
    object_key: str = Field(default="", max_length=512)
    file_size: int = Field(default=0, ge=0)
    content_type: str = Field(default="", max_length=120)
    # 外部链接（courseware_type=link）
    source_url: str = Field(default="", max_length=600)
    # AI 生成的单文件 HTML 互动课件（courseware_type=html）
    html_content: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    # upload | ai
    origin: str = Field(default="upload", max_length=10, index=True)
    tags: list[str] = Field(default_factory=list, sa_type=JSON)
    remark: str = Field(default="", max_length=300)
    created_by: int | None = Field(default=None, index=True)
    created_by_name: str = Field(default="", max_length=60)
