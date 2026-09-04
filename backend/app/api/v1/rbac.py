"""角色与权限管理 API：角色 / 权限点目录 / 菜单结构 / 映射"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.enums import BaseUserRole
from app.models.org import Tenant, User
from app.services.rbac import (
    create_menu,
    create_permission,
    create_role,
    delete_menu,
    delete_permission,
    delete_role,
    ensure_builtin_roles,
    ensure_menu_permissions,
    ensure_permissions,
    list_menu_permission_bindings,
    list_permissions,
    list_role_members,
    list_role_permissions,
    list_roles,
    load_menu_permission_map,
    load_menus,
    preview_menu_by_permissions,
    set_menu_permissions,
    set_role_members,
    set_role_permissions,
    update_menu,
    update_permission,
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


class MenuPermissionsIn(BaseModel):
    permissions: list[str] = Field(
        default_factory=list,
        description="该菜单可见所需权限点（满足任一即可）；空列表清除映射",
    )


class PermissionIn(BaseModel):
    code: str = Field(min_length=2, max_length=100, pattern=r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=50)
    module: str = Field(min_length=1, max_length=50)
    sort: int | None = None


class PermissionUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=50)
    module: str | None = Field(default=None, max_length=50)
    sort: int | None = None


class MenuIn(BaseModel):
    key: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=50)
    path: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default="grid", max_length=50)
    sort: int = 0
    enabled: bool = True
    roles: list[str] = Field(default_factory=list)
    required_capability: str | None = None
    group_key: str = "other"
    group_title: str = "其他"
    group_icon: str = "grid"
    group_sort: int = 100


class MenuUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=50)
    path: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default=None, max_length=50)
    sort: int | None = None
    enabled: bool | None = None
    roles: list[str] | None = None
    required_capability: str | None = None
    group_key: str | None = None
    group_title: str | None = None
    group_icon: str | None = None
    group_sort: int | None = None


def _require_school_admin(user: User) -> None:
    if user.role != BaseUserRole.director:
        raise HTTPException(status_code=403, detail="仅校长管理员可以配置角色与权限")


@router.get("/permissions", summary="权限点目录（按模块分组，读库）")
async def permissions(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    await ensure_permissions(session)
    return {"code": 0, "message": "ok", "data": await list_permissions(session)}


@router.post("/permission-items", status_code=status.HTTP_201_CREATED, summary="新建权限点")
async def create_permission_api(
    body: PermissionIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        item = await create_permission(
            session, body.code, body.name, body.module, body.sort
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "code": 0,
        "message": "ok",
        "data": {"code": item.code, "name": item.name, "module": item.module, "sort": item.sort},
    }


@router.patch("/permission-items/{code}", summary="编辑权限点")
async def update_permission_api(
    code: str,
    body: PermissionUpdateIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        item = await update_permission(
            session,
            code,
            name=body.name,
            module=body.module,
            sort=body.sort,
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "code": 0,
        "message": "ok",
        "data": {"code": item.code, "name": item.name, "module": item.module, "sort": item.sort},
    }


@router.delete("/permission-items/{code}", summary="删除权限点")
async def delete_permission_api(
    code: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        await delete_permission(session, code)
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": None}


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


@router.get("/roles/{role_id}/menu-preview", summary="按权限码预览角色侧栏菜单")
async def role_menu_preview(
    role_id: int,
    codes: str | None = Query(
        default=None,
        description="逗号分隔的权限点编码；省略则使用该角色已保存权限",
    ),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    await ensure_permissions(session)
    try:
        if codes is None:
            permission_codes = await list_role_permissions(session, role_id, tenant_id)
        else:
            permission_codes = {item.strip() for item in codes.split(",") if item.strip()}
            await list_role_permissions(session, role_id, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tenant = await session.get(Tenant, tenant_id)
    gaokao_mode = tenant.gaokao_mode if tenant else "3+1+2"
    await ensure_menu_permissions(session)
    menu_permissions = await load_menu_permission_map(session)
    menu_items = await load_menus(session, include_disabled=False)
    return {
        "code": 0,
        "message": "ok",
        "data": preview_menu_by_permissions(
            permission_codes,
            gaokao_mode,
            menu_permissions=menu_permissions,
            menu_items=menu_items,
        ),
    }


@router.get("/menus", summary="菜单结构列表（管理台，含未开放）")
async def menus_list(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    await ensure_menu_permissions(session)
    data = await load_menus(session, include_disabled=True)
    await session.commit()
    return {"code": 0, "message": "ok", "data": data}


@router.post("/menus", status_code=status.HTTP_201_CREATED, summary="新建菜单项")
async def menus_create(
    body: MenuIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        item = await create_menu(session, body.model_dump())
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": {"key": item.key, "name": item.name}}


@router.patch("/menus/{menu_key}", summary="编辑菜单项")
async def menus_update(
    menu_key: str,
    body: MenuUpdateIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        item = await update_menu(
            session,
            menu_key,
            body.model_dump(exclude_unset=True),
        )
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": {"key": item.key, "name": item.name}}


@router.delete("/menus/{menu_key}", summary="删除菜单项")
async def menus_delete(
    menu_key: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        await delete_menu(session, menu_key)
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": None}


@router.get("/menu-permissions", summary="菜单可见权限映射（管理台）")
async def menu_permissions_list(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    data = await list_menu_permission_bindings(session)
    await session.commit()
    return {"code": 0, "message": "ok", "data": data}


@router.put("/menu-permissions/{menu_key}", summary="整量设置某菜单的可见权限点")
async def menu_permissions_set(
    menu_key: str,
    body: MenuPermissionsIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    _require_school_admin(user)
    try:
        codes = await set_menu_permissions(session, menu_key, body.permissions)
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"code": 0, "message": "ok", "data": {"menu_key": menu_key, "permissions": codes}}


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
