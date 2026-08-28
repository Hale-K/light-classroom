"""班级排座 API：自动生成、历史查询和启用。"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.enums import SeatLayout, SeatRule, SeatStatus, StudentStatus
from app.models.exam import Paper
from app.models.org import Class, SeatArrangement, Student
from app.models.scan import Submission
from app.services.scheduling import arrange_students

router = APIRouter(prefix="/seating", tags=["排座管理"])


class GenerateSeatsIn(BaseModel):
    class_id: int
    rows: int = Field(ge=1, le=20)
    cols: int = Field(ge=1, le=20)
    order: SeatRule = Field(default=SeatRule.roster, description="排序方式")
    layout: SeatLayout = Field(default=SeatLayout.normal, description="排布方式")
    pairing: str = Field(default="none", description="搭配方式(身高互补)")
    seed: int | None = None
    exam_id: int | None = Field(default=None, description="按某场考试成绩排序时指定的考试")
    separation_pairs: list[list[int]] = Field(
        default_factory=list, description="需隔离对学生对：彼此不得相邻"
    )
    adjacency_pairs: list[list[int]] = Field(
        default_factory=list, description="想挨着的学生对：尽量相邻"
    )
    effective_from: date | None = None
    effective_to: date | None = None
    front_student_ids: list[int] = Field(default_factory=list, max_length=20)


class UpdateSeatsIn(BaseModel):
    seats: list[dict[str, int]] = Field(description="手动调整后的座位：{row, col, student_id}")


def _arrangement_out(item: SeatArrangement, students: dict[int, Student]):
    data = item.model_dump()
    raw_seats = (item.student_map or {}).get("seats", [])
    data["seats"] = [
        {
            **seat,
            "student_name": students.get(seat["student_id"]).name if students.get(seat["student_id"]) else "未知学生",
            "student_no": students.get(seat["student_id"]).student_no if students.get(seat["student_id"]) else None,
            "gender": students.get(seat["student_id"]).gender if students.get(seat["student_id"]) else None,
            "height_cm": students.get(seat["student_id"]).height_cm if students.get(seat["student_id"]) else None,
        }
        for seat in raw_seats
    ]
    return data


@router.get("/arrangements", summary="查询班级座位表")
async def list_arrangements(
    class_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    items = list((await session.execute(select(SeatArrangement).where(
        SeatArrangement.class_id == class_id,
    ).order_by(SeatArrangement.created_at.desc()))).scalars().all())
    students = list((await session.execute(select(Student).where(Student.class_id == class_id))).scalars().all())
    student_map = {item.id: item for item in students}
    return {"code": 0, "message": "ok", "data": [_arrangement_out(item, student_map) for item in items]}


@router.post("/generate", summary="生成班级座位表", status_code=201)
async def generate_arrangement(
    body: GenerateSeatsIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    class_item = await session.get(Class, body.class_id)
    if not class_item or class_item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="班级不存在")
    students = list((await session.execute(select(Student).where(
        Student.class_id == body.class_id,
        Student.status == StudentStatus.studying,
    ).order_by(Student.roster_order, Student.id))).scalars().all())
    if not students:
        raise HTTPException(status_code=422, detail="该班级没有在读学生")
    if body.order.value == "score" and body.exam_id is None:
        raise HTTPException(status_code=422, detail="按考试成绩排序时，请选择一场考试")

    student_dicts = [item.model_dump() for item in students]
    if body.exam_id is not None:
        paper_ids = list((await session.execute(
            select(Paper.id).where(Paper.exam_id == body.exam_id),
        )).scalars().all())
        student_ids = [item.id for item in students]
        exam_totals: dict[int, float] = {}
        if paper_ids:
            subs = list((await session.execute(select(Submission).where(
                Submission.paper_id.in_(paper_ids),
                Submission.student_id.in_(student_ids),
            ))).scalars().all())
            agg: dict[int, float] = {}
            for sub in subs:
                agg[sub.student_id] = agg.get(sub.student_id, 0.0) + float(sub.total_score)
            exam_totals = agg
        for item in student_dicts:
            item["exam_score"] = exam_totals.get(item["id"])

    try:
        seats = arrange_students(
            student_dicts,
            rows=body.rows,
            cols=body.cols,
            order=body.order.value,
            layout=body.layout.value,
            pairing=body.pairing,
            seed=body.seed,
            front_student_ids=set(body.front_student_ids),
            separation_pairs=body.separation_pairs,
            adjacency_pairs=body.adjacency_pairs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    arrangement = SeatArrangement(
        class_id=body.class_id,
        rows=body.rows,
        cols=body.cols,
        rule=body.order,
        layout=body.layout,
        student_map={"seats": [seat.__dict__ for seat in seats]},
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        status=SeatStatus.draft,
        created_by=user.id,
        tenant_id=tenant_id,
    )
    session.add(arrangement)
    await session.commit()
    await session.refresh(arrangement)
    return {"code": 0, "message": "ok", "data": _arrangement_out(arrangement, {item.id: item for item in students})}


@router.patch("/arrangements/{arrangement_id}/seats", summary="保存手动调整的座位")
async def update_arrangement_seats(
    arrangement_id: int,
    body: UpdateSeatsIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    arrangement = await session.get(SeatArrangement, arrangement_id)
    if arrangement is None or arrangement.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="座位表不存在")
    arrangement.student_map = {
        "seats": sorted(body.seats, key=lambda s: (s["row"], s["col"])),
    }
    session.add(arrangement)
    await session.commit()
    await session.refresh(arrangement)
    students = list((await session.execute(select(Student).where(
        Student.class_id == arrangement.class_id,
    ))).scalars().all())
    return {"code": 0, "message": "ok", "data": _arrangement_out(arrangement, {item.id: item for item in students})}


@router.patch("/arrangements/{arrangement_id}/activate", summary="启用座位表")
async def activate_arrangement(
    arrangement_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    target = await session.get(SeatArrangement, arrangement_id)
    if not target or target.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="座位表不存在")
    current = list((await session.execute(select(SeatArrangement).where(
        SeatArrangement.class_id == target.class_id,
        SeatArrangement.status == SeatStatus.active,
    ))).scalars().all())
    for item in current:
        item.status = SeatStatus.archived
    target.status = SeatStatus.active
    if target.effective_from is None:
        target.effective_from = date.today()
    await session.commit()
    await session.refresh(target)
    students = list((await session.execute(select(Student).where(Student.class_id == target.class_id))).scalars().all())
    return {"code": 0, "message": "ok", "data": _arrangement_out(target, {item.id: item for item in students})}
