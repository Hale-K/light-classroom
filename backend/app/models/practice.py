"""巩固域模型
practice_sheet / practice_question
"""
from datetime import datetime
from decimal import Decimal
from sqlmodel import SQLModel, Field

from app.db.base import TimestampMixin, TenantMixin
from app.models.enums import DifficultyLevel, PracticeStatus


class PracticeSheet(TimestampMixin, TenantMixin, SQLModel, table=True):
    """巩固卷(一生一份)"""
    __table_args__ = {"comment": "巩固卷"}
    id: int | None = Field(default=None, primary_key=True)
    source_paper_id: int | None = Field(default=None, description="由哪次考试生成")
    student_id: int = Field(index=True)
    status: PracticeStatus = Field(default=PracticeStatus.generated)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_by: int | None = Field(default=None)
    printed_at: datetime | None = Field(default=None)
    returned_at: datetime | None = Field(default=None)
    reviewed_at: datetime | None = Field(default=None)


class PracticeQuestion(SQLModel, table=True):
    """巩固卷题目"""
    __table_args__ = {"comment": "巩固卷题目"}
    id: int | None = Field(default=None, primary_key=True)
    practice_sheet_id: int = Field(index=True)
    seq: int = Field(default=0, description="题序")
    content: str = Field(max_length=4000, description="题干(AI生成)")
    answer: str | None = Field(default=None, description="答案")
    knowledge_point_id: int | None = Field(default=None)
    difficulty: DifficultyLevel = Field(default=DifficultyLevel.basic)
    origin_question_id: int | None = Field(default=None, description="变式来源(原错题)")
    score: Decimal = Field(default=Decimal("0"))
    earned_score: Decimal | None = Field(default=None, description="回流批改得分")