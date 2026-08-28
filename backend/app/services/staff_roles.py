"""School staff role definitions and RBAC helpers."""
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import BaseUserRole
from app.models.rbac import Role, UserRole


@dataclass(frozen=True)
class StaffRoleSpec:
    code: str
    name: str
    description: str


ASSIGNABLE_STAFF_ROLES = (
    StaffRoleSpec("head_teacher", "班主任", "负责行政班学生管理与班级排座"),
    StaffRoleSpec("subject_teacher", "任教老师", "承担学科教学、建卷与阅卷任务"),
    StaffRoleSpec("academic_director", "教导主任", "负责选科分班、排课与排考等教学管理"),
)
_ROLE_BY_CODE = {item.code: item for item in ASSIGNABLE_STAFF_ROLES}


def normalize_staff_roles(role_codes: list[str]) -> list[str]:
    unknown = sorted(set(role_codes) - _ROLE_BY_CODE.keys())
    if unknown:
        raise ValueError(f"不支持的教职工角色：{', '.join(unknown)}")
    selected = set(role_codes)
    return [item.code for item in ASSIGNABLE_STAFF_ROLES if item.code in selected]


def effective_menu_role(base_role: BaseUserRole, role_codes: list[str]) -> str:
    if base_role == BaseUserRole.director:
        return "director"
    if "academic_director" in role_codes:
        return "academic_director"
    return "teacher"


async def ensure_staff_roles(session: AsyncSession, tenant_id: int) -> dict[str, Role]:
    from app.services.rbac import ensure_builtin_roles

    await ensure_builtin_roles(session, tenant_id)
    result = await session.execute(select(Role).where(
        Role.tenant_id == tenant_id,
        Role.code.in_(_ROLE_BY_CODE),
    ))
    roles = {item.code: item for item in result.scalars().all()}
    for spec in ASSIGNABLE_STAFF_ROLES:
        if spec.code not in roles:
            role = Role(tenant_id=tenant_id, code=spec.code, name=spec.name, description=spec.description)
            session.add(role)
            roles[spec.code] = role
    await session.flush()
    return roles


async def get_staff_role_codes(session: AsyncSession, user_id: int) -> list[str]:
    result = await session.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, Role.code.in_(_ROLE_BY_CODE))
    )
    return normalize_staff_roles(list(result.scalars().all()))


async def replace_staff_roles(
    session: AsyncSession,
    user_id: int,
    role_codes: list[str],
    tenant_id: int,
) -> list[str]:
    normalized = normalize_staff_roles(role_codes)
    roles = await ensure_staff_roles(session, tenant_id)
    await session.execute(delete(UserRole).where(UserRole.user_id == user_id))
    for code in normalized:
        session.add(UserRole(user_id=user_id, role_id=roles[code].id))
    await session.flush()
    return normalized
