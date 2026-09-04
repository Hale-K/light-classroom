"""School personnel accounts and multi-role assignments."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.core.security import get_password_hash
from app.db.session import get_session
from app.models.enums import BaseUserRole, UserStatus
from app.models.org import User
from app.models.rbac import Role, UserRole
from app.services.org.staff_roles import ASSIGNABLE_STAFF_ROLES, normalize_staff_roles, replace_staff_roles

router = APIRouter(prefix="/staff", tags=["人员与权限"])

TEACHER_LEVELS = {"特级教师", "正高级教师", "高级教师", "一级教师", "二级教师", "普通教师"}


class StaffCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=6, max_length=20)
    password: str = Field(min_length=6, max_length=64)
    roles: list[str] = Field(default_factory=list)
    teacher_level: str | None = Field(default=None, max_length=30)


class StaffRolesIn(BaseModel):
    roles: list[str] = Field(default_factory=list)


class StaffUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=6, max_length=20)
    roles: list[str] = Field(default_factory=list)
    teacher_level: str | None = Field(default=None, max_length=30)


class StaffStatusIn(BaseModel):
    status: UserStatus


def _require_school_admin(user: User) -> None:
    if user.role != BaseUserRole.director:
        raise HTTPException(status_code=403, detail="仅校长管理员可以配置人员与权限")


def _role_catalog():
    return [item.__dict__ for item in ASSIGNABLE_STAFF_ROLES]


def _staff_data(user: User, roles: list[str]):
    is_school_admin = user.role == BaseUserRole.director
    return {
        "id": user.id,
        "name": user.name,
        "phone": user.phone,
        "status": user.status.value,
        "roles": ["school_admin"] if is_school_admin else roles,
        "is_school_admin": is_school_admin,
        "teacher_level": user.teacher_level,
    }


async def _load_role_map(session: AsyncSession, user_ids: list[int]) -> dict[int, list[str]]:
    if not user_ids:
        return {}
    result = await session.execute(
        select(UserRole.user_id, Role.code)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_(user_ids))
    )
    role_map: dict[int, list[str]] = {user_id: [] for user_id in user_ids}
    for user_id, code in result.all():
        if code in {item.code for item in ASSIGNABLE_STAFF_ROLES}:
            role_map[user_id].append(code)
    return {user_id: normalize_staff_roles(codes) for user_id, codes in role_map.items()}


@router.get("", summary="人员账号与角色")
async def list_staff(
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_school_admin(user)
    users = list((await session.execute(
        select(User).where(User.tenant_id == tenant_id).order_by(User.role, User.name)
    )).scalars().all())
    role_map = await _load_role_map(session, [item.id for item in users])
    return {"code": 0, "message": "ok", "data": {
        "accounts": [_staff_data(item, role_map.get(item.id, [])) for item in users],
        "roles": _role_catalog(),
    }}


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建教职工账号")
async def create_staff(
    body: StaffCreateIn,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_school_admin(user)
    try:
        role_codes = normalize_staff_roles(body.roles)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    exists = (await session.execute(select(User).where(User.phone == body.phone))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="该手机号已存在")
    if body.teacher_level is not None and body.teacher_level not in TEACHER_LEVELS:
        raise HTTPException(status_code=422, detail="教师职级不合法")
    account = User(
        name=body.name,
        phone=body.phone,
        password_hash=get_password_hash(body.password),
        role=BaseUserRole.teacher,
        teacher_level=body.teacher_level,
        tenant_id=tenant_id,
    )
    session.add(account)
    await session.flush()
    await replace_staff_roles(session, account.id, role_codes, tenant_id)
    await session.commit()
    await session.refresh(account)
    return {"code": 0, "message": "ok", "data": _staff_data(account, role_codes)}


@router.patch("/{staff_id}", summary="编辑人员信息")
async def update_staff(
    staff_id: int,
    body: StaffUpdateIn,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_school_admin(user)
    account = await session.get(User, staff_id)
    if account is None or account.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="教职工账号不存在")
    if account.role == BaseUserRole.director:
        raise HTTPException(status_code=422, detail="校长管理员信息不可修改")
    if body.teacher_level is not None and body.teacher_level not in TEACHER_LEVELS:
        raise HTTPException(status_code=422, detail="教师职级不合法")
    duplicate = (await session.execute(select(User).where(User.tenant_id == tenant_id, User.phone == body.phone, User.id != staff_id))).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="该手机号已存在")
    try:
        role_codes = normalize_staff_roles(body.roles)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    account.name = body.name
    account.phone = body.phone
    account.teacher_level = body.teacher_level
    await replace_staff_roles(session, account.id, role_codes, tenant_id)
    await session.commit()
    await session.refresh(account)
    return {"code": 0, "message": "ok", "data": _staff_data(account, role_codes)}


@router.patch("/{staff_id}/roles", summary="分配教职工角色")
async def update_staff_roles(
    staff_id: int,
    body: StaffRolesIn,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_school_admin(user)
    account = await session.get(User, staff_id)
    if account is None or account.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="教职工账号不存在")
    if account.role == BaseUserRole.director:
        raise HTTPException(status_code=422, detail="校长管理员角色不可修改")
    try:
        role_codes = await replace_staff_roles(session, account.id, body.roles, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {"code": 0, "message": "ok", "data": _staff_data(account, role_codes)}


@router.patch("/{staff_id}/status", summary="启用或停用教职工账号")
async def update_staff_status(
    staff_id: int,
    body: StaffStatusIn,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    _require_school_admin(user)
    account = await session.get(User, staff_id)
    if account is None or account.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="教职工账号不存在")
    if account.role == BaseUserRole.director:
        raise HTTPException(status_code=422, detail="校长管理员账号不可停用")
    account.status = body.status
    await session.commit()
    await session.refresh(account)
    roles = await _load_role_map(session, [account.id])
    return {"code": 0, "message": "ok", "data": _staff_data(account, roles.get(account.id, []))}
