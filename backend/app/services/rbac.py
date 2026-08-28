"""细粒度权限点：目录定义 + 播种 + 角色权限管理服务

设计说明：
- PERMISSION_CATALOG 是系统全部权限点的单一真源，按「模块」分组。
- ensure_permissions() 在启动时把目录同步进 permission 表（幂等 upsert）。
- 角色（Role）既包含系统内置角色，也允许校长在该页自行新建，并逐角色勾选权限点（RolePermission）。
"""
from sqlalchemy import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.org import Tenant, User

# 内置角色（编码保留，不允许删除/改名）
BUILTIN_ROLE_CODES = {"school_admin", "academic_director", "head_teacher", "subject_teacher"}

PermissionSpec = tuple[str, str, str]  # (module, name, code)


def role_belongs_to_tenant(role: Role, tenant_id: int) -> bool:
    return role.tenant_id == tenant_id


async def _tenant_role(session: AsyncSession, role_id: int, tenant_id: int) -> Role:
    role = await session.get(Role, role_id)
    if role is None or not role_belongs_to_tenant(role, tenant_id):
        raise ValueError("角色不存在")
    return role


# 权限点目录（模块分组，顺序即展示顺序）
PERMISSION_CATALOG: list[PermissionSpec] = [
    # 工作台
    ("工作台", "查看工作台", "dashboard:view"),
    # 试卷库
    ("试卷库", "查看试卷", "paper:view"),
    ("试卷库", "新建/编辑试卷", "paper:write"),
    ("试卷库", "发布试卷", "paper:publish"),
    ("试卷库", "删除试卷", "paper:delete"),
    # 扫描进卷
    ("扫描进卷", "查看扫描批次", "scan:view"),
    ("扫描进卷", "上传扫描件", "scan:upload"),
    ("扫描进卷", "切分/分配/确认批次", "scan:process"),
    # 排课管理
    ("排课管理", "查看课表与任教关系", "scheduling:view"),
    ("排课管理", "配置任教关系", "scheduling:assign"),
    ("排课管理", "生成课表", "scheduling:generate"),
    # 班级排座
    ("班级排座", "查看座位表", "seating:view"),
    ("班级排座", "建立规则并生成座位", "seating:manage"),
    # 选科走班
    ("选科走班", "查看选科分布", "gaokao:view"),
    ("选科走班", "生成教学班/课表", "gaokao:manage"),
    # 学生档案
    ("学生档案", "查看学生名册", "students:view"),
    ("学生档案", "新增/编辑/删除学生", "students:manage"),
    # 行政班管理
    ("行政班管理", "查看班级与名单", "classes:view"),
    ("行政班管理", "调整班级与排座", "classes:manage"),
    # 考试与排考
    ("考试管理", "查看考试与场次", "exam:view"),
    ("考试管理", "新建/编排考试", "exam:manage"),
    # 打分阅卷
    ("打分阅卷", "查看作答与成绩", "grading:view"),
    ("打分阅卷", "录入/修改成绩", "grading:write"),
    # 组织机构
    ("组织机构", "查看组织架构", "organization:view"),
    ("组织机构", "维护组织与任命", "organization:manage"),
    # 空间资源
    ("空间资源", "查看空间资源", "facilities:view"),
    ("空间资源", "维护空间资源", "facilities:manage"),
    # 人员与权限
    ("人员与权限", "查看人员账号", "staff:view"),
    ("人员与权限", "管理账号与状态", "staff:manage"),
    ("人员与权限", "管理角色与权限", "rbac:manage"),
    # 会议管理
    ("会议管理", "查看会议", "meetings:view"),
    ("会议管理", "新建/编辑会议", "meetings:manage"),
]


async def ensure_permissions(session: AsyncSession) -> None:
    """幂等地把权限点目录同步进 permission 表。"""
    existing = {
        item.code: item
        for item in (await session.execute(select(Permission))).scalars().all()
    }
    for module, name, code in PERMISSION_CATALOG:
        item = existing.get(code)
        if item is None:
            session.add(Permission(code=code, name=name, module=module))
            continue
        item.name = name
        item.module = module
    await session.flush()


# 内置角色的名称与说明
BUILTIN_ROLES: tuple[tuple[str, str, str], ...] = (
    ("school_admin", "校长管理员", "学校最高权限，可管理全部功能与人员权限"),
    ("academic_director", "教导主任", "负责教学管理：排课、排考、选科与教学安排"),
    ("head_teacher", "班主任", "负责行政班学生管理与班级排座"),
    ("subject_teacher", "任教老师", "承担学科教学、建卷与阅卷任务"),
)

# 内置角色默认权限点（首次建立时写入；此后以页面勾选为准）
BUILTIN_ROLE_DEFAULTS: dict[str, set[str]] = {
    "school_admin": {code for _module, _name, code in PERMISSION_CATALOG},
    "academic_director": {
        "dashboard:view", "exam:view", "exam:manage", "grading:view", "grading:write",
        "scan:view", "scan:process", "scheduling:view", "scheduling:assign", "scheduling:generate",
        "seating:view", "seating:manage", "gaokao:view", "gaokao:manage",
        "students:view", "classes:view", "classes:manage", "organization:view",
        "facilities:view", "facilities:manage", "meetings:view", "meetings:manage",
    },
    "head_teacher": {
        "dashboard:view", "exam:view", "grading:view", "scan:view",
        "seating:view", "seating:manage", "students:view", "classes:view", "meetings:view",
    },
    "subject_teacher": {
        "dashboard:view", "exam:view", "paper:view", "paper:write",
        "scan:view", "scan:upload", "grading:view", "grading:write", "students:view",
    },
}


async def ensure_builtin_roles(session: AsyncSession, tenant_id: int | None = None) -> None:
    """Ensure every school owns an independent copy of the builtin roles."""
    await ensure_permissions(session)
    tenant_ids = [tenant_id] if tenant_id is not None else list(
        (await session.execute(select(Tenant.id))).scalars().all()
    )
    all_perms = list((await session.execute(select(Permission.code, Permission.id))).all())
    code_to_pid = {code: permission_id for code, permission_id in all_perms}

    for current_tenant_id in tenant_ids:
        for code, name, description in BUILTIN_ROLES:
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
            for permission_code in BUILTIN_ROLE_DEFAULTS.get(code, set()):
                permission_id = code_to_pid.get(permission_code)
                if permission_id is not None:
                    session.add(RolePermission(role_id=role.id, permission_id=permission_id))
    await session.flush()


async def list_permissions(session: AsyncSession) -> list[dict]:
    """Return only supported permission points, in catalog order."""
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for module, name, code in PERMISSION_CATALOG:
        if module not in grouped:
            grouped[module] = []
            order.append(module)
        grouped[module].append({"code": code, "name": name})
    return [{"module": module, "permissions": grouped[module]} for module in order]


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
    code_to_id = {code: pid for code, pid in all_perms}
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
