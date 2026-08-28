"""角色与权限管理 API：角色 CRUD + 权限点目录 + 角色→权限分配"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.enums import BaseUserRole
from app.models.org import User
from app.services.rbac import (
    create_role,
    delete_role,
    ensure_builtin_roles,
    ensure_permissions,
    list_permissions,
    list_role_members,
    list_role_permissions,
    list_roles,
    set_role_members,
    set_role_permissions,
    update_role,
)

router = APIRouter(prefix="/rbac", tags=["角色与权限"])


class RoleIn(BaseModel):
    code: str = Field(
        min_length=2,
        max_length=50,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="角色编码，小写字母开头，仅允许小写字母、数字或下划线",
    )
    name: str = Field(min_length=1, max_length=50, description="角色名称")
    description: str | None = Field(default=None, max_length=255)


class RoleUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=255)


class RolePermissionsIn(BaseModel):
    permissions: list[str] = Field(default_factory=list, description="权限点编码集合")


class RoleMembersIn(BaseModel):
    user_ids: list[int] = Field(default_factory=list, description="角色成员账号 ID")

    @field_validator("user_ids")
    @classmethod
    def normalize_user_ids(cls, values: list[int]) -> list[int]:
        return sorted(set(values))


def _require_school_admin(user: User) -> None:
    if user.role != BaseUserRole.director:
        raise HTTPException(status_code=403, detail="仅校长管理员可以配置角色与权限")


@router.get("/permissions", summary="权限点目录（按模块分组）")
async def permissions(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    await ensure_permissions(session)
    return {"code": 0, "message": "ok", "data": await list_permissions(session)}


@router.get("/roles", summary="角色列表")
async def roles(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    await ensure_builtin_roles(session, tenant_id)
    return {"code": 0, "message": "ok", "data": await list_roles(session, tenant_id)}


@router.post("/roles", status_code=status.HTTP_201_CREATED, summary="新建角色")
async def create_role_api(
    body: RoleIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        role = await create_role(
            session,
            tenant_id,
            body.code.strip(),
            body.name.strip(),
            body.description,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": {"id": role.id, "code": role.code, "name": role.name}}


@router.patch("/roles/{role_id}", summary="编辑角色（名称/说明）")
async def update_role_api(
    role_id: int,
    body: RoleUpdateIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        role = await update_role(session, role_id, tenant_id, body.name.strip(), body.description)
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": {"id": role.id, "name": role.name, "description": role.description}}


@router.delete("/roles/{role_id}", summary="删除角色（内置角色与已分配角色除外）")
async def delete_role_api(
    role_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        await delete_role(session, role_id, tenant_id)
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": None}


@router.get("/roles/{role_id}/permissions", summary="角色已拥有的权限点")
async def role_permissions(
    role_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    await ensure_permissions(session)
    try:
        codes = sorted(await list_role_permissions(session, role_id, tenant_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": codes}


@router.put("/roles/{role_id}/permissions", summary="整量设置角色的权限点")
async def set_role_permissions_api(
    role_id: int,
    body: RolePermissionsIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        codes = await set_role_permissions(session, role_id, tenant_id, body.permissions)
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": codes}


@router.get("/roles/{role_id}/members", summary="角色成员列表")
async def role_members(
    role_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        data = await list_role_members(session, role_id, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": data}


@router.put("/roles/{role_id}/members", summary="整量设置角色成员")
async def set_role_members_api(
    role_id: int,
    body: RoleMembersIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        user_ids = await set_role_members(session, role_id, tenant_id, body.user_ids)
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": user_ids}
