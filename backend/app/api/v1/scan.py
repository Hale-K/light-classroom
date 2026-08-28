"""扫描进卷 API（A10）

流程：上传批次 → 切分(Split) → 逐页登记 → 按学生分配(生成 Submission) → 确认(Confirm)。
真机上传/切分对接 COS 与图像处理，此处提供批次、状态与作答关系的数据载体。
所有查询由多租户中间件自动注入 tenant_id；写入显式带租户。
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user, get_current_tenant
from app.models.exam import Paper
from app.models.org import Class, Student
from app.models.scan import ScanBatch, ScanPage, Submission
from app.models.enums import ScanBatchStatus, SubmissionStatus

router = APIRouter(tags=["扫描进卷"])


# ---------- Pydantic ----------
class BatchIn(BaseModel):
    paper_id: int
    file_name: str | None = Field(default=None, max_length=255)
    page_count: int = Field(default=0, ge=0)


class PageIn(BaseModel):
    page_index: int = Field(ge=0)
    cos_url: str | None = Field(default=None, max_length=500)


class AssignIn(BaseModel):
    class_id: int | None = Field(default=None, description="限定某班；缺省 = 该卷年级全体学生")


# ---------- 批次 ----------
@router.get("/scans/batches", summary="扫描批次列表")
async def list_batches(
    paper_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    stmt = select(ScanBatch).order_by(ScanBatch.id.desc())
    if paper_id is not None:
        stmt = stmt.where(ScanBatch.paper_id == paper_id)
    result = await session.execute(stmt)
    return {"code": 0, "message": "ok", "data": [b.model_dump() for b in result.scalars().all()]}


@router.post("/scans/batches", summary="上传扫描批次", status_code=201)
async def create_batch(
    body: BatchIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    paper = await session.get(Paper, body.paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="试卷不存在")
    if paper.status != "finalized":
        raise HTTPException(status_code=409, detail="试卷未定稿，不可进卷")
    batch = ScanBatch(
        paper_id=body.paper_id,
        file_name=body.file_name,
        page_count=body.page_count,
        created_by=user.id,
        tenant_id=tenant_id,
    )
    session.add(batch)
    await session.commit()
    await session.refresh(batch)
    return {"code": 0, "message": "ok", "data": batch.model_dump()}


# ---------- 切分 / 页 ----------
@router.patch("/scans/batches/{batch_id}/split", summary="切分完成")
async def split_batch(
    batch_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    batch = await _get_batch(session, batch_id)
    batch.status = ScanBatchStatus.split
    await session.commit()
    await session.refresh(batch)
    return {"code": 0, "message": "ok", "data": batch.model_dump()}


@router.get("/scans/batches/{batch_id}/pages", summary="批次页面列表")
async def list_pages(
    batch_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    await _get_batch(session, batch_id)
    result = await session.execute(
        select(ScanPage).where(ScanPage.batch_id == batch_id).order_by(ScanPage.page_index)
    )
    return {"code": 0, "message": "ok", "data": [p.model_dump() for p in result.scalars().all()]}


@router.post("/scans/batches/{batch_id}/pages", summary="登记扫描页", status_code=201)
async def add_page(
    batch_id: int,
    body: PageIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    await _get_batch(session, batch_id)
    page = ScanPage(batch_id=batch_id, page_index=body.page_index, cos_url=body.cos_url)
    session.add(page)
    await session.commit()
    await session.refresh(page)
    return {"code": 0, "message": "ok", "data": page.model_dump()}


# ---------- 分配（建立 一生一卷 作答关系，唯一约束防重） ----------
@router.post("/scans/batches/{batch_id}/assign", summary="按学生分配生成作答")
async def assign_batch(
    batch_id: int,
    body: AssignIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    batch = await _get_batch(session, batch_id)
    paper = await session.get(Paper, batch.paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="试卷不存在")

    # 确定本次应分发的学生：限定某班，否则该卷年级全体
    if body.class_id is not None:
        classes = [body.class_id]
    else:
        rows = await session.execute(select(Class.id).where(Class.grade_id == paper.grade_id))
        classes = rows.scalars().all()
    students = (await session.execute(
        select(Student).where(Student.class_id.in_(classes), Student.status == "studying")
    )).scalars().all()

    # 本卷已有作答，跳过重复（来自同一教师重复操作）
    existing = set((await session.execute(
        select(Submission.student_id).where(Submission.paper_id == paper.id)
    )).scalars().all())

    created = []
    for s in students:
        if s.id in existing:
            continue
        submission = Submission(
            paper_id=paper.id,
            student_id=s.id,
            status=SubmissionStatus.scanned,
            tenant_id=tenant_id,
        )
        session.add(submission)
        created.append(s.id)

    batch.status = ScanBatchStatus.assigned
    await session.commit()
    return {"code": 0, "message": "ok",
            "data": {"batch_id": batch.id, "created": len(created), "total": len(students)}}


# ---------- 确认 ----------
@router.patch("/scans/batches/{batch_id}/confirm", summary="确认批次")
async def confirm_batch(
    batch_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    batch = await _get_batch(session, batch_id)
    batch.status = ScanBatchStatus.confirmed
    await session.commit()
    await session.refresh(batch)
    return {"code": 0, "message": "ok", "data": batch.model_dump()}


async def _get_batch(session: AsyncSession, batch_id: int) -> ScanBatch:
    batch = await session.get(ScanBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="扫描批次不存在")
    return batch