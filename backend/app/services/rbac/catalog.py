"""权限点目录：空库播种、列表与 CRUD。"""
from sqlalchemy import delete, func, select, text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.rbac import MenuPermission, Permission, RolePermission
from app.services.rbac.seed import PERMISSION_SEED


_schema_checked = False
RETIRED_PERMISSION_PREFIXES = ("scan:", "paper:", "grading:")


def _is_retired_permission(code: str) -> bool:
    return code.startswith(RETIRED_PERMISSION_PREFIXES)


async def ensure_permission_schema(session: AsyncSession) -> None:
    """开发库兼容：补齐 permission.sort（生产走 Alembic）。

    ALTER 即使列已存在也要拿 permission 表的 AccessExclusiveLock，并发的 menus
    请求同时执行会互相死锁（PostgreSQL DeadlockDetectedError）。
    进程内只放行第一个请求，其余直接跳过。
    """
    global _schema_checked
    if _schema_checked:
        return
    _schema_checked = True
    try:
        await session.execute(
            text("ALTER TABLE permission ADD COLUMN IF NOT EXISTS sort INTEGER NOT NULL DEFAULT 0")
        )
        await session.flush()
    except Exception:
        _schema_checked = False
        raise


async def ensure_permissions(session: AsyncSession) -> None:
    """仅空库播种；已有数据不再用代码覆盖。"""
    await ensure_permission_schema(session)
    count = (
        await session.execute(select(func.count()).select_from(Permission))
    ).scalar_one()
    if count:
        return
    for index, (module, name, code) in enumerate(PERMISSION_SEED):
        session.add(Permission(code=code, name=name, module=module, sort=index))
    await session.flush()


async def list_permissions(session: AsyncSession) -> list[dict]:
    """从数据库读取权限点，按模块与 sort 排序。"""
    await ensure_permissions(session)
    rows = list(
        (
            await session.execute(
                select(Permission).order_by(Permission.module, Permission.sort, Permission.id)
            )
        ).scalars().all()
    )
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for item in rows:
        # Older databases may still have catalog rows until the cleanup migration
        # runs. Do not expose removed modules in the role editor in the meantime.
        if _is_retired_permission(item.code):
            continue
        if item.module not in grouped:
            grouped[item.module] = []
            order.append(item.module)
        grouped[item.module].append({"code": item.code, "name": item.name})
    return [{"module": module, "permissions": grouped[module]} for module in order]


async def create_permission(
    session: AsyncSession,
    code: str,
    name: str,
    module: str,
    sort: int | None = None,
) -> Permission:
    code = code.strip()
    name = name.strip()
    module = module.strip()
    if not code or not name or not module:
        raise ValueError("编码、名称、模块不能为空")
    if _is_retired_permission(code):
        raise ValueError("该功能已下线，不能重新添加权限")
    exists = (
        await session.execute(select(Permission.id).where(Permission.code == code))
    ).first()
    if exists:
        raise ValueError(f"权限点 {code} 已存在")
    if sort is None:
        max_sort = (
            await session.execute(
                select(func.max(Permission.sort)).where(Permission.module == module)
            )
        ).scalar_one()
        sort = int(max_sort or 0) + 10
    item = Permission(code=code, name=name, module=module, sort=sort)
    session.add(item)
    await session.flush()
    return item


async def update_permission(
    session: AsyncSession,
    code: str,
    *,
    name: str | None = None,
    module: str | None = None,
    sort: int | None = None,
) -> Permission:
    item = (
        await session.execute(select(Permission).where(Permission.code == code))
    ).scalar_one_or_none()
    if item is None:
        raise ValueError("权限点不存在")
    if _is_retired_permission(item.code):
        raise ValueError("该权限已下线，请先执行权限清理迁移")
    if name is not None:
        item.name = name.strip()
    if module is not None:
        item.module = module.strip()
    if sort is not None:
        item.sort = sort
    await session.flush()
    return item


async def delete_permission(session: AsyncSession, code: str) -> None:
    item = (
        await session.execute(select(Permission).where(Permission.code == code))
    ).scalar_one_or_none()
    if item is None:
        raise ValueError("权限点不存在")
    in_use = (
        await session.execute(
            select(RolePermission.id).where(RolePermission.permission_id == item.id).limit(1)
        )
    ).first()
    if in_use:
        raise ValueError("该权限点已分配给角色，请先解除后删除")
    await session.execute(
        delete(MenuPermission).where(MenuPermission.permission_id == item.id)
    )
    await session.delete(item)
    await session.flush()
