"""分析域模型
student_profile / wrong_question / teaching_plan
"""
from datetime import datetime
from typing import Any
from sqlmodel import SQLModel, Field
from sqlalchemy import JSON, UniqueConstraint

from app.db.base import TimestampMixin, TenantMixin
from app.models.enums import PlanStatus, PlanType, ProfileTier


class StudentProfile(TenantMixin, SQLModel, table=True):
    """学生画像（物化表，打分事件驱动更新）"""
    __table_args__ = (
        UniqueConstraint("tenant_id", "student_id", "knowledge_point_id", name="uq_studentprofile_student_kp"),
        {"comment": "学生画像"},
    )
    id: int | None = Field(default=None, primary_key=True)
    student_id: int = Field(index=True)
    knowledge_point_id: int = Field(index=True)
    mastery: int = Field(default=0, description="掌握度 0-100")
    tier: ProfileTier = Field(default=ProfileTier.weak, description="分层依据")
    attempt_count: int = Field(default=0, description="作答次数")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WrongQuestion(TenantMixin, SQLModel, table=True):
    """错题集"""
    __table_args__ = (
        UniqueConstraint("tenant_id", "student_id", "question_id", name="uq_wrongquestion_student_question"),
        {"comment": "错题集"},
    )
    id: int | None = Field(default=None, primary_key=True)
    student_id: int = Field(index=True)
    question_id: int = Field(index=True)
    source_paper_id: int | None = Field(default=None, description="来自哪次考试")
    wrong_count: int = Field(default=1, description=">=2 重点突破题")
    last_wrong_at: datetime = Field(default_factory=datetime.utcnow)
    is_mastered: bool = Field(default=False, description="巩固回流后已掌握")
    mastered_at: datetime | None = Field(default=None)


class TeachingPlan(TimestampMixin, TenantMixin, SQLModel, table=True):
    """AI 教学计划（老师参考后编辑）"""
    __table_args__ = {"comment": "AI教学计划"}
    id: int | None = Field(default=None, primary_key=True)
    class_id: int = Field(index=True)
    subject_id: int = Field(index=True)
    grade_level: int = Field(default=0)
    plan_type: PlanType = Field(default=PlanType.weekly)
    period: str | None = Field(default=None, max_length=50, description="计划周期")
    content: dict | None = Field(default=None, sa_type=JSON, description="计划内容(json)")
    status: PlanStatus = Field(default=PlanStatus.generated)
    created_by: int | None = Field(default=None)  # 生成老师
    edited_at: datetime | None = Field(default=None)