"""Persisted school organization and scoped staff appointments."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.enums import BaseUserRole
from app.models.org import Grade, OrganizationUnit, StaffAppointment, StudentGradeMembership, Tenant, TenantConfig, User
from app.models.enums import UserStatus
from app.services.organization import build_organization_tree

router = APIRouter(prefix="/organization", tags=["组织机构"])

UNIT_TYPES = {"department", "grade_group", "subject_group", "admin_class"}
POSITION_CODES = {"principal", "academic_director", "grade_director", "head_teacher", "deputy_head_teacher", "member"}


class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    unit_type: str = Field(default="department")
    parent_id: int | None = None
    academic_year: str | None = Field(default=None, max_length=20)
    cohort_label: str | None = Field(default=None, max_length=30)
    grade_id: int | None = None
    sort_order: int = 0


class UnitUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: int | None = None
    academic_year: str | None = Field(default=None, max_length=20)
    cohort_label: str | None = Field(default=None, max_length=30)
    grade_id: int | None = None
    sort_order: int | None = None
    status: str | None = Field(default=None, pattern=r"^(active|archived)$")


class AppointmentIn(BaseModel):
    organization_unit_id: int
    staff_id: int
    position_code: str
    academic_year: str | None = Field(default=None, max_length=20)
    replace_grade_assignment: bool = False


class AutoAppointmentPlan(BaseModel):
    source_unit_id: int
    teacher_ids: list[int] = Field(default_factory=list)
    required_count: int = Field(ge=0)


class AutoAppointmentIn(BaseModel):
    target_unit_id: int
    academic_year: str | None = Field(default=None, max_length=20)
    position_code: str = "member"
    plans: list[AutoAppointmentPlan] = Field(min_length=1)


def get_new_teacher_ids(teacher_ids: list[int], target_staff_ids: set[int]) -> list[int]:
    """Return only teachers not already assigned to the target grade group."""
    return list(dict.fromkeys(teacher_id for teacher_id in teacher_ids if teacher_id not in target_staff_ids))


def _require_principal(user: User) -> None:
    if user.role != BaseUserRole.director:
        raise HTTPException(status_code=403, detail="仅校长管理员可以维护组织机构")


async def _tenant_unit(session: AsyncSession, tenant_id: int, unit_id: int) -> OrganizationUnit:
    unit = await session.get(OrganizationUnit, unit_id)
    if unit is None or unit.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="组织节点不存在")
    return unit


GRADE_CENTER_CONFIG_KEY = "org_grade_center"


@router.get("/grade-center", summary="查询年级管理中心单元")
async def get_grade_center(
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == GRADE_CENTER_CONFIG_KEY,
    ))).scalars().first()
    unit_id = int(row.config_value.get("unit_id", 0)) if row and isinstance(row.config_value, dict) else 0
    unit = await session.get(OrganizationUnit, unit_id) if unit_id else None
    if unit is None or unit.tenant_id != tenant_id or unit.status != "active":
        return {"code": 0, "message": "ok", "data": {"unit_id": None, "unit_name": None}}
    return {"code": 0, "message": "ok", "data": {"unit_id": unit.id, "unit_name": unit.name}}


@router.put("/grade-center/{unit_id}", summary="设置年级管理中心单元(全校唯一)")
async def set_grade_center(
    unit_id: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_principal(user)
    unit = await session.get(OrganizationUnit, unit_id)
    if unit is None or unit.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="组织单元不存在")
    row = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == GRADE_CENTER_CONFIG_KEY,
    ))).scalars().first()
    existing_id = int(row.config_value.get("unit_id", 0)) if row and isinstance(row.config_value, dict) else 0
    if existing_id and existing_id != unit_id:
        existing = await session.get(OrganizationUnit, existing_id)
        if existing is not None and existing.tenant_id == tenant_id and existing.status == "active":
            raise HTTPException(status_code=422, detail=f"年级管理中心已存在（{existing.name}），全校只能有一个")
    if row is None:
        row = TenantConfig(tenant_id=tenant_id, config_key=GRADE_CENTER_CONFIG_KEY, config_value={"unit_id": unit_id}, updated_by=user.id)
        session.add(row)
    else:
        row.config_value = {"unit_id": unit_id}
        row.updated_by = user.id
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"unit_id": unit_id, "unit_name": unit.name}}


@router.get("/tree")
async def organization_tree(
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_principal(user)
    school = await session.get(Tenant, tenant_id)
    units = list((await session.execute(
        select(OrganizationUnit).where(
            OrganizationUnit.tenant_id == tenant_id,
            OrganizationUnit.status == "active",
        ).order_by(OrganizationUnit.sort_order, OrganizationUnit.id)
    )).scalars().all())
    counts = dict((await session.execute(
        select(StaffAppointment.organization_unit_id, func.count(StaffAppointment.id))
        .where(StaffAppointment.tenant_id == tenant_id, StaffAppointment.status == "active")
        .group_by(StaffAppointment.organization_unit_id)
    )).all())
    tree = build_organization_tree([item.model_dump() for item in units], counts)
    return {"code": 0, "message": "ok", "data": {
        "school": {"id": tenant_id, "name": school.name if school else "当前学校"},
        "units": tree,
    }}


async def _ensure_single_grade_center_name(session: AsyncSession, tenant_id: int, name: str, exclude_unit_id: int | None = None) -> None:
    """「年级管理中心」是保留名,全校只能存在一个(防止绕过开关直接建同名单元)。"""
    if name.strip() != "年级管理中心":
        return
    stmt = select(OrganizationUnit.id).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.name == "年级管理中心",
        OrganizationUnit.status == "active",
    )
    if exclude_unit_id is not None:
        stmt = stmt.where(OrganizationUnit.id != exclude_unit_id)
    exists = (await session.execute(stmt)).scalar()
    if exists:
        raise HTTPException(status_code=422, detail="年级管理中心已存在，全校只能有一个")


@router.post("/units", status_code=status.HTTP_201_CREATED)
async def create_unit(
    body: UnitIn,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_principal(user)
    if body.unit_type not in UNIT_TYPES:
        raise HTTPException(status_code=422, detail="不支持的组织类型")
    if body.grade_id is not None:
        if body.unit_type != "grade_group":
            raise HTTPException(status_code=422, detail="只有年级部可以绑定对应年级")
        grade = await session.get(Grade, body.grade_id)
        if grade is None or grade.tenant_id != tenant_id:
            raise HTTPException(status_code=422, detail="对应年级不存在")
    if body.parent_id is not None:
        await _tenant_unit(session, tenant_id, body.parent_id)
    await _ensure_single_grade_center_name(session, tenant_id, body.name)
    unit = OrganizationUnit(tenant_id=tenant_id, **body.model_dump())
    session.add(unit)
    await session.commit()
    await session.refresh(unit)
    return {"code": 0, "message": "ok", "data": unit.model_dump()}


@router.patch("/units/{unit_id}")
async def update_unit(
    unit_id: int,
    body: UnitUpdateIn,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_principal(user)
    unit = await _tenant_unit(session, tenant_id, unit_id)
    values = body.model_dump(exclude_unset=True)
    if "grade_id" in values:
        if unit.unit_type != "grade_group" and values["grade_id"] is not None:
            raise HTTPException(status_code=422, detail="只有年级部可以绑定对应年级")
        if values["grade_id"] is not None:
            grade = await session.get(Grade, values["grade_id"])
            if grade is None or grade.tenant_id != tenant_id:
                raise HTTPException(status_code=422, detail="对应年级不存在")
    if values.get("parent_id") == unit_id:
        raise HTTPException(status_code=422, detail="组织节点不能成为自己的上级")
    if values.get("parent_id") is not None:
        await _tenant_unit(session, tenant_id, values["parent_id"])
    if values.get("name"):
        await _ensure_single_grade_center_name(session, tenant_id, values["name"], exclude_unit_id=unit_id)
    for key, value in values.items():
        setattr(unit, key, value)
    await session.commit()
    await session.refresh(unit)
    return {"code": 0, "message": "ok", "data": unit.model_dump()}


@router.delete("/units/{unit_id}")
async def delete_unit(
    unit_id: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    """删除未被引用的组织节点；有学生年级快照时必须保留。"""
    _require_principal(user)
    unit = await _tenant_unit(session, tenant_id, unit_id)
    linked_students = (await session.execute(select(func.count(StudentGradeMembership.id)).where(
        StudentGradeMembership.tenant_id == tenant_id,
        StudentGradeMembership.grade_unit_id == unit_id,
    ))).scalar_one()
    child_count = (await session.execute(select(func.count(OrganizationUnit.id)).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.parent_id == unit_id,
        OrganizationUnit.status == "active",
    ))).scalar_one()
    appointment_count = (await session.execute(select(func.count(StaffAppointment.id)).where(
        StaffAppointment.tenant_id == tenant_id,
        StaffAppointment.organization_unit_id == unit_id,
        StaffAppointment.status == "active",
    ))).scalar_one()
    if linked_students or child_count or appointment_count:
        raise HTTPException(status_code=409, detail={
            "message": "组织节点存在关联数据，不能删除",
            "student_memberships": linked_students,
            "children": child_count,
            "active_appointments": appointment_count,
        })
    await session.delete(unit)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"id": unit_id}}


@router.get("/appointments")
async def list_appointments(
    include_archived: bool = False,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_principal(user)
    statement = select(StaffAppointment, User.name, OrganizationUnit.name).where(
        StaffAppointment.tenant_id == tenant_id,
        *( () if include_archived else (StaffAppointment.status == "active",) ),
    ).join(User, User.id == StaffAppointment.staff_id).join(OrganizationUnit, OrganizationUnit.id == StaffAppointment.organization_unit_id).order_by(OrganizationUnit.sort_order, User.name)
    rows = (await session.execute(statement)).all()
    return {"code": 0, "message": "ok", "data": [{
        **item.model_dump(), "staff_name": staff_name, "organization_name": organization_name,
    } for item, staff_name, organization_name in rows]}


@router.post("/appointments", status_code=status.HTTP_201_CREATED)
async def create_appointment(
    body: AppointmentIn,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_principal(user)
    if body.position_code not in POSITION_CODES:
        raise HTTPException(status_code=422, detail="不支持的岗位")
    target_unit = await _tenant_unit(session, tenant_id, body.organization_unit_id)
    staff = await session.get(User, body.staff_id)
    if staff is None or staff.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="人员账号不存在")
    existing = (await session.execute(select(StaffAppointment).where(
        StaffAppointment.tenant_id == tenant_id,
        StaffAppointment.organization_unit_id == body.organization_unit_id,
        StaffAppointment.staff_id == body.staff_id,
        StaffAppointment.position_code == body.position_code,
        StaffAppointment.academic_year == body.academic_year,
        StaffAppointment.status == "active",
    ))).scalar_one_or_none()
    if existing:
        return {"code": 0, "message": "ok", "data": existing.model_dump()}
    if target_unit.unit_type == "grade_group":
        other_grade_appointments = list((await session.execute(
            select(StaffAppointment).join(OrganizationUnit, OrganizationUnit.id == StaffAppointment.organization_unit_id).where(
                StaffAppointment.tenant_id == tenant_id,
                StaffAppointment.staff_id == body.staff_id,
                StaffAppointment.status == "active",
                OrganizationUnit.unit_type == "grade_group",
                StaffAppointment.organization_unit_id != body.organization_unit_id,
            )
        )).scalars().all())
        if other_grade_appointments and not body.replace_grade_assignment:
            raise HTTPException(status_code=409, detail="该教师已在其他年级部任职，请使用手动重新分配")
        if body.replace_grade_assignment:
            for appointment in other_grade_appointments:
                appointment.status = "archived"
    item = StaffAppointment(
        tenant_id=tenant_id, appointed_by=user.id,
        organization_unit_id=body.organization_unit_id,
        staff_id=body.staff_id,
        position_code=body.position_code,
        academic_year=body.academic_year,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"code": 0, "message": "ok", "data": item.model_dump()}


@router.post("/appointments/auto-allocate")
async def auto_allocate_appointments(
    body: AutoAppointmentIn,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    """Validate and atomically allocate teachers to one grade group."""
    _require_principal(user)
    if body.position_code not in POSITION_CODES:
        raise HTTPException(status_code=422, detail="不支持的岗位")
    target_unit = await _tenant_unit(session, tenant_id, body.target_unit_id)
    if target_unit.unit_type != "grade_group" or target_unit.status != "active":
        raise HTTPException(status_code=422, detail="目标组织必须是启用中的年级部")

    source_ids = [plan.source_unit_id for plan in body.plans]
    if len(source_ids) != len(set(source_ids)):
        raise HTTPException(status_code=422, detail="同一学科教研组不能重复提交")
    source_units = list((await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.id.in_(source_ids),
        OrganizationUnit.unit_type == "subject_group",
        OrganizationUnit.status == "active",
    ))).scalars().all())
    if len(source_units) != len(source_ids):
        raise HTTPException(status_code=422, detail="教师来源必须是当前学校启用中的学科教研组")
    source_units_by_id = {unit.id: unit for unit in source_units}

    active_target = list((await session.execute(select(StaffAppointment).where(
        StaffAppointment.tenant_id == tenant_id,
        StaffAppointment.organization_unit_id == body.target_unit_id,
        StaffAppointment.academic_year == body.academic_year,
        StaffAppointment.status == "active",
    ))).scalars().all())
    target_staff_ids = {item.staff_id for item in active_target}
    existing_target_appointments = list((await session.execute(select(StaffAppointment).where(
        StaffAppointment.tenant_id == tenant_id,
        StaffAppointment.organization_unit_id == body.target_unit_id,
        StaffAppointment.position_code == body.position_code,
        StaffAppointment.academic_year == body.academic_year,
    ))).scalars().all())
    existing_target_by_staff = {item.staff_id: item for item in existing_target_appointments}
    grade_units = select(OrganizationUnit.id).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type == "grade_group",
        OrganizationUnit.status == "active",
    )
    locked_staff_ids = set((await session.execute(select(StaffAppointment.staff_id).where(
        StaffAppointment.tenant_id == tenant_id,
        StaffAppointment.organization_unit_id.in_(grade_units),
        StaffAppointment.organization_unit_id != body.target_unit_id,
        StaffAppointment.status == "active",
    ))).scalars().all())

    planned_ids: set[int] = set()
    to_create: list[StaffAppointment] = []
    reactivated_count = 0
    shortage: list[str] = []
    for plan in body.plans:
        source_unit = source_units_by_id[plan.source_unit_id]
        teacher_ids = list(dict.fromkeys(plan.teacher_ids))
        if len(teacher_ids) != len(plan.teacher_ids):
            raise HTTPException(status_code=422, detail=f"{source_unit.name}存在重复教师")
        source_staff_ids = set((await session.execute(select(StaffAppointment.staff_id).where(
            StaffAppointment.tenant_id == tenant_id,
            StaffAppointment.organization_unit_id == source_unit.id,
            StaffAppointment.status == "active",
        ))).scalars().all())
        current_count = len(target_staff_ids & source_staff_ids)
        required_new = max(0, plan.required_count - current_count)
        new_teacher_ids = get_new_teacher_ids(teacher_ids, target_staff_ids)
        if len(new_teacher_ids) != required_new:
            raise HTTPException(status_code=409, detail=f"{source_unit.name}需要新增 {required_new} 人，提交了 {len(new_teacher_ids)} 人")
        if not new_teacher_ids:
            continue
        valid_count = (await session.execute(select(func.count(User.id)).where(
            User.tenant_id == tenant_id,
            User.id.in_(new_teacher_ids),
            User.status == UserStatus.active,
            User.role != BaseUserRole.director,
        ))).scalar_one()
        invalid = set(new_teacher_ids) - set((await session.execute(select(User.id).where(
            User.tenant_id == tenant_id,
            User.id.in_(new_teacher_ids),
            User.status == UserStatus.active,
            User.role != BaseUserRole.director,
        ))).scalars().all())
        if valid_count != len(new_teacher_ids) or invalid:
            raise HTTPException(status_code=409, detail=f"{source_unit.name}包含不可用教师")
        if not set(new_teacher_ids).issubset(source_staff_ids):
            raise HTTPException(status_code=409, detail=f"{source_unit.name}存在不属于该学科组的教师")
        conflict_ids = set(new_teacher_ids) & (locked_staff_ids | planned_ids)
        if conflict_ids:
            raise HTTPException(status_code=409, detail="存在已在其他年级部任职或重复安排的教师")
        planned_ids.update(new_teacher_ids)
        for teacher_id in new_teacher_ids:
            existing = existing_target_by_staff.get(teacher_id)
            if existing is not None:
                if existing.status != "active":
                    existing.status = "active"
                    existing.appointed_by = user.id
                    reactivated_count += 1
                continue
            to_create.append(StaffAppointment(
                tenant_id=tenant_id,
                appointed_by=user.id,
                organization_unit_id=body.target_unit_id,
                staff_id=teacher_id,
                position_code=body.position_code,
                academic_year=body.academic_year,
                status="active",
            ))

    if shortage:
        raise HTTPException(status_code=409, detail="；".join(shortage))
    if not to_create:
        if reactivated_count:
            await session.commit()
        return {"code": 0, "message": "ok", "data": {"created_count": reactivated_count, "target_unit_id": body.target_unit_id}}

    # The unique constraint is the final idempotency guard for concurrent retries.
    # A second identical request must be a successful no-op instead of a 500.
    statement = postgres_insert(StaffAppointment).values([
        {
            "tenant_id": item.tenant_id,
            "organization_unit_id": item.organization_unit_id,
            "staff_id": item.staff_id,
            "position_code": item.position_code,
            "academic_year": item.academic_year,
            "status": item.status,
            "appointed_by": item.appointed_by,
        }
        for item in to_create
    ]).on_conflict_do_nothing(constraint="uq_staffappointment_scope")
    result = await session.execute(statement)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"created_count": (result.rowcount or 0) + reactivated_count, "target_unit_id": body.target_unit_id}}


@router.delete("/appointments/{appointment_id}")
async def delete_appointment(
    appointment_id: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_principal(user)
    item = await session.get(StaffAppointment, appointment_id)
    if item is None or item.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="岗位任命不存在")
    await session.execute(delete(StaffAppointment).where(StaffAppointment.id == appointment_id))
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"id": appointment_id}}


@router.post("/appointments/archive-by-unit/{unit_id}")
async def archive_unit_appointments(
    unit_id: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    """结束一个年级部的任职周期，保留历史任命和教师账号。"""
    _require_principal(user)
    await _tenant_unit(session, tenant_id, unit_id)
    result = await session.execute(
        update(StaffAppointment)
        .where(StaffAppointment.tenant_id == tenant_id, StaffAppointment.organization_unit_id == unit_id, StaffAppointment.status == "active")
        .values(status="archived")
    )
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"unit_id": unit_id, "archived_count": result.rowcount or 0}}
