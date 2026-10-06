"""Persisted school organization and scoped staff appointments."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.enums import BaseUserRole
from app.models.org import Grade, OrganizationUnit, StaffAppointment, StudentGradeMembership, Subject, Tenant, TenantConfig, User
from app.services.org.organization import build_organization_tree, current_organization_units, organization_subtree_ids
from app.services.org.cohort import normalize_cohort_label

router = APIRouter(prefix="/organization", tags=["组织机构"])

UNIT_TYPES = {"department", "grade_group", "subject_group", "admin_class"}
POSITION_CODES = {"principal", "academic_director", "grade_director", "head_teacher", "deputy_head_teacher", "member"}


def validate_grade_group_binding(unit_type: str, grade_id: int | None) -> None:
    """Keep the grade-group/grade relationship explicit and consistent."""
    if unit_type == "grade_group" and grade_id is None:
        raise ValueError("年级部必须绑定对应年级")
    if unit_type != "grade_group" and grade_id is not None:
        raise ValueError("只有年级部可以绑定对应年级")


def validate_subject_group_binding(unit_type: str, subject_id: int | None) -> None:
    """A subject group must point to an explicit subject; names are not a relation."""
    if unit_type == "subject_group" and subject_id is None:
        raise ValueError("学科组必须关联科目")
    if unit_type != "subject_group" and subject_id is not None:
        raise ValueError("只有学科组可以关联科目")


async def _tenant_subject(session: AsyncSession, tenant_id: int, subject_id: int) -> Subject:
    subject = await session.get(Subject, subject_id)
    if subject is None or subject.tenant_id != tenant_id:
        raise HTTPException(status_code=422, detail="关联科目不存在或不属于当前租户")
    return subject


class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    unit_type: str = Field(default="department")
    subject_id: int | None = None
    parent_id: int | None = None
    academic_year: str | None = Field(default=None, max_length=20)
    cohort_label: str | None = Field(default=None, max_length=30)
    grade_id: int | None = None
    sort_order: int = 0

    @field_validator("cohort_label", mode="before")
    @classmethod
    def normalize_cohort(cls, value: str | None) -> str | None:
        return normalize_cohort_label(value)


class UnitUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: int | None = None
    subject_id: int | None = None
    academic_year: str | None = Field(default=None, max_length=20)
    cohort_label: str | None = Field(default=None, max_length=30)
    grade_id: int | None = None
    sort_order: int | None = None
    status: str | None = Field(default=None, pattern=r"^(active|archived)$")

    @field_validator("cohort_label", mode="before")
    @classmethod
    def normalize_cohort(cls, value: str | None) -> str | None:
        return normalize_cohort_label(value)


class AppointmentIn(BaseModel):
    organization_unit_id: int
    staff_id: int
    position_code: str
    academic_year: str | None = Field(default=None, max_length=20)
    replace_grade_assignment: bool = False


def _require_principal(user: User) -> None:
    if user.role != BaseUserRole.director:
        raise HTTPException(status_code=403, detail="仅校长管理员可以维护组织机构")


async def _tenant_unit(session: AsyncSession, tenant_id: int, unit_id: int) -> OrganizationUnit:
    unit = await session.get(OrganizationUnit, unit_id)
    if unit is None or unit.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="组织节点不存在")
    return unit


async def _current_organization_unit_ids(session: AsyncSession, tenant_id: int) -> set[int]:
    rows = list((await session.execute(
        select(OrganizationUnit).where(OrganizationUnit.tenant_id == tenant_id)
    )).scalars().all())
    return {
        int(item["id"])
        for item in current_organization_units([row.model_dump() for row in rows])
    }


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
    all_units = list((await session.execute(
        select(OrganizationUnit).where(OrganizationUnit.tenant_id == tenant_id)
        .order_by(OrganizationUnit.sort_order, OrganizationUnit.id)
    )).scalars().all())
    visible_units = current_organization_units([item.model_dump() for item in all_units])
    visible_unit_ids = {int(item["id"]) for item in visible_units}
    counts = dict((await session.execute(
        select(StaffAppointment.organization_unit_id, func.count(StaffAppointment.id))
        .where(
            StaffAppointment.tenant_id == tenant_id,
            StaffAppointment.status == "active",
            StaffAppointment.organization_unit_id.in_(visible_unit_ids),
        )
        .group_by(StaffAppointment.organization_unit_id)
    )).all())
    tree = build_organization_tree(visible_units, counts)
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
    try:
        validate_grade_group_binding(body.unit_type, body.grade_id)
        validate_subject_group_binding(body.unit_type, body.subject_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.grade_id is not None:
        grade = await session.get(Grade, body.grade_id)
        if grade is None or grade.tenant_id != tenant_id:
            raise HTTPException(status_code=422, detail="对应年级不存在")
    if body.subject_id is not None:
        await _tenant_subject(session, tenant_id, body.subject_id)
    if body.parent_id is not None:
        parent = await _tenant_unit(session, tenant_id, body.parent_id)
        if parent.id not in await _current_organization_unit_ids(session, tenant_id):
            raise HTTPException(status_code=409, detail="不能在已归档的组织下新增节点")
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
    effective_grade_id = values.get("grade_id", unit.grade_id)
    effective_subject_id = values.get("subject_id", unit.subject_id)
    try:
        validate_grade_group_binding(unit.unit_type, effective_grade_id)
        validate_subject_group_binding(unit.unit_type, effective_subject_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "grade_id" in values and values["grade_id"] is not None:
        grade = await session.get(Grade, values["grade_id"])
        if grade is None or grade.tenant_id != tenant_id:
            raise HTTPException(status_code=422, detail="对应年级不存在")
    if "subject_id" in values and values["subject_id"] is not None:
        await _tenant_subject(session, tenant_id, values["subject_id"])
    if values.get("parent_id") == unit_id:
        raise HTTPException(status_code=422, detail="组织节点不能成为自己的上级")
    if values.get("parent_id") is not None:
        parent = await _tenant_unit(session, tenant_id, values["parent_id"])
        if parent.id not in await _current_organization_unit_ids(session, tenant_id):
            raise HTTPException(status_code=409, detail="不能移动到已归档的组织下")
    if values.get("status") == "active" and unit.parent_id is not None:
        if unit.parent_id not in await _current_organization_unit_ids(session, tenant_id):
            raise HTTPException(status_code=409, detail="不能在已归档的上级组织下恢复节点")
    if values.get("name"):
        await _ensure_single_grade_center_name(session, tenant_id, values["name"], exclude_unit_id=unit_id)
    archive_requested = values.pop("status", None) == "archived"
    for key, value in values.items():
        setattr(unit, key, value)
    if archive_requested:
        tenant_units = list((await session.execute(
            select(OrganizationUnit.id, OrganizationUnit.parent_id).where(
                OrganizationUnit.tenant_id == tenant_id,
            )
        )).all())
        unit_ids = organization_subtree_ids(
            unit_id,
            [{"id": child_id, "parent_id": parent_id} for child_id, parent_id in tenant_units],
        )
        unit.status = "archived"
        await session.execute(
            update(OrganizationUnit)
            .where(OrganizationUnit.tenant_id == tenant_id, OrganizationUnit.id.in_(unit_ids))
            .values(status="archived")
        )
        await session.execute(
            update(StaffAppointment)
            .where(
                StaffAppointment.tenant_id == tenant_id,
                StaffAppointment.organization_unit_id.in_(unit_ids),
                StaffAppointment.status == "active",
            )
            .values(status="archived")
        )
    elif body.status is not None and "status" in body.model_fields_set:
        unit.status = body.status
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
    """删除组织节点：无子节点且无老师任职即可删除。"""
    _require_principal(user)
    unit = await _tenant_unit(session, tenant_id, unit_id)
    child_count = (await session.execute(select(func.count(OrganizationUnit.id)).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.parent_id == unit_id,
    ))).scalar_one()
    appointment_count = (await session.execute(select(func.count(StaffAppointment.id)).where(
        StaffAppointment.tenant_id == tenant_id,
        StaffAppointment.organization_unit_id == unit_id,
    ))).scalar_one()
    active_appointment_count = (await session.execute(select(func.count(StaffAppointment.id)).where(
        StaffAppointment.tenant_id == tenant_id,
        StaffAppointment.organization_unit_id == unit_id,
        StaffAppointment.status == "active",
    ))).scalar_one()
    if child_count or appointment_count:
        raise HTTPException(status_code=409, detail={
            "message": "组织节点存在子节点或任职历史，不能删除",
            "children": child_count,
            "active_appointments": active_appointment_count,
            "historical_appointments": appointment_count - active_appointment_count,
        })
    await session.delete(unit)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"id": unit_id}}


@router.get("/appointments")
async def list_appointments(
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    """List current (active) staff appointments only."""
    _require_principal(user)
    visible_unit_ids = await _current_organization_unit_ids(session, tenant_id)
    statement = select(StaffAppointment, User.name, OrganizationUnit.name).where(
        StaffAppointment.tenant_id == tenant_id,
        StaffAppointment.status == "active",
        StaffAppointment.organization_unit_id.in_(visible_unit_ids),
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
    active_unit_ids = await _current_organization_unit_ids(session, tenant_id)
    if target_unit.id not in active_unit_ids:
        raise HTTPException(status_code=409, detail="不能在已归档的组织或其下级组织中新增任职关系")
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
