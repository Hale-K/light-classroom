"""菜单服务：结构与可见权限均以数据库为准

- menu 表：侧栏菜单结构（标题、路径、分组、角色白名单等）
- menu_permission 表：菜单可见所需权限点（满足任一即可）
- 新环境空库时由 seed 模块播种一次；之后只读库 / 管理台维护
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.rbac import Menu, MenuPermission, Permission
from app.services.academic.gaokao import get_subject_choice_strategy
from app.services.rbac.seed import MENU_PERMISSION_SEED, MENU_SEED


async def ensure_menu_schema(session: AsyncSession) -> None:
    """开发库兼容：补齐 menu 新列（生产走 Alembic）。"""
    statements = [
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS key VARCHAR(50)",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS roles_csv VARCHAR(255) NOT NULL DEFAULT ''",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS required_capability VARCHAR(50)",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS group_key VARCHAR(50) NOT NULL DEFAULT 'other'",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS group_title VARCHAR(50) NOT NULL DEFAULT '其他'",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS group_icon VARCHAR(50) NOT NULL DEFAULT 'grid'",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS group_sort INTEGER NOT NULL DEFAULT 100",
        "UPDATE menu SET key = 'legacy_' || id::text WHERE key IS NULL OR key = ''",
    ]
    for sql in statements:
        await session.execute(text(sql))
    await session.flush()


def _roles_list(roles_csv: str) -> list[str]:
    return [item.strip() for item in (roles_csv or "").split(",") if item.strip()]


def _roles_csv(roles: list[str] | None) -> str:
    return ",".join(item.strip() for item in (roles or []) if item and item.strip())


def menu_row_to_dict(item: Menu) -> dict[str, Any]:
    return {
        "id": item.id,
        "key": item.key,
        "title": item.name,
        "name": item.name,
        "path": item.path,
        "icon": item.icon or "grid",
        "sort": item.sort,
        "enabled": bool(item.enabled),
        "roles": _roles_list(item.roles_csv),
        "required_capability": item.required_capability,
        "group_key": item.group_key,
        "group_title": item.group_title,
        "group_icon": item.group_icon,
        "group_sort": item.group_sort,
    }


async def ensure_menus(session: AsyncSession) -> None:
    """仅空表播种菜单结构。"""
    await ensure_menu_schema(session)
    count = (await session.execute(select(func.count()).select_from(Menu))).scalar_one()
    if count:
        return
    for spec in MENU_SEED:
        session.add(
            Menu(
                key=spec["key"],
                name=spec["name"],
                path=spec["path"],
                icon=spec["icon"],
                sort=int(spec["sort"]),
                enabled=bool(spec["enabled"]),
                roles_csv=_roles_csv(list(spec.get("roles") or [])),
                required_capability=spec.get("required_capability"),
                group_key=spec["group_key"],
                group_title=spec["group_title"],
                group_icon=spec["group_icon"],
                group_sort=int(spec["group_sort"]),
            )
        )
    await session.flush()


async def sync_menu_groups(session: AsyncSession) -> None:
    """按种子刷新已有菜单的分组（侧栏 3 组布局升级）。"""
    await ensure_menu_schema(session)
    spec_by_key = {spec["key"]: spec for spec in MENU_SEED}
    rows = list((await session.execute(select(Menu))).scalars().all())
    for row in rows:
        spec = spec_by_key.get(row.key or "")
        if spec is None:
            continue
        row.group_key = spec["group_key"]
        row.group_title = spec["group_title"]
        row.group_icon = spec["group_icon"]
        row.group_sort = int(spec["group_sort"])
    await session.flush()


async def ensure_file_center_menu(session: AsyncSession) -> None:
    """已有库补齐「文件中心」菜单与权限映射（不覆盖其它项）。"""
    from app.services.rbac.catalog import ensure_permissions

    await ensure_permissions(session)
    perm = (
        await session.execute(select(Permission).where(Permission.code == "file_center:view"))
    ).scalar_one_or_none()
    if perm is None:
        perm = Permission(code="file_center:view", name="查看文件中心", module="文件中心", sort=80)
        session.add(perm)
        await session.flush()
    existing = (
        await session.execute(select(Menu).where(Menu.key == "file-center"))
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Menu(
                key="file-center",
                name="文件中心",
                path="/file-center",
                icon="upload",
                sort=15,
                enabled=True,
                roles_csv="director,academic_director",
                required_capability=None,
                group_key="teaching-exams",
                group_title="教学考试",
                group_icon="book",
                group_sort=30,
            )
        )
        await session.flush()
    linked = (
        await session.execute(
            select(MenuPermission).where(
                MenuPermission.menu_key == "file-center",
                MenuPermission.permission_id == perm.id,
            )
        )
    ).scalar_one_or_none()
    if linked is None:
        session.add(MenuPermission(menu_key="file-center", permission_id=perm.id))
    await session.flush()


async def ensure_ai_provider_menu(session: AsyncSession) -> None:
    """已有库补齐「服务商管理」菜单与权限。"""
    from app.services.rbac.catalog import ensure_permissions

    await ensure_permissions(session)
    codes = [
        ("ai_provider:view", "查看大模型服务商"),
        ("ai_provider:manage", "配置大模型服务商"),
    ]
    perm_ids: list[int] = []
    for code, name in codes:
        perm = (
            await session.execute(select(Permission).where(Permission.code == code))
        ).scalar_one_or_none()
        if perm is None:
            perm = Permission(code=code, name=name, module="服务商管理", sort=90)
            session.add(perm)
            await session.flush()
        perm_ids.append(perm.id)
    existing = (
        await session.execute(select(Menu).where(Menu.key == "ai-providers"))
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Menu(
                key="ai-providers",
                name="服务商管理",
                path="/ai-providers",
                icon="cloud",
                sort=15,
                enabled=True,
                roles_csv="director",
                required_capability=None,
                group_key="school-affairs",
                group_title="学籍教务",
                group_icon="school",
                group_sort=20,
            )
        )
        await session.flush()
    for pid in perm_ids:
        linked = (
            await session.execute(
                select(MenuPermission).where(
                    MenuPermission.menu_key == "ai-providers",
                    MenuPermission.permission_id == pid,
                )
            )
        ).scalar_one_or_none()
        if linked is None:
            session.add(MenuPermission(menu_key="ai-providers", permission_id=pid))
    await session.flush()


async def ensure_menu_permissions(session: AsyncSession) -> None:
    """权限点 + 菜单结构 + 默认菜单权限映射（按 menu_key 仅补缺）。"""
    from app.services.rbac.catalog import ensure_permissions

    await ensure_permissions(session)
    await ensure_menus(session)
    await sync_menu_groups(session)
    await ensure_file_center_menu(session)
    await ensure_ai_provider_menu(session)
    existing_keys = set(
        (await session.execute(select(MenuPermission.menu_key).distinct())).scalars().all()
    )
    code_to_id = {
        code: pid
        for code, pid in (await session.execute(select(Permission.code, Permission.id))).all()
    }
    for menu_key, codes in MENU_PERMISSION_SEED.items():
        if menu_key in existing_keys:
            continue
        for code in codes:
            permission_id = code_to_id.get(code)
            if permission_id is None:
                continue
            session.add(MenuPermission(menu_key=menu_key, permission_id=permission_id))
    await session.flush()


async def load_menus(session: AsyncSession, *, include_disabled: bool = False) -> list[dict[str, Any]]:
    await ensure_menus(session)
    query = select(Menu).order_by(Menu.group_sort, Menu.sort, Menu.id)
    if not include_disabled:
        query = query.where(Menu.enabled.is_(True))
    rows = list((await session.execute(query)).scalars().all())
    return [menu_row_to_dict(item) for item in rows]


async def load_menu_permission_map(session: AsyncSession) -> dict[str, set[str]]:
    rows = (
        await session.execute(
            select(MenuPermission.menu_key, Permission.code)
            .join(Permission, Permission.id == MenuPermission.permission_id)
        )
    ).all()
    result: dict[str, set[str]] = {}
    for menu_key, code in rows:
        result.setdefault(menu_key, set()).add(code)
    return result


def build_menu(
    role: str,
    gaokao_mode: str = "3+1+2",
    permission_codes: set[str] | None = None,
    menu_permissions: dict[str, set[str]] | None = None,
    menu_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """根据菜单行 + 权限映射构建侧栏树。

    menu_items / menu_permissions 由调用方从数据库加载后传入。
    单元测试可直接注入内存数据。
    """
    capabilities = get_subject_choice_strategy(gaokao_mode).capabilities
    mapping = menu_permissions or {}
    items = menu_items or []
    teacher_roles = {"teacher", "head_teacher", "subject_teacher"}
    if role in teacher_roles:
        if any(item.get("group_key") == "teacher-workbench" for item in items):
            items = [item for item in items if item.get("group_key") == "teacher-workbench"]

    def is_visible(item: dict[str, Any]) -> bool:
        if not item.get("enabled", True) or not item.get("path"):
            return False
        required_capability = item.get("required_capability")
        if required_capability and required_capability not in capabilities:
            return False
        roles = item.get("roles") or []
        if permission_codes is None or role == "director":
            role_visible = not roles or role in roles
            return role_visible
        key = str(item.get("key") or "")
        if key in mapping:
            required = mapping[key]
            return bool(required & permission_codes)
        if item.get("group_key") == "teacher-workbench":
            return False
        return not roles or role in roles

    visible_items = {
        str(item["key"]): {
            "key": item["key"],
            "title": item.get("title") or item.get("name"),
            "icon": item.get("icon") or "grid",
            "path": item.get("path"),
            "available": True,
            "children": [],
        }
        for item in items
        if is_visible(item)
    }

    groups: dict[str, dict[str, Any]] = {}
    group_order: list[str] = []
    for item in sorted(items, key=lambda row: (row.get("group_sort", 100), row.get("sort", 0))):
        key = str(item.get("key") or "")
        if key not in visible_items:
            continue
        group_key = str(item.get("group_key") or "other")
        if group_key not in groups:
            groups[group_key] = {
                "key": group_key,
                "title": item.get("group_title") or "其他",
                "icon": item.get("group_icon") or "grid",
                "path": None,
                "available": True,
                "children": [],
            }
            group_order.append(group_key)
        groups[group_key]["children"].append(visible_items[key])
    return [groups[key] for key in group_order if groups[key]["children"]]


def preview_menu_by_permissions(
    permission_codes: set[str],
    gaokao_mode: str = "3+1+2",
    menu_permissions: dict[str, set[str]] | None = None,
    menu_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    codes = set(permission_codes)
    mapping = menu_permissions or {}
    menus = build_menu(
        "__preview__",
        gaokao_mode,
        permission_codes=codes,
        menu_permissions=mapping,
        menu_items=menu_items,
    )
    matched: dict[str, list[str]] = {}
    for group in menus:
        for child in group.get("children", []):
            key = str(child.get("key") or "")
            required = mapping.get(key, set())
            matched[key] = sorted(required & codes)
    return {
        "menus": menus,
        "matched_permissions": matched,
        "permission_codes": sorted(codes),
    }


async def list_menu_permission_bindings(session: AsyncSession) -> list[dict[str, Any]]:
    await ensure_menu_permissions(session)
    mapping = await load_menu_permission_map(session)
    menus = await load_menus(session, include_disabled=True)
    return [
        {
            **item,
            "permission_codes": sorted(mapping.get(item["key"], set())),
            "configured": item["key"] in mapping,
        }
        for item in menus
        if item.get("path")
    ]


async def set_menu_permissions(
    session: AsyncSession,
    menu_key: str,
    permission_codes: list[str],
) -> list[str]:
    await ensure_menus(session)
    exists = (
        await session.execute(select(Menu.id).where(Menu.key == menu_key))
    ).first()
    if not exists:
        raise ValueError(f"未知菜单：{menu_key}")
    from app.services.rbac.catalog import ensure_permissions

    await ensure_permissions(session)
    code_to_id = {
        code: pid
        for code, pid in (await session.execute(select(Permission.code, Permission.id))).all()
    }
    unknown = [code for code in permission_codes if code not in code_to_id]
    if unknown:
        raise ValueError(f"未知权限点：{', '.join(unknown)}")
    await session.execute(delete(MenuPermission).where(MenuPermission.menu_key == menu_key))
    for code in sorted(set(permission_codes)):
        session.add(MenuPermission(menu_key=menu_key, permission_id=code_to_id[code]))
    await session.flush()
    return sorted(set(permission_codes))


async def create_menu(session: AsyncSession, data: dict[str, Any]) -> Menu:
    await ensure_menus(session)
    key = str(data.get("key") or "").strip()
    name = str(data.get("name") or data.get("title") or "").strip()
    if not key or not name:
        raise ValueError("菜单编码与名称不能为空")
    exists = (await session.execute(select(Menu.id).where(Menu.key == key))).first()
    if exists:
        raise ValueError(f"菜单编码 {key} 已存在")
    item = Menu(
        key=key,
        name=name,
        path=(str(data["path"]).strip() if data.get("path") else None),
        icon=str(data.get("icon") or "grid"),
        sort=int(data.get("sort") or 0),
        enabled=bool(data.get("enabled", True)),
        roles_csv=_roles_csv(list(data.get("roles") or [])),
        required_capability=data.get("required_capability") or None,
        group_key=str(data.get("group_key") or "other"),
        group_title=str(data.get("group_title") or "其他"),
        group_icon=str(data.get("group_icon") or "grid"),
        group_sort=int(data.get("group_sort") or 100),
    )
    session.add(item)
    await session.flush()
    return item


async def update_menu(session: AsyncSession, key: str, data: dict[str, Any]) -> Menu:
    item = (
        await session.execute(select(Menu).where(Menu.key == key))
    ).scalar_one_or_none()
    if item is None:
        raise ValueError("菜单不存在")
    if "name" in data or "title" in data:
        item.name = str(data.get("name") or data.get("title") or item.name).strip()
    if "path" in data:
        item.path = str(data["path"]).strip() if data.get("path") else None
    if "icon" in data and data["icon"] is not None:
        item.icon = str(data["icon"])
    if "sort" in data and data["sort"] is not None:
        item.sort = int(data["sort"])
    if "enabled" in data and data["enabled"] is not None:
        item.enabled = bool(data["enabled"])
    if "roles" in data:
        item.roles_csv = _roles_csv(list(data.get("roles") or []))
    if "required_capability" in data:
        item.required_capability = data.get("required_capability") or None
    if "group_key" in data and data["group_key"]:
        item.group_key = str(data["group_key"])
    if "group_title" in data and data["group_title"]:
        item.group_title = str(data["group_title"])
    if "group_icon" in data and data["group_icon"]:
        item.group_icon = str(data["group_icon"])
    if "group_sort" in data and data["group_sort"] is not None:
        item.group_sort = int(data["group_sort"])
    await session.flush()
    return item


async def delete_menu(session: AsyncSession, key: str) -> None:
    item = (
        await session.execute(select(Menu).where(Menu.key == key))
    ).scalar_one_or_none()
    if item is None:
        raise ValueError("菜单不存在")
    await session.execute(delete(MenuPermission).where(MenuPermission.menu_key == key))
    await session.delete(item)
    await session.flush()


# 兼容旧测试：不再导出代码侧 MENU_CATALOG；提供种子转换辅助
def seed_menu_items() -> list[dict[str, Any]]:
    return [
        {
            "key": spec["key"],
            "title": spec["name"],
            "name": spec["name"],
            "path": spec["path"],
            "icon": spec["icon"],
            "sort": spec["sort"],
            "enabled": spec["enabled"],
            "roles": list(spec.get("roles") or []),
            "required_capability": spec.get("required_capability"),
            "group_key": spec["group_key"],
            "group_title": spec["group_title"],
            "group_icon": spec["group_icon"],
            "group_sort": spec["group_sort"],
        }
        for spec in MENU_SEED
    ]


# 兼容旧常量名（仅测试/脚本）
DEFAULT_MENU_PERMISSIONS = MENU_PERMISSION_SEED
MENU_PERMISSIONS = MENU_PERMISSION_SEED
