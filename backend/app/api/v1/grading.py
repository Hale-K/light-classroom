"""高效打分 API（A11）

队列：GET 某卷作答 → 逐题录入得分(支持满分/流式键盘的整分) → 批量提交汇总总分。
- AnswerScore 每题一条，唯一约束 (submission_id, question_id)，PUT 幂等 upsert
- finalize 汇总总分并写入 submission.total_score，标记 graded
所有查询由多租户中间件自动注入 tenant_id；写入显式带租户。
"""
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user, get_current_tenant
from app.models.exam import Paper, Question
from app.models.scan import Submission, AnswerScore
from app.models.enums import ConfirmStatus, GradingMode, SubmissionStatus
from app.models.org import Student

router = APIRouter(tags=["高效打分"])


class ScoreIn(BaseModel):
    score: Decimal = Field(ge=0)
    comment: str | None = Field(default=None, max_length=500)
    ai_score: Decimal | None = Field(default=None, ge=0)


# ---------- 阅卷队列 ----------
@router.get("/grading/papers/{paper_id}/submissions", summary="某卷作答队列")
async def list_submissions(
    paper_id: int,
    status_: SubmissionStatus | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    stmt = select(Submission).where(Submission.paper_id == paper_id)
    if status_ is not None:
        stmt = stmt.where(Submission.status == status_)
    result = await session.execute(stmt.order_by(Submission.id))
    data = []
    for sub in result.scalars().all():
        d = sub.model_dump()
        stu = await session.get(Student, sub.student_id)
        d["student_name"] = stu.name if stu else None
        scored = (await session.execute(
            select(func.count()).select_from(AnswerScore)
            .where(AnswerScore.submission_id == sub.id,
                   AnswerScore.confirm_status == ConfirmStatus.confirmed)
        )).scalar_one()
        d["scored_questions"] = scored
        data.append(d)
    return {"code": 0, "message": "ok", "data": data}


# ---------- 单份详情（卷面图地址 + 每题状态） ----------
@router.get("/grading/submissions/{submission_id}", summary="作答详情")
async def get_submission(
    submission_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    sub = await session.get(Submission, submission_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="作答不存在")

    questions = (await session.execute(
        select(Question).where(Question.paper_id == sub.paper_id).order_by(Question.question_no)
    )).scalars().all()

    answer_rows = (await session.execute(
        select(AnswerScore).where(AnswerScore.submission_id == submission_id)
    )).scalars().all()
    ans_by_q = {a.question_id: a for a in answer_rows}

    items = []
    for q in questions:
        a = ans_by_q.get(q.id)
        items.append({
            "question_id": q.id,
            "question_no": q.question_no,
            "score": q.score,
            "difficulty": q.difficulty.value if q.difficulty else None,
            "content": q.content,
            "given_score": a.score if a else None,
            "ai_score": a.ai_score if a else None,
            "ai_confidence": a.ai_confidence if a else None,
            "confirm_status": a.confirm_status.value if a and a.confirm_status else None,
        })

    stu = await session.get(Student, sub.student_id)
    return {"code": 0, "message": "ok", "data": {
        "submission": sub.model_dump(),
        "student_name": stu.name if stu else None,
        "questions": items,
    }}


# ---------- 逐题打分（幂等 upsert） ----------
@router.put("/grading/submissions/{submission_id}/questions/{question_id}",
            summary="录入单题得分")
async def score_question(
    submission_id: int,
    question_id: int,
    body: ScoreIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    sub = await session.get(Submission, submission_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="作答不存在")
    q = await session.get(Question, question_id)
    if q is None or q.paper_id != sub.paper_id:
        raise HTTPException(status_code=404, detail="题目不属于该卷")

    stmt = select(AnswerScore).where(
        AnswerScore.submission_id == submission_id, AnswerScore.question_id == question_id)
    ans = (await session.execute(stmt)).scalar_one_or_none()
    now = datetime.utcnow()
    if ans is None:
        ans = AnswerScore(
            submission_id=submission_id,
            question_id=question_id,
            score=body.score,
            ai_score=body.ai_score,
            comment=body.comment,
            grading_mode=GradingMode.manual,
            confirm_status=ConfirmStatus.confirmed,
            grader_id=user.id,
            graded_at=now,
            tenant_id=tenant_id,
        )
        session.add(ans)
    else:
        ans.score = body.score
        if body.ai_score is not None:
            ans.ai_score = body.ai_score
        ans.comment = body.comment
        ans.confirm_status = ConfirmStatus.confirmed
        ans.grader_id = user.id
        ans.graded_at = now
    await session.commit()
    await session.refresh(ans)
    return {"code": 0, "message": "ok", "data": ans.model_dump()}


# ---------- 批量提交：汇总总分 ----------
@router.post("/grading/submissions/{submission_id}/finalize", summary="提交并汇总总分")
async def finalize_submission(
    submission_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    sub = await session.get(Submission, submission_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="作答不存在")
    total = (await session.execute(
        select(func.coalesce(func.sum(AnswerScore.score), 0)).where(
            AnswerScore.submission_id == submission_id)
    )).scalar_one()
    sub.total_score = total
    sub.status = SubmissionStatus.graded
    sub.graded_by = user.id
    sub.graded_at = datetime.utcnow()
    await session.commit()
    await session.refresh(sub)
    return {"code": 0, "message": "ok", "data": sub.model_dump()}