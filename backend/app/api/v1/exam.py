"""Basic exam records used by the exam-scheduling workflow."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.enums import ExamStatus, ExamType
from app.models.exam import Exam

router = APIRouter(tags=["考试管理"])


class ExamIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    exam_type: ExamType = ExamType.monthly
    academic_year: str = Field(min_length=4, max_length=20)
    term: str = Field(default="1", pattern=r"^[12]$")


class ExamStatusIn(BaseModel):
    status: ExamStatus


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
    exams = (await session.execute(stmt)).scalars().all()
    return {"code": 0, "message": "ok", "data": [item.model_dump() for item in exams]}


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


@router.get("/exams/{exam_id}", summary="考试详情")
async def get_exam(
    exam_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    exam = await session.get(Exam, exam_id)
    if exam is None:
        raise HTTPException(status_code=404, detail="考试不存在")
    return {"code": 0, "message": "ok", "data": exam.model_dump()}


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
