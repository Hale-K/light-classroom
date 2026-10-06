"""Small exam and timetable summary for the workbench."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.enums import ExamStatus
from app.models.exam import Exam

router = APIRouter(tags=["工作台"])


@router.get("/dashboard/summary", summary="工作台汇总")
async def dashboard_summary(
    limit: int = 5,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    limit = max(1, min(limit, 20))
    exams = (await session.execute(
        select(Exam).order_by(Exam.created_at.desc()).limit(limit)
    )).scalars().all()
    return {"code": 0, "message": "ok", "data": {
        "exams": [{**item.model_dump(), "ongoing": item.status == ExamStatus.ongoing} for item in exams],
        "ongoing_count": sum(item.status == ExamStatus.ongoing for item in exams),
    }}
