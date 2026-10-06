"""角色：内置角色播种、CRUD、权限分配、成员分配。"""
from sqlalchemy import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.org import Tenant, User
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.services.rbac.catalog import RETIRED_PERMISSION_PREFIXES, ensure_permissions
from app.services.rbac.seed import BUILTIN_ROLE_PERMISSION_SEED, BUILTIN_ROLE_SEED

# 内置角色（编码保留，不允许删除/改名）
BUILTIN_ROLE_CODES = {"school_admin", "academic_director", "head_teacher", "subject_teacher"}


def role_belongs_to_tenant(role: Role, tenant_id: int) -> bool:
    return role.tenant_id == tenant_id


async def _tenant_role(session: AsyncSession, role_id: int, tenant_id: int) -> Role:
    role = await session.get(Role, role_id)
    if role is None or not role_belongs_to_tenant(role, tenant_id):
        raise ValueError("角色不存在")
    return role


async def ensure_builtin_roles(session: AsyncSession, tenant_id: int | None = None) -> None:
    """Ensure every school owns an independent copy of the builtin roles."""
    await ensure_permissions(session)
    tenant_ids = [tenant_id] if tenant_id is not None else list(
        (await session.execute(select(Tenant.id))).scalars().all()
    )
    all_perm_codes = list((await session.execute(select(Permission.code))).scalars().all())
    code_to_pid = {
        code: permission_id
        for code, permission_id in (
            await session.execute(select(Permission.code, Permission.id))
        ).all()
    }

    for current_tenant_id in tenant_ids:
        for code, name, description in BUILTIN_ROLE_SEED:
            role = await role_by_code(session, code, current_tenant_id)
            if role is None:
                role = Role(
                    tenant_id=current_tenant_id,
                    code=code,
                    name=name,
                    description=description,
                )
                session.add(role)
                await session.flush()
            has_any = (await session.execute(
                select(RolePermission.id).where(RolePermission.role_id == role.id).limit(1)
            )).first()
            if has_any:
                continue
            if code == "school_admin":
                defaults = set(all_perm_codes)
            else:
                defaults = BUILTIN_ROLE_PERMISSION_SEED.get(code, set())
            for permission_code in defaults:
                permission_id = code_to_pid.get(permission_code)
                if permission_id is not None:
                    session.add(RolePermission(role_id=role.id, permission_id=permission_id))
    await session.flush()


async def list_roles(session: AsyncSession, tenant_id: int) -> list[dict]:
    """List one school's roles with permission and member counts."""
    roles = list((await session.execute(
        select(Role).where(Role.tenant_id == tenant_id).order_by(Role.id)
    )).scalars().all())
    if not roles:
        return []
    perm_counts: dict[int, int] = {}
    result = await session.execute(
        select(RolePermission.role_id).where(RolePermission.role_id.in_([r.id for r in roles]))
    )
    for (role_id,) in result.all():
        perm_counts[role_id] = perm_counts.get(role_id, 0) + 1
    member_counts: dict[int, int] = {}
    result = await session.execute(
        select(UserRole.role_id).where(UserRole.role_id.in_([r.id for r in roles]))
    )
    for (role_id,) in result.all():
        member_counts[role_id] = member_counts.get(role_id, 0) + 1
    school_admin_count = len(list((await session.execute(select(User.id).where(
        User.tenant_id == tenant_id,
        User.role == "director",
    ))).scalars().all()))
    return [
        {
            "id": role.id,
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "builtin": role.code in BUILTIN_ROLE_CODES,
            "permission_count": perm_counts.get(role.id, 0),
            "member_count": school_admin_count if role.code == "school_admin" else member_counts.get(role.id, 0),
        }
        for role in roles
    ]


async def role_by_code(session: AsyncSession, code: str, tenant_id: int) -> Role | None:
    return (await session.execute(select(Role).where(
        Role.code == code,
        Role.tenant_id == tenant_id,
    ))).scalar_one_or_none()


async def create_role(
    session: AsyncSession,
    tenant_id: int,
    code: str,
    name: str,
    description: str | None,
) -> Role:
    if not code or not name:
        raise ValueError("角色编码与名称不能为空")
    if await role_by_code(session, code, tenant_id):
        raise ValueError(f"角色编码 {code} 已存在")
    role = Role(tenant_id=tenant_id, code=code, name=name, description=description or "")
    session.add(role)
    await session.flush()
    return role


async def update_role(
    session: AsyncSession,
    role_id: int,
    tenant_id: int,
    name: str,
    description: str | None,
) -> Role:
    role = await _tenant_role(session, role_id, tenant_id)
    if role.code in BUILTIN_ROLE_CODES:
        raise ValueError("内置角色不允许修改名称")
    if not name:
        raise ValueError("角色名称不能为空")
    role.name = name
    role.description = description or ""
    await session.flush()
    return role


async def delete_role(session: AsyncSession, role_id: int, tenant_id: int) -> None:
    role = await _tenant_role(session, role_id, tenant_id)
    if role.code in BUILTIN_ROLE_CODES:
        raise ValueError("内置角色不允许删除")
    in_use = (await session.execute(select(UserRole.id).where(UserRole.role_id == role_id).limit(1))).first()
    if in_use:
        raise ValueError("该角色已分配给人员，请先解除后删除")
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    await session.delete(role)
    await session.flush()


async def list_role_permissions(session: AsyncSession, role_id: int, tenant_id: int) -> set[str]:
    await _tenant_role(session, role_id, tenant_id)
    result = await session.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .where(*[~Permission.code.startswith(prefix) for prefix in RETIRED_PERMISSION_PREFIXES])
    )
    return set(result.scalars().all())


async def set_role_permissions(
    session: AsyncSession,
    role_id: int,
    tenant_id: int,
    codes: list[str],
) -> list[str]:
    """整量替换角色的权限点集合。"""
    await _tenant_role(session, role_id, tenant_id)
    all_perms = list((await session.execute(select(Permission.code, Permission.id))).all())
    code_to_id = {
        code: pid for code, pid in all_perms
        if not code.startswith(RETIRED_PERMISSION_PREFIXES)
    }
    unknown = [c for c in codes if c not in code_to_id]
    if unknown:
        raise ValueError(f"未知权限点：{', '.join(unknown)}")
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    for code in set(codes):
        session.add(RolePermission(role_id=role_id, permission_id=code_to_id[code]))
    await session.flush()
    return sorted(set(codes))


async def list_role_members(session: AsyncSession, role_id: int, tenant_id: int) -> dict:
    role = await _tenant_role(session, role_id, tenant_id)
    users = list((await session.execute(
        select(User).where(User.tenant_id == tenant_id).order_by(User.role, User.name, User.id)
    )).scalars().all())
    assigned_ids = set((await session.execute(
        select(UserRole.user_id).where(UserRole.role_id == role_id)
    )).scalars().all())
    return {
        "role": {"id": role.id, "code": role.code, "name": role.name},
        "editable": role.code != "school_admin",
        "members": [
            {
                "id": item.id,
                "name": item.name,
                "phone": item.phone,
                "status": item.status.value,
                "assignable": role.code != "school_admin" and item.role.value != "director",
                "assigned": (
                    item.role.value == "director"
                    if role.code == "school_admin"
                    else item.id in assigned_ids
                ),
            }
            for item in users
        ],
    }


async def set_role_members(
    session: AsyncSession,
    role_id: int,
    tenant_id: int,
    user_ids: list[int],
) -> list[int]:
    role = await _tenant_role(session, role_id, tenant_id)
    if role.code == "school_admin":
        raise ValueError("校长管理员由校长账号自动拥有，不支持手工分配")
    normalized_ids = sorted(set(user_ids))
    if normalized_ids:
        valid_users = list((await session.execute(select(User).where(
            User.tenant_id == tenant_id,
            User.id.in_(normalized_ids),
        ))).scalars().all())
        valid_ids = {item.id for item in valid_users if item.role.value != "director"}
        unknown_ids = sorted(set(normalized_ids) - valid_ids)
        if unknown_ids:
            raise ValueError(f"人员账号不存在或不可分配：{', '.join(map(str, unknown_ids))}")
    await session.execute(delete(UserRole).where(UserRole.role_id == role_id))
    for user_id in normalized_ids:
        session.add(UserRole(user_id=user_id, role_id=role_id))
    await session.flush()
    return normalized_ids
