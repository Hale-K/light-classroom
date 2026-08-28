"""押题域模型
question_bank / exam_trend / teacher_style / hot_topic /
prediction_task / prediction_item / prediction_feedback
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from sqlmodel import SQLModel, Field
from sqlalchemy import JSON

from app.db.base import TimestampMixin, TenantMixin
from app.models.enums import (
    DifficultyLevel, ExamNature, PredictionItemStatus, PredictionTaskStatus,
    QuestionType, SourceType, TopicCategory, TrendDirection,
)


class QuestionBank(TimestampMixin, SQLModel, table=True):
    """题目库(沉淀市面/真题/原创)，tenant_id 空=公共库"""
    __table_args__ = {"comment": "题目库"}
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int | None = Field(default=None, index=True, description="空=公共库")
    subject_id: int = Field(index=True)
    grade_level: int = Field(default=0)
    knowledge_point_id: int | None = Field(default=None)
    difficulty: DifficultyLevel = Field(default=DifficultyLevel.basic)
    question_type: QuestionType = Field(default=QuestionType.single)
    source_type: SourceType = Field(default=SourceType.self)
    source_ref: str | None = Field(default=None, max_length=255)
    content: str = Field(max_length=4000, description="题干")
    answer: str | None = Field(default=None, description="答案")
    analysis: str | None = Field(default=None, description="解析")
    tags: dict | None = Field(default=None, sa_type=JSON, description="自定义标签")
    use_count: int = Field(default=0, description="被使用次数")
    is_verified: bool = Field(default=False)


class ExamTrend(SQLModel, table=True):
    """考点趋势(历史考情聚合)"""
    __table_args__ = {"comment": "考点趋势"}
    id: int | None = Field(default=None, primary_key=True)
    subject_id: int = Field(index=True)
    knowledge_point_id: int = Field(index=True)
    year: int = Field(default=0)
    term: int | None = Field(default=None)
    exam_nature: ExamNature = Field(default=ExamNature.monthly)
    appear_count: int = Field(default=0, description="出现次数")
    score_weight: Decimal = Field(default=Decimal("0"), description="分值权重")
    trend_score: Decimal = Field(default=Decimal("0"), description="趋势分(近三年加权)")
    region: str | None = Field(default=None, max_length=50)


class TeacherStyle(TenantMixin, SQLModel, table=True):
    """出题老师风格画像(自动学习)"""
    __table_args__ = {"comment": "老师风格画像"}
    id: int | None = Field(default=None, primary_key=True)
    teacher_id: int = Field(index=True)
    subject_id: int = Field(index=True)
    preferred_kp: dict | None = Field(default=None, sa_type=JSON, description="偏好知识点及频次")
    difficulty_dist: dict | None = Field(default=None, sa_type=JSON, description="难度分布")
    type_dist: dict | None = Field(default=None, sa_type=JSON, description="题型分布")
    source_preference: dict | None = Field(default=None, sa_type=JSON)
    style_vector: dict | None = Field(default=None, sa_type=JSON, description="风格特征向量")
    sample_size: int = Field(default=0, description="样本量(出卷次数)")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class HotTopic(SQLModel, table=True):
    """社会热点(讨论度)"""
    __table_args__ = {"comment": "社会热点"}
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(max_length=200, description="热点标题")
    category: TopicCategory = Field(default=TopicCategory.livelihood)
    heat_index: int = Field(default=0)
    heat_date: date | None = Field(default=None)
    keywords: dict | None = Field(default=None, sa_type=JSON)
    related_subjects: dict | None = Field(default=None, sa_type=JSON, description="关联学科")
    trend_direction: TrendDirection = Field(default=TrendDirection.stable)
    source: str | None = Field(default=None, max_length=255)


class PredictionTask(TimestampMixin, TenantMixin, SQLModel, table=True):
    """押题任务"""
    __table_args__ = {"comment": "押题任务"}
    id: int | None = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True, description="预测目标考试")
    subject_id: int = Field(index=True)
    grade_level: int = Field(default=0)
    created_by: int | None = Field(default=None)
    model_name: str | None = Field(default=None, max_length=100)
    status: PredictionTaskStatus = Field(default=PredictionTaskStatus.queued)
    confidence_avg: Decimal | None = Field(default=None, description="平均置信度")
    finished_at: datetime | None = Field(default=None)


class PredictionItem(SQLModel, table=True):
    """押题结果明细"""
    __table_args__ = {"comment": "押题结果明细"}
    id: int | None = Field(default=None, primary_key=True)
    prediction_task_id: int = Field(index=True)
    knowledge_point_id: int | None = Field(default=None)
    question_type: QuestionType = Field(default=QuestionType.single)
    difficulty: DifficultyLevel = Field(default=DifficultyLevel.basic)
    probability: int = Field(default=0, description="命中概率 0-100")
    reason: str | None = Field(default=None, max_length=1000, description="押题理由")
    status: PredictionItemStatus = Field(default=PredictionItemStatus.pending)
    reviewer_id: int | None = Field(default=None)
    reviewed_at: datetime | None = Field(default=None)
    generated_question_id: int | None = Field(default=None, description="AI生成样题")


class PredictionFeedback(SQLModel, table=True):
    """押题效果反馈(闭环进化)"""
    __table_args__ = {"comment": "押题效果反馈"}
    id: int | None = Field(default=None, primary_key=True)
    prediction_item_id: int = Field(index=True)
    exam_id: int = Field(index=True)
    actual_appeared: bool = Field(default=False)
    actual_weight: Decimal = Field(default=Decimal("0"), description="实际分值权重")
    feedback_by: int | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)