"""School-wide campuses, buildings, rooms and meeting bookings."""
from datetime import datetime
from math import ceil
import random

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.enums import BaseUserRole
from app.models.facility import (
    Building, Campus, Meeting, ResourceAllocationRule, Room, RoomBooking,
    RoomCohortAllocation,
)
from app.models.org import Class, Grade, OrganizationUnit, Student, User
from app.services.resource_allocation import room_matches_rule
from app.services.staff_roles import get_staff_role_codes
from app.services.naming import normalize_entity_name
from app.services.cohort import current_academic_year, expected_cohort_label

router = APIRouter(tags=["校区场室与会议"])


class CampusIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    address: str | None = Field(default=None, max_length=200)
    student_capacity: int | None = Field(default=None, ge=1, le=100000)


class BuildingIn(BaseModel):
    campus_id: int
    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=30)
    floor_count: int = Field(default=1, ge=1, le=100)


class BuildingStatusIn(BaseModel):
    status: str = Field(pattern=r"^(active|maintenance|disabled)$")


class RoomIn(BaseModel):
    building_id: int
    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=30)
    floor: int = 1
    capacity: int = Field(default=40, ge=1, le=5000)
    room_type: str = Field(default="classroom", pattern=r"^(classroom|laboratory|computer|meeting|auditorium|office)$")
    features: list[str] = Field(default_factory=list)
    is_schedulable: bool = True
    is_exam_enabled: bool = False
    is_meeting_enabled: bool = False


class ResourceAllocationRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    cohort_label: str = Field(pattern=r"^\d{4}届$")
    academic_year: str = Field(default="2026-2027", min_length=9, max_length=20)
    term: str = Field(default="1", pattern=r"^(1|2)$")
    campus_id: int
    building_id: int | None = None
    building_ids: list[int] | None = Field(default=None, min_length=1)
    floor_from: int | None = Field(default=None, ge=-5, le=100)
    floor_to: int | None = Field(default=None, ge=-5, le=100)
    room_type: str | None = Field(
        default=None,
        pattern=r"^(classroom|laboratory|computer|meeting|auditorium|office)$",
    )
    min_capacity: int | None = Field(default=None, ge=1, le=5000)
    required_feature: str | None = Field(default=None, max_length=50)
    allocation_mode: str = Field(default="shared", pattern=r"^(exclusive|shared)$")
    room_ids: list[int] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_floor_range(self):
        if self.floor_from is not None and self.floor_to is not None and self.floor_from > self.floor_to:
            raise ValueError("起始楼层不能高于结束楼层")
        return self


class MeetingIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    room_id: int
    start_at: datetime
    end_at: datetime
    participant_ids: list[int] = Field(default_factory=list)
    agenda: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_period(self):
        if self.end_at <= self.start_at:
            raise ValueError("会议结束时间必须晚于开始时间")
        return self


async def require_manager(session: AsyncSession, user: User, principal_only: bool = False) -> None:
    if user.role == BaseUserRole.director:
        return
    if not principal_only and "academic_director" in await get_staff_role_codes(session, user.id):
        return
    raise HTTPException(status_code=403, detail="当前账号没有资源管理权限")


async def tenant_item(session, model, item_id: int, tenant_id: int, label: str):
    item = await session.get(model, item_id)
    if item is None or item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    return item


@router.get("/facilities/overview")
async def facilities_overview(
    tenant_id: int = Depends(get_current_tenant), session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    campuses = list((await session.execute(select(Campus).where(Campus.tenant_id == tenant_id))).scalars().all())
    buildings = list((await session.execute(select(Building).where(Building.tenant_id == tenant_id))).scalars().all())
    rooms = list((await session.execute(select(Room).where(Room.tenant_id == tenant_id))).scalars().all())
    return {"code": 0, "message": "ok", "data": {
        "campuses": [item.model_dump() for item in campuses],
        "buildings": [{**item.model_dump(), "room_count": sum(r.building_id == item.id for r in rooms),
            "multimedia_count": sum(r.building_id == item.id and "multimedia" in r.features for r in rooms)} for item in buildings],
        "stats": {"campus_count": len(campuses), "building_count": len(buildings), "room_count": len(rooms),
            "multimedia_count": sum("multimedia" in room.features for room in rooms)},
    }}


@router.post("/facilities/campuses", status_code=status.HTTP_201_CREATED)
async def create_campus(body: CampusIn, tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    await require_manager(session, user, principal_only=True)
    item = Campus(tenant_id=tenant_id, **body.model_dump()); session.add(item)
    await session.commit(); await session.refresh(item)
    return {"code": 0, "message": "ok", "data": item.model_dump()}


@router.post("/facilities/buildings", status_code=status.HTTP_201_CREATED)
async def create_building(body: BuildingIn, tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    await require_manager(session, user, principal_only=True)
    await tenant_item(session, Campus, body.campus_id, tenant_id, "校区")
    name = normalize_entity_name(body.name) or ""
    duplicate = (await session.execute(select(Building.id).where(
        Building.tenant_id == tenant_id, Building.campus_id == body.campus_id, Building.name == name,
    ))).scalar()
    if duplicate:
        raise HTTPException(status_code=422, detail=f"该校区下楼宇「{name}」已存在")
    item = Building(tenant_id=tenant_id, **{**body.model_dump(), "name": name}); session.add(item)
    await session.commit(); await session.refresh(item)
    return {"code": 0, "message": "ok", "data": item.model_dump()}


@router.patch("/facilities/buildings/{building_id}/status")
async def update_building_status(building_id: int, body: BuildingStatusIn,
    tenant_id: int = Depends(get_current_tenant), session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)):
    await require_manager(session, user, principal_only=True)
    item = await tenant_item(session, Building, building_id, tenant_id, "楼宇")
    item.status = body.status
    session.add(item); await session.commit(); await session.refresh(item)
    return {"code": 0, "message": "ok", "data": item.model_dump()}


@router.get("/facilities/rooms")
async def list_rooms(building_id: int | None = None, room_type: str | None = None,
    tenant_id: int = Depends(get_current_tenant), session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)):
    stmt = select(Room).where(Room.tenant_id == tenant_id)
    if building_id: stmt = stmt.where(Room.building_id == building_id)
    if room_type: stmt = stmt.where(Room.room_type == room_type)
    items = list((await session.execute(stmt.order_by(Room.building_id, Room.floor, Room.name))).scalars().all())
    buildings = {b.id: b.name for b in (await session.execute(select(Building).where(Building.tenant_id == tenant_id))).scalars().all()}
    allocations = list((await session.execute(select(RoomCohortAllocation).where(
        RoomCohortAllocation.tenant_id == tenant_id,
        RoomCohortAllocation.status == "active",
    ).order_by(RoomCohortAllocation.cohort_label))).scalars().all())
    allocations_by_room: dict[int, list[RoomCohortAllocation]] = {}
    for allocation in allocations:
        allocations_by_room.setdefault(allocation.room_id, []).append(allocation)
    class_assignments: dict[int, list[dict]] = {}
    if items:
        class_rows = (await session.execute(select(Class, Grade.name).join(
            Grade, Grade.id == Class.grade_id,
        ).where(
            Class.tenant_id == tenant_id,
            Class.home_room_id.in_([item.id for item in items]),
        ))).all()
        for class_item, grade_name in class_rows:
            class_assignments.setdefault(class_item.home_room_id, []).append({
                "id": class_item.id,
                "name": class_item.name,
                "grade_id": class_item.grade_id,
                "grade_name": grade_name,
            })
    return {"code": 0, "message": "ok", "data": [{
        **item.model_dump(),
        "building_name": buildings.get(item.building_id, "-"),
        "cohort_allocations": [{
            "rule_id": allocation.rule_id,
            "cohort_label": allocation.cohort_label,
            "academic_year": allocation.academic_year,
            "term": allocation.term,
            "allocation_mode": allocation.allocation_mode,
        } for allocation in allocations_by_room.get(item.id, [])],
        "class_assignments": class_assignments.get(item.id, []),
    } for item in items]}


@router.post("/facilities/rooms", status_code=status.HTTP_201_CREATED)
async def create_room(body: RoomIn, tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    await require_manager(session, user)
    await tenant_item(session, Building, body.building_id, tenant_id, "楼宇")
    item = Room(tenant_id=tenant_id, **body.model_dump()); session.add(item)
    await session.commit(); await session.refresh(item)
    return {"code": 0, "message": "ok", "data": item.model_dump()}


async def scoped_rooms(
    session: AsyncSession,
    tenant_id: int,
    body: ResourceAllocationRuleIn,
) -> list[Room]:
    await tenant_item(session, Campus, body.campus_id, tenant_id, "校区")
    buildings = list((await session.execute(select(Building).where(
        Building.tenant_id == tenant_id,
        Building.campus_id == body.campus_id,
    ))).scalars().all())
    campus_building_ids = {building.id for building in buildings}
    selected_building_ids = set(body.building_ids or ([] if body.building_id is None else [body.building_id]))
    if selected_building_ids - campus_building_ids:
        raise HTTPException(status_code=422, detail="所选楼宇不属于目标校区")
    building_ids = selected_building_ids or campus_building_ids
    rooms = list((await session.execute(select(Room).where(
        Room.tenant_id == tenant_id,
        Room.building_id.in_(building_ids),
        *([Room.floor >= body.floor_from] if body.floor_from is not None else []),
        *([Room.floor <= body.floor_to] if body.floor_to is not None else []),
    ).order_by(Room.building_id, Room.floor, Room.name))).scalars().all()) if building_ids else []
    return rooms


async def matching_rooms(
    session: AsyncSession,
    tenant_id: int,
    body: ResourceAllocationRuleIn,
) -> list[Room]:
    rooms = await scoped_rooms(session, tenant_id, body)
    matched = [room for room in rooms if room_matches_rule(room.model_dump(), body.model_dump())]
    if body.allocation_mode == "exclusive" and matched:
        allocated_room_ids = set((await session.execute(select(RoomCohortAllocation.room_id).where(
            RoomCohortAllocation.tenant_id == tenant_id,
            RoomCohortAllocation.status == "active",
            RoomCohortAllocation.room_id.in_([room.id for room in matched]),
            (RoomCohortAllocation.cohort_label != body.cohort_label)
            | (RoomCohortAllocation.academic_year != body.academic_year)
            | (RoomCohortAllocation.term != body.term),
        ))).scalars().all())
        matched = [room for room in matched if room.id not in allocated_room_ids]
    return matched


async def target_student_count(
    session: AsyncSession,
    tenant_id: int,
    campus_id: int,
    cohort_label: str,
) -> int | None:
    grade_units = list((await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type == "grade_group",
        OrganizationUnit.cohort_label == cohort_label,
        OrganizationUnit.status == "active",
    ))).scalars().all())
    levels = {level for unit in grade_units for level, label in ((1, "高一"), (2, "高二"), (3, "高三")) if label in unit.name}
    if not levels:
        return None
    grade_ids = list((await session.execute(select(Grade.id).where(
        Grade.tenant_id == tenant_id,
        Grade.campus_id == campus_id,
        Grade.level.in_(levels),
    ))).scalars().all())
    if not grade_ids:
        return None
    return int((await session.execute(select(func.count(Student.id)).where(
        Student.tenant_id == tenant_id,
        Student.campus_id == campus_id,
        Student.grade_id.in_(grade_ids),
        Student.status == "studying",
    ))).scalar_one())


async def allocation_preview(
    session: AsyncSession,
    tenant_id: int,
    body: ResourceAllocationRuleIn,
) -> dict:
    rooms = await scoped_rooms(session, tenant_id, body)
    room_ids = [room.id for room in rooms if room.id is not None]
    building_names = dict((await session.execute(select(Building.id, Building.name).where(
        Building.tenant_id == tenant_id,
        Building.id.in_({room.building_id for room in rooms}),
    ))).all()) if rooms else {}
    allocations = list((await session.execute(select(RoomCohortAllocation).where(
        RoomCohortAllocation.tenant_id == tenant_id,
        RoomCohortAllocation.status == "active",
        RoomCohortAllocation.room_id.in_(room_ids),
        RoomCohortAllocation.academic_year == body.academic_year,
        RoomCohortAllocation.term == body.term,
    ))).scalars().all()) if room_ids else []
    allocations_by_room: dict[int, list[RoomCohortAllocation]] = {}
    for allocation in allocations:
        allocations_by_room.setdefault(allocation.room_id, []).append(allocation)

    preview: list[dict] = []
    for room in rooms:
        active_allocations = allocations_by_room.get(room.id, [])
        other_cohorts = sorted({item.cohort_label for item in active_allocations if item.cohort_label != body.cohort_label})
        current_cohort = any(item.cohort_label == body.cohort_label for item in active_allocations)
        matches = room_matches_rule(room.model_dump(), body.model_dump())
        if room.status != "available":
            state = "unavailable"
        elif other_cohorts:
            state = "occupied"
        elif current_cohort:
            state = "current"
        elif matches:
            state = "available"
        else:
            state = "ineligible"
        preview.append({
            **room.model_dump(),
            "building_name": building_names.get(room.building_id, ""),
            "state": state,
            "selectable": state == "available",
            "occupied_by": other_cohorts,
            "matches_rule": matches,
        })
    selectable = [item for item in preview if item["selectable"]]
    student_count = await target_student_count(session, tenant_id, body.campus_id, body.cohort_label)
    available_capacity = sum(item["capacity"] for item in selectable)
    return {
        "rooms": preview,
        "student_count": student_count,
        "available_capacity": available_capacity,
        "capacity_sufficient": student_count is None or available_capacity >= student_count,
        "capacity_gap": None if student_count is None else available_capacity - student_count,
        "recommended_room_count": None if student_count is None else ceil(student_count / 45),
    }


@router.post("/facilities/allocation-rules/preview")
async def preview_allocation_rule(
    body: ResourceAllocationRuleIn,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await require_manager(session, user)
    preview_data = await allocation_preview(session, tenant_id, body)
    preview_rooms = preview_data["rooms"]
    rooms = [item for item in preview_rooms if item["selectable"]]
    return {"code": 0, "message": "ok", "data": {
        "matched_count": len(rooms),
        "occupied_count": sum(item["state"] == "occupied" for item in preview_rooms),
        **{key: value for key, value in preview_data.items() if key != "rooms"},
        "rooms": preview_rooms[:500],
    }}


@router.get("/facilities/allocation-rules")
async def list_allocation_rules(
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    rules = list((await session.execute(select(ResourceAllocationRule).where(
        ResourceAllocationRule.tenant_id == tenant_id,
        ResourceAllocationRule.status == "active",
    ).order_by(ResourceAllocationRule.id.desc()))).scalars().all())
    counts = dict((await session.execute(select(
        RoomCohortAllocation.rule_id, func.count(RoomCohortAllocation.id),
    ).where(
        RoomCohortAllocation.tenant_id == tenant_id,
        RoomCohortAllocation.status == "active",
    ).group_by(RoomCohortAllocation.rule_id))).all())
    return {"code": 0, "message": "ok", "data": [
        {**rule.model_dump(), "matched_room_count": counts.get(rule.id, 0)} for rule in rules
    ]}


@router.post("/facilities/allocation-rules", status_code=status.HTTP_201_CREATED)
async def create_allocation_rule(
    body: ResourceAllocationRuleIn,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await require_manager(session, user)
    preview_data = await allocation_preview(session, tenant_id, body)
    preview_rooms = preview_data["rooms"]
    matched_by_id = {
        item["id"]: item for item in preview_rooms if item["selectable"]
    }
    if body.room_ids is not None:
        invalid_ids = [room_id for room_id in body.room_ids if room_id not in matched_by_id]
        if invalid_ids:
            raise HTTPException(status_code=422, detail="所选场室中包含不可分配或不符合规则的场室")
        rooms = [await session.get(Room, room_id) for room_id in body.room_ids]
        rooms = [room for room in rooms if room is not None]
    else:
        rooms = [await session.get(Room, room_id) for room_id in matched_by_id]
        rooms = [room for room in rooms if room is not None]
    if preview_data["student_count"] is not None:
        selected_capacity = sum(room.capacity for room in rooms)
        if selected_capacity < preview_data["student_count"]:
            raise HTTPException(status_code=422, detail=f"所选场室容量不足，还缺少 {preview_data['student_count'] - selected_capacity} 个座位")
    if not rooms:
        raise HTTPException(status_code=422, detail="当前规则没有匹配到可用场室，请先调整条件")
    rule_data = body.model_dump(exclude={"room_ids"})
    selected_building_ids = sorted(body.building_ids or ([] if body.building_id is None else [body.building_id]))
    rule_data["building_ids"] = selected_building_ids or None
    rule_data["building_id"] = selected_building_ids[0] if len(selected_building_ids) == 1 else None
    rule = ResourceAllocationRule(
        tenant_id=tenant_id,
        created_by=user.id,
        **rule_data,
    )
    session.add(rule)
    await session.flush()
    session.add_all([RoomCohortAllocation(
        tenant_id=tenant_id,
        rule_id=rule.id,
        room_id=room.id,
        cohort_label=body.cohort_label,
        academic_year=body.academic_year,
        term=body.term,
        allocation_mode=body.allocation_mode,
    ) for room in rooms])
    await session.commit()
    await session.refresh(rule)
    return {"code": 0, "message": "ok", "data": {
        **rule.model_dump(),
        "matched_room_count": len(rooms),
    }}


@router.delete("/facilities/allocation-rules/{rule_id}")
async def delete_allocation_rule(
    rule_id: int,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await require_manager(session, user)
    rule = await tenant_item(session, ResourceAllocationRule, rule_id, tenant_id, "资源划分规则")
    allocations = list((await session.execute(select(RoomCohortAllocation).where(
        RoomCohortAllocation.tenant_id == tenant_id,
        RoomCohortAllocation.rule_id == rule_id,
    ))).scalars().all())
    room_ids = {allocation.room_id for allocation in allocations}
    generated_classes = list((await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.home_room_id.in_(room_ids) if room_ids else False,
    ))).scalars().all())
    generated_class_ids = {item.id for item in generated_classes if item.id is not None}
    unassigned_students = 0
    if generated_class_ids:
        students = list((await session.execute(select(Student).where(
            Student.tenant_id == tenant_id,
            Student.class_id.in_(generated_class_ids),
        ))).scalars().all())
        for student in students:
            student.class_id = None
            session.add(student)
        unassigned_students = len(students)
        for class_item in generated_classes:
            await session.delete(class_item)
    for allocation in allocations:
        await session.delete(allocation)
    await session.delete(rule)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "deleted_class_count": len(generated_classes),
        "unassigned_student_count": unassigned_students,
    }}


"""班级规划输入输出模型与接口"""


CLASS_TYPE_LABELS = {
    'elite': '尖子班',
    'key': '重点班',
    'experimental': '实验班',
    'regular': '普通班',
}


class BuildingPreference(BaseModel):
    building_id: int
    preferred_types: list[str] = Field(
        default_factory=lambda: ['elite', 'key', 'experimental', 'regular'],
    )

    @model_validator(mode='after')
    def validate_types(self):
        allowed = {'elite', 'key', 'experimental', 'regular'}
        self.preferred_types = [t for t in self.preferred_types if t in allowed] or list(allowed)
        return self


class ClassPlanningPreviewIn(BaseModel):
    grade_id: int
    grade_group_id: int | None = None
    elite_count: int = Field(default=0, ge=0, le=500)
    key_count: int = Field(default=0, ge=0, le=500)
    experimental_count: int = Field(default=0, ge=0, le=500)
    regular_count: int = Field(default=0, ge=0, le=500)
    strategy: str = Field(default='random', pattern=r'^(random|snake|custom)$')
    custom_room_ids: list[int] | None = Field(default=None, min_length=1)
    custom_sub_strategy: str | None = Field(default=None, pattern=r'^(random|snake)$')
    building_preferences: list[BuildingPreference] = Field(default_factory=list)
    skip_generated: bool = True  # 默认仅使用尚未生成行政班的教室，避免重复生成；补增时仍可继续使用剩余资源
    inspect_only: bool = False


class ClassPlanningPlanItem(BaseModel):
    room_id: int
    room_name: str
    building_id: int
    building_name: str
    floor: int
    code: str | None
    capacity: int
    sequence_no: int
    class_type: str
    proposed_class_name: str


class ClassPlanningExecuteIn(ClassPlanningPreviewIn):
    plan: list[ClassPlanningPlanItem] = Field(default_factory=list)


async def _collect_planning_rooms(
    session: AsyncSession,
    tenant_id: int,
    grade_id: int,
    strategy: str,
    custom_room_ids: list[int] | None,
    custom_sub_strategy: str | None,
    skip_generated: bool,
    cohort_label: str | None = None,
) -> tuple[Grade, list[dict], str]:
    """返回(grade, 候选教室列表[{room, building_name}], 排序策略字符串)。
    候选项不带 building_preferences，由调用方使用。

    重要约束(与前端 planCandidateRooms 对齐)：候选教室**必须**来自已通过资源分配规则
    分配了届别的教室(即 RoomCohortAllocation 中有 status='active' 记录的 room_id)，
    未分配届别的教室(如全校区76间，仅38间分配了届别)一律排除。
    """
    grade = (await session.execute(
        select(Grade).where(Grade.tenant_id == tenant_id, Grade.id == grade_id)
    )).scalar_one_or_none()
    if not grade:
        raise HTTPException(status_code=404, detail="年级不存在")

    # 0) 加载全租户 active 的届别分配记录：room_id → 分配的 cohort_label 集合
    all_allocations = list((await session.execute(select(RoomCohortAllocation).where(
        RoomCohortAllocation.tenant_id == tenant_id,
        RoomCohortAllocation.status == "active",
    ))).scalars().all())
    alloc_by_room: dict[int, set[str]] = {}
    for alloc in all_allocations:
        alloc_by_room.setdefault(alloc.room_id, set()).add(alloc.cohort_label)
    # 已分配届别的 room_id 全集(第一层硬过滤：未分配届别的教室一律不进候选池)
    allocated_room_ids: set[int] = set(alloc_by_room.keys())

    # 1) 已生成班级的教室 → home_room_id 集合
    skip_ids: set[int] = set()
    if skip_generated:
        rows = (await session.execute(
            select(Class.home_room_id).where(
                Class.tenant_id == tenant_id,
                Class.home_room_id.isnot(None),
                Class.grade_id == grade_id,
                *([Class.cohort_label == cohort_label] if cohort_label else []),
            )
        )).fetchall()
        skip_ids = {r for (r,) in rows if r is not None}

    # 2) 按年级 campus_id 限定楼宇，并提取该楼宇内已分配届别的 cohort_label 集合
    campus_ids: set[int] = set()
    if grade.campus_id:
        campus_ids.add(grade.campus_id)
    buildings = (await session.execute(select(Building).where(Building.tenant_id == tenant_id))).scalars().all()
    building_campus = {b.id: b.campus_id for b in buildings}
    campus_building_ids: set[int] = {
        b.id for b in buildings
        if not campus_ids or building_campus.get(b.id) in campus_ids
    }
    # 该楼宇范围内出现过的届别标签(对应前端 planGradeCohortLabels)
    grade_cohort_labels: set[str] = set()
    for rid, cohorts in alloc_by_room.items():
        # 通过 Room.building_id 归属判断会多一次查询，这里简化：
        # 直接从下面的 Room 查询里再过滤届别；此处仅预留给后续 IN 过滤优化用
        pass

    # 3) 查询普通教室(限定楼宇范围内)，再叠加届别分配硬约束
    where = [Room.tenant_id == tenant_id, Room.room_type == 'classroom']
    stmt = select(Room, Building.name.label('building_name')).join(
        Building, Building.id == Room.building_id,
    ).where(*where)
    rows = (await session.execute(stmt)).all()
    candidates = []
    custom_selected_ids = set(custom_room_ids or [])
    for room, bname in rows:
        # 第一层硬约束：必须是已通过资源分配规则分配了届别的教室
        if room.id not in allocated_room_ids:
            continue
        if room.id in skip_ids:
            continue
        if campus_building_ids and room.building_id not in campus_building_ids:
            continue
        # 第二层硬约束：必须属于当前选中的年级部/届别。
        if cohort_label and cohort_label not in alloc_by_room.get(room.id, set()):
            continue
        if strategy == 'custom' and custom_selected_ids and room.id not in custom_selected_ids:
            continue
        candidates.append({
            'room': room,
            'building_name': bname,
        })
    # 排序策略
    actual_strategy = strategy
    if strategy == 'custom' and custom_sub_strategy:
        actual_strategy = custom_sub_strategy
    if actual_strategy == 'random':
        random.shuffle(candidates)
    else:
        # snake or default: sort deterministic by building_id → floor → code → id then snake
        candidates.sort(key=lambda x: (
            x['building_name'],
            x['room'].floor,
            x['room'].code or '',
            x['room'].name,
            x['room'].id,
        ))
        if actual_strategy == 'snake':
            # 蛇形排序：按楼宇分组，然后每层顺序交替，这里简化为：先按(楼宇, 楼层, 编号)排序，
            # 楼层 奇/偶顺序交替，更直观。
            grouped: dict[tuple[str, int], list[dict]] = {}
            for c in candidates:
                grouped.setdefault((c['building_name'], c['room'].floor), []).append(c)
            ordered: list[dict] = []
            sorted_keys = sorted(grouped.keys())
            for idx, k in enumerate(sorted_keys):
                arr = list(grouped[k])
                if idx % 2 == 1:
                    arr.reverse()  # 反向 → 蛇形
                ordered.extend(arr)
            candidates = ordered
    return grade, candidates, actual_strategy


def _apply_building_preferences(candidates: list[dict], preferences: list[BuildingPreference]) -> list[dict]:
    """把栋优先的教室（preferred_types 含优先级高的类型）提到队列前端，保持原顺序其它。"""
    if not preferences:
        return candidates
    pref_map: dict[int, set[str]] = {
        p.building_id: set(p.preferred_types) for p in preferences
    }
    # 优先度：elite > key > experimental > regular，栋中含 elite/key prefs 的先
    def bucket(c) -> int:
        bid = c['room'].building_id
        prefs = pref_map.get(bid)
        if not prefs:
            return 4
        if 'elite' in prefs:
            return 0
        if 'key' in prefs:
            return 1
        if 'experimental' in prefs:
            return 2
        if 'regular' in prefs and len(prefs) == 1:
            return 5
        return 3
    candidates_sorted = sorted(enumerate(candidates), key=lambda x: (bucket(x[1]), x[0]))
    return [c for _, c in candidates_sorted]


async def _run_class_planning_preview(
    session: AsyncSession,
    tenant_id: int,
    body: ClassPlanningPreviewIn,
) -> dict:
    cohort_label: str | None = None
    if body.grade_group_id is not None:
        unit = (await session.execute(select(OrganizationUnit).where(
            OrganizationUnit.tenant_id == tenant_id,
            OrganizationUnit.id == body.grade_group_id,
            OrganizationUnit.unit_type == 'grade_group',
            OrganizationUnit.status == 'active',
        ))).scalar_one_or_none()
        if not unit:
            raise HTTPException(status_code=422, detail="所选年级部不存在或已停用")
        cohort_label = unit.cohort_label
        if not cohort_label:
            raise HTTPException(status_code=422, detail="所选年级部缺少届别编码")

    grade, candidates, _strategy = await _collect_planning_rooms(
        session, tenant_id, body.grade_id, body.strategy,
        body.custom_room_ids, body.custom_sub_strategy, body.skip_generated, cohort_label,
    )
    candidates = _apply_building_preferences(candidates, body.building_preferences)

    # 计数验证
    total_requested = body.elite_count + body.key_count + body.experimental_count + body.regular_count
    student_count = (await session.execute(select(func.count(Student.id)).where(
        Student.tenant_id == tenant_id,
        Student.grade_id == grade.id,
    ))).scalar() or 0
    assigned_student_count = (await session.execute(select(func.count(Student.id)).where(
        Student.tenant_id == tenant_id,
        Student.grade_id == grade.id,
        Student.class_id.isnot(None),
    ))).scalar() or 0
    remaining_student_count = max(0, student_count - assigned_student_count)
    available_capacity = sum(max(0, int(c['room'].capacity or 0)) for c in candidates)
    capacity_so_far = 0
    recommended_class_count = 0
    for candidate in sorted(candidates, key=lambda item: int(item['room'].capacity or 0), reverse=True):
        if capacity_so_far >= remaining_student_count:
            break
        capacity_so_far += max(0, int(candidate['room'].capacity or 0))
        recommended_class_count += 1

    # 数量为 0 是合法的资源探查请求：选择年级部时前端先用它读取
    # 学生数、剩余容量和后端建议班级数，不能当成输入错误。
    if total_requested > len(candidates):
        raise HTTPException(status_code=422, detail=(
            f"可用教室 {len(candidates)} 间，少于需生成的 {total_requested} 个班；"
            "请先在资源分配规则中分配更多教室到对应届别。"
        ))

    # 为每个类型建池，按 building 限制分配
    elite_pool = [f'elite'] * body.elite_count
    key_pool = [f'key'] * body.key_count
    exp_pool = [f'experimental'] * body.experimental_count
    reg_pool = [f'regular'] * body.regular_count

    def _next_type_from_pools(prefs: set[str]) -> str | None:
        # 按优先级：elite → key → experimental → regular，但只取 prefs 允许的
        order = [
            ('elite', elite_pool),
            ('key', key_pool),
            ('experimental', exp_pool),
            ('regular', reg_pool),
        ]
        for tname, pool in order:
            if pool and tname in prefs:
                return pool.pop(0)
        return None

    # 取年级前缀
    grade_label = grade.name.replace('年级', '')

    # 已存在班级数（作为序号起点）
    existing_count = (await session.execute(select(func.count(Class.id)).where(
        Class.tenant_id == tenant_id,
        Class.grade_id == grade.id,
    ))).scalar() or 0

    # building preferences 的反向映射
    pref_map: dict[int, set[str]] = {
        p.building_id: set(p.preferred_types) for p in body.building_preferences
    }
    all_types = {'elite', 'key', 'experimental', 'regular'}

    plan: list[ClassPlanningPlanItem] = []
    used: set[int] = set()
    # 第一遍：building_preferences 有限制的类型
    for c in candidates:
        if len(plan) >= total_requested:
            break
        rid = c['room'].id
        if rid in used:
            continue
        bid = c['room'].building_id
        prefs = pref_map.get(bid, all_types)
        t = _next_type_from_pools(prefs)
        if t is None:
            continue
        used.add(rid)
        seq = existing_count + len(plan) + 1
        plan.append(ClassPlanningPlanItem(
            room_id=rid,
            room_name=c['room'].name,
            building_id=bid,
            building_name=c['building_name'],
            floor=c['room'].floor,
            code=c['room'].code,
            capacity=c['room'].capacity,
            sequence_no=seq,
            class_type=t,
            proposed_class_name=f'{grade_label}（{seq}）班',
        ))
    # 第二遍：剩下池子中的类型，用没有限制的教室填充
    if len(plan) < total_requested:
        for c in candidates:
            if len(plan) >= total_requested:
                break
            rid = c['room'].id
            if rid in used:
                continue
            bid = c['room'].building_id
            prefs = pref_map.get(bid, all_types)
            t = _next_type_from_pools(prefs)
            if t is None:
                # 再兜底：即使building不允许，剩下教室如果无法满足也必须分配（但此分支仅当类型数 > 教室时才出现，不过前面限制了总数，一般不会到）
                t = _next_type_from_pools(all_types)
            if t is None:
                continue
            used.add(rid)
            seq = existing_count + len(plan) + 1
            plan.append(ClassPlanningPlanItem(
                room_id=rid,
                room_name=c['room'].name,
                building_id=bid,
                building_name=c['building_name'],
                floor=c['room'].floor,
                code=c['room'].code,
                capacity=c['room'].capacity,
                sequence_no=seq,
                class_type=t,
                proposed_class_name=f'{grade_label}（{seq}）班',
            ))
    return {
        'grade_id': grade.id,
        'grade_group_id': body.grade_group_id,
        'cohort_label': cohort_label,
        'grade_name': grade.name,
        'grade_label': grade_label,
        'existing_count': existing_count,
        'available_room_count': len(candidates),
        'requested_total': total_requested,
        'item_count': len(plan),
        'items': plan,
        'remaining_pools': {
            'elite': len(elite_pool),
            'key': len(key_pool),
            'experimental': len(exp_pool),
            'regular': len(reg_pool),
        },
        'student_count': student_count,
        'assigned_student_count': assigned_student_count,
        'remaining_student_count': remaining_student_count,
        'available_capacity': available_capacity,
        'capacity_sufficient': available_capacity >= remaining_student_count,
        'capacity_gap': max(0, remaining_student_count - available_capacity),
        'recommended_class_count': recommended_class_count,
    }


@router.post("/facilities/class-planning/preview")
async def preview_class_planning(
    body: ClassPlanningPreviewIn,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await require_manager(session, user)
    data = await _run_class_planning_preview(session, tenant_id, body)
    return {"code": 0, "message": "ok", "data": data}


@router.post("/facilities/class-planning/execute")
async def execute_class_planning(
    body: ClassPlanningExecuteIn,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    await require_manager(session, user)
    plan = body.plan
    if not plan:
        # 没给 plan，就自己根据输入参数重新预览一份
        data = await _run_class_planning_preview(session, tenant_id, body)
        plan = data['items']
    grade = (await session.execute(select(Grade).where(
        Grade.tenant_id == tenant_id, Grade.id == body.grade_id,
    ))).scalar_one_or_none()
    if not grade:
        raise HTTPException(status_code=404, detail="年级不存在")
    cohort_label = None
    if body.grade_group_id is not None:
        unit = (await session.execute(select(OrganizationUnit).where(
            OrganizationUnit.tenant_id == tenant_id,
            OrganizationUnit.id == body.grade_group_id,
            OrganizationUnit.unit_type == 'grade_group',
            OrganizationUnit.status == 'active',
        ))).scalar_one_or_none()
        if not unit or not unit.cohort_label:
            raise HTTPException(status_code=422, detail="所选年级部不存在或缺少届别编码")
        cohort_label = unit.cohort_label
    else:
        cohort_label = expected_cohort_label(await current_academic_year(session, tenant_id), grade.level)
    # 唯一性：同一个 home_room_id / 同届同 name 不能重复
    existing_home_room_ids = {r for (r,) in (await session.execute(select(Class.home_room_id).where(
        Class.tenant_id == tenant_id, Class.grade_id == grade.id,
        Class.cohort_label == cohort_label, Class.home_room_id.isnot(None),
    ))).fetchall() if r is not None}
    existing_names = {r for (r,) in (await session.execute(select(Class.name).where(
        Class.tenant_id == tenant_id, Class.grade_id == grade.id, Class.cohort_label == cohort_label,
    ))).fetchall()}
    created: list[Class] = []
    for item in plan:
        if item.room_id in existing_home_room_ids:
            continue
        name = normalize_entity_name(item.proposed_class_name) or item.proposed_class_name
        dedup_idx = 0
        final_name = name
        while final_name in existing_names:
            dedup_idx += 1
            final_name = f'{name}（补{dedup_idx}）'
        existing_names.add(final_name)
        existing_home_room_ids.add(item.room_id)
        new_class = Class(
            tenant_id=tenant_id,
            grade_id=grade.id,
            name=final_name,
            class_type=item.class_type,
            home_room_id=item.room_id,
            planned_student_count=item.capacity,
            cohort_label=cohort_label,
        )
        session.add(new_class)
        created.append(new_class)
    await session.flush()
    await session.commit()
    summary: dict = {}
    for c in created:
        summary[c.class_type] = summary.get(c.class_type, 0) + 1
    readable_summary = {CLASS_TYPE_LABELS.get(k, k): v for k, v in summary.items()}
    return {"code": 0, "message": f"成功生成 {len(created)} 个行政班", "data": {
        "created_count": len(created),
        "by_type": readable_summary,
        "class_ids": [c.id for c in created if c.id is not None],
    }}


@router.get("/meetings")
async def list_meetings(tenant_id: int = Depends(get_current_tenant), session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)):
    rows = (await session.execute(select(Meeting, Room.name).join(Room, Room.id == Meeting.room_id)
        .where(Meeting.tenant_id == tenant_id).order_by(Meeting.start_at.desc()))).all()
    return {"code": 0, "message": "ok", "data": [{**meeting.model_dump(), "room_name": room_name} for meeting, room_name in rows]}

@router.post("/meetings", status_code=status.HTTP_201_CREATED)
async def create_meeting(body: MeetingIn, tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session), user: User = Depends(get_current_user)):
    await require_manager(session, user)
    room = await tenant_item(session, Room, body.room_id, tenant_id, "场室")
    if room.status != "available" or not room.is_meeting_enabled:
        raise HTTPException(status_code=422, detail="该场室当前不可用于会议")
    conflict = (await session.execute(select(func.count(RoomBooking.id)).where(
        RoomBooking.tenant_id == tenant_id, RoomBooking.room_id == room.id, RoomBooking.status == "active",
        RoomBooking.start_at < body.end_at, RoomBooking.end_at > body.start_at,
    ))).scalar_one()
    if conflict:
        raise HTTPException(status_code=409, detail="该场室在所选时间已被占用")
    meeting = Meeting(tenant_id=tenant_id, organizer_id=user.id, **body.model_dump()); session.add(meeting)
    await session.flush()
    session.add(RoomBooking(tenant_id=tenant_id, room_id=room.id, source_type="meeting", source_id=meeting.id,
        title=meeting.title, start_at=meeting.start_at, end_at=meeting.end_at))
    await session.commit(); await session.refresh(meeting)
    return {"code": 0, "message": "ok", "data": {**meeting.model_dump(), "room_name": room.name}}
