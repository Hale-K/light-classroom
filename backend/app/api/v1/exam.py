"""考试管理 + 轻量建卷 API（A9）

分层：教务处建考试(Exam) → 为考试建卷(Paper) → 往卷上挂题(Question) → 定稿(finalize)。
所有查询由多租户中间件自动注入 tenant_id；写入显式带租户（见 deps.get_current_tenant）。
"""
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user, get_current_tenant
from app.models.exam import Exam, Paper, Question
from app.models.enums import (
    DifficultyLevel, ExamStatus, ExamType, PaperStatus, QuestionType, SourceType,
)

router = APIRouter(tags=["考试建卷"])


# ---------- Pydantic ----------
class ExamIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    exam_type: ExamType = ExamType.monthly
    academic_year: str = Field(min_length=4, max_length=20)


class PaperIn(BaseModel):
    subject_id: int
    grade_id: int
    title: str = Field(min_length=1, max_length=200)
    total_score: Decimal = Field(default=Decimal("100"))
    teacher_id: int | None = None


class QuestionIn(BaseModel):
    question_no: int | None = Field(default=None, ge=1, description="题号，缺省自动续号")
    score: Decimal = Field(default=Decimal("0"))
    knowledge_point_id: int | None = None
    difficulty: DifficultyLevel = DifficultyLevel.basic
    content: str | None = None
    question_type: QuestionType | None = None
    source_type: SourceType | None = None


class ExamStatusIn(BaseModel):
    status: ExamStatus


# ---------- 考试 ----------
@router.get("/exams", summary="考试列表")
async def list_exams(
    exam_type: ExamType | None = None,
    status_: ExamStatus | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    stmt = select(Exam).order_by(Exam.created_at.desc())
    if exam_type is not None:
        stmt = stmt.where(Exam.exam_type == exam_type)
    if status_ is not None:
        stmt = stmt.where(Exam.status == status_)
    result = await session.execute(stmt)
    exams = []
    for e in result.scalars().all():
        d = e.model_dump()
        d["paper_count"] = (await session.execute(
            select(func.count()).select_from(Paper).where(Paper.exam_id == e.id)
        )).scalar_one()
        exams.append(d)
    return {"code": 0, "message": "ok", "data": exams}


@router.post("/exams", summary="创建考试", status_code=201)
async def create_exam(
    body: ExamIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    exam = Exam(**body.model_dump(), created_by=user.id, tenant_id=tenant_id)
    session.add(exam)
    await session.commit()
    await session.refresh(exam)
    return {"code": 0, "message": "ok", "data": exam.model_dump()}


@router.get("/exams/{exam_id}", summary="考试详情（含试卷）")
async def get_exam(
    exam_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    exam = await session.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="考试不存在")
    result = await session.execute(select(Paper).where(Paper.exam_id == exam_id))
    data = exam.model_dump()
    data["papers"] = [p.model_dump() for p in result.scalars().all()]
    return {"code": 0, "message": "ok", "data": data}


@router.patch("/exams/{exam_id}/status", summary="更新考试状态")
async def update_exam_status(
    exam_id: int,
    body: ExamStatusIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    exam = await session.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="考试不存在")
    exam.status = body.status
    await session.commit()
    await session.refresh(exam)
    return {"code": 0, "message": "ok", "data": exam.model_dump()}


# ---------- 试卷（轻量建卷） ----------
@router.post("/exams/{exam_id}/papers", summary="为考试建卷", status_code=201)
async def create_paper(
    exam_id: int,
    body: PaperIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    exam = await session.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="考试不存在")
    paper = Paper(
        exam_id=exam_id,
        teacher_id=body.teacher_id or user.id,
        title=body.title,
        total_score=body.total_score,
        subject_id=body.subject_id,
        grade_id=body.grade_id,
        status=PaperStatus.building,
        tenant_id=tenant_id,
    )
    session.add(paper)
    await session.commit()
    await session.refresh(paper)
    return {"code": 0, "message": "ok", "data": paper.model_dump()}


@router.get("/papers/{paper_id}", summary="试卷详情（含题目）")
async def get_paper(
    paper_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="试卷不存在")
    result = await session.execute(
        select(Question).where(Question.paper_id == paper_id).order_by(Question.question_no)
    )
    questions = result.scalars().all()
    data = paper.model_dump()
    data["questions"] = [q.model_dump() for q in questions]
    # 轻量汇总：实际题分累计，供核对与总分回填
    data["actual_score"] = sum((q.score for q in questions), Decimal("0"))
    return {"code": 0, "message": "ok", "data": data}


@router.post("/papers/{paper_id}/questions", summary="添加题目", status_code=201)
async def add_question(
    paper_id: int,
    body: QuestionIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="试卷不存在")
    if paper.status != PaperStatus.building:
        raise HTTPException(status_code=409, detail="试卷已定稿，不可增题")

    q_no = body.question_no
    if q_no is None:
        # 自动续号：当前最大题号 + 1
        q_no = (await session.execute(
            select(func.max(Question.question_no)).where(Question.paper_id == paper_id)
        )).scalar_one() or 0
        q_no += 1

    question = Question(
        paper_id=paper_id,
        question_no=q_no,
        score=body.score,
        knowledge_point_id=body.knowledge_point_id,
        difficulty=body.difficulty,
        content=body.content,
        question_type=body.question_type,
        source_type=body.source_type,
    )
    session.add(question)
    await session.commit()
    await session.refresh(question)
    return {"code": 0, "message": "ok", "data": question.model_dump()}


@router.patch("/papers/{paper_id}/finalize", summary="试卷定稿")
async def finalize_paper(
    paper_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="试卷不存在")
    if paper.status != PaperStatus.building:
        raise HTTPException(status_code=409, detail="试卷已定稿")
    paper.status = PaperStatus.finalized
    paper.delivered_at = datetime.utcnow()
    await session.commit()
    await session.refresh(paper)
    return {"code": 0, "message": "ok", "data": paper.model_dump()}