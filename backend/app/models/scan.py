"""进卷域模型
scan_batch / scan_page / submission / answer_score
"""
from datetime import datetime
from decimal import Decimal
from sqlmodel import SQLModel, Field, UniqueConstraint

from app.db.base import TimestampMixin, TenantMixin
from app.models.enums import ConfirmStatus, GradingMode, ScanBatchStatus, SubmissionStatus


class ScanBatch(TimestampMixin, TenantMixin, SQLModel, table=True):
    """扫描批次"""
    __table_args__ = {"comment": "扫描批次"}
    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(index=True)
    file_name: str | None = Field(default=None, max_length=255)
    page_count: int = Field(default=0)
    status: ScanBatchStatus = Field(default=ScanBatchStatus.uploaded)
    created_by: int | None = Field(default=None)


class ScanPage(SQLModel, table=True):
    """扫描页"""
    __table_args__ = {"comment": "扫描页"}
    id: int | None = Field(default=None, primary_key=True)
    batch_id: int = Field(index=True)
    page_index: int = Field(description="页序号")
    cos_url: str | None = Field(default=None, max_length=500, description="对象存储地址")
    student_id: int | None = Field(default=None, index=True, description="分配后回填")


class Submission(TimestampMixin, TenantMixin, SQLModel, table=True):
    """作答记录(一生一卷)"""
    __table_args__ = (
        UniqueConstraint("paper_id", "student_id", name="uq_submission_paper_student"),
        {"comment": "作答记录"},
    )
    id: int | None = Field(default=None, primary_key=True)
    paper_id: int = Field(index=True)
    student_id: int = Field(index=True)
    status: SubmissionStatus = Field(default=SubmissionStatus.scanned)
    total_score: Decimal = Field(default=Decimal("0"), description="总分(自动汇总)")
    graded_by: int | None = Field(default=None)
    graded_at: datetime | None = Field(default=None)


class AnswerScore(TimestampMixin, TenantMixin, SQLModel, table=True):
    """每题得分"""
    __table_args__ = (
        UniqueConstraint("submission_id", "question_id", name="uq_answerscore_sub_ques"),
        {"comment": "每题得分"},
    )
    id: int | None = Field(default=None, primary_key=True)
    submission_id: int = Field(index=True)
    question_id: int = Field(index=True)
    score: Decimal = Field(default=Decimal("0"), description="最终得分(人工确认生效)")
    ai_score: Decimal | None = Field(default=None, description="AI 建议分(预批)")
    ai_confidence: Decimal | None = Field(default=None, description="AI 置信度 0-100")
    ai_comment: str | None = Field(default=None, max_length=500)
    grading_mode: GradingMode = Field(default=GradingMode.manual)
    confirm_status: ConfirmStatus = Field(default=ConfirmStatus.pending)
    grader_id: int | None = Field(default=None)
    graded_at: datetime | None = Field(default=None)
    comment: str | None = Field(default=None, max_length=500, description="人工评语")