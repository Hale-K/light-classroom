"""工作台聚合 API

将工作台所需的考试 / 定稿卷 / 每卷已批与总数一次返回，
避免前端串行拉取 N 个 detail + queue 造成的大量请求与后端 N+1 查询。
所有查询由多租户中间件自动注入 tenant_id。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user
from app.models.exam import Exam, Paper
from app.models.enums import ExamStatus, PaperStatus, SubmissionStatus
from app.models.scan import ScanBatch, Submission

router = APIRouter(tags=["工作台"])


@router.get("/dashboard/summary", summary="工作台汇总")
async def dashboard_summary(
    limit: int = 5,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    limit = max(1, min(limit, 20))
    # 最近考试(含每场卷数、进行中状态)
    exams = (await session.execute(
        select(Exam).order_by(Exam.created_at.desc()).limit(limit)
    )).scalars().all()
    exam_ids = [e.id for e in exams]

    paper_counts = {}
    if exam_ids:
        rows = await session.execute(
            select(Paper.exam_id, func.count()).where(Paper.exam_id.in_(exam_ids))
            .group_by(Paper.exam_id)
        )
        paper_counts = {eid: cnt for eid, cnt in rows.all()}

    # 全部定稿卷（工作台阅卷队列 = 该租户所有已定稿卷的批改进度）
    papers = (await session.execute(
        select(Paper).where(Paper.status == PaperStatus.finalized)
        .order_by(Paper.id.desc())
    )).scalars().all()
    paper_ids = [p.id for p in papers]

    # 每卷作答总数 + 已批阅数（一次聚合，避免每卷单独查询）
    total_by_paper = {}
    graded_by_paper = {}
    if paper_ids:
        rows = await session.execute(
            select(Submission.paper_id, func.count()).where(Submission.paper_id.in_(paper_ids))
            .group_by(Submission.paper_id)
        )
        total_by_paper = {pid: cnt for pid, cnt in rows.all()}
        rows = await session.execute(
            select(Submission.paper_id, func.count())
            .where(Submission.paper_id.in_(paper_ids),
                   Submission.status == SubmissionStatus.graded)
            .group_by(Submission.paper_id)
        )
        graded_by_paper = {pid: cnt for pid, cnt in rows.all()}

    # 扫描批次
    batches = (await session.execute(
        select(ScanBatch).order_by(ScanBatch.id.desc()).limit(limit)
    )).scalars().all()

    return {"code": 0, "message": "ok", "data": {
        "exams": [
            {
                **e.model_dump(),
                "paper_count": paper_counts.get(e.id, 0),
                "ongoing": e.status == ExamStatus.ongoing,
            }
            for e in exams
        ],
        "ongoing_count": sum(1 for e in exams if e.status == ExamStatus.ongoing),
        "papers": [
            {
                "id": p.id,
                "title": p.title,
                "subject_id": p.subject_id,
                "graded": graded_by_paper.get(p.id, 0),
                "total": total_by_paper.get(p.id, 0),
            }
            for p in papers
        ],
        "paper_count": len(papers),
        "graded_total": sum(graded_by_paper.get(p.id, 0) for p in papers),
        "submission_total": sum(total_by_paper.get(p.id, 0) for p in papers),
        "batches": [b.model_dump() for b in batches],
        "pending_batch_count": sum(
            1 for b in batches if b.status and b.status != "confirmed"
        ),
    }}