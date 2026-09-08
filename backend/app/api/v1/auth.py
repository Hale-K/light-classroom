"""认证 API - 登录 / 注册 / 当前用户（A4）"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import SQLModel

from app.core.security import create_access_token, get_password_hash, verify_password
from app.core.config import settings
from app.db.session import AsyncSessionLocal, get_session, school_code_ctx, tenant_id_ctx
from app.api.deps import get_current_user, get_user_permission_codes
from app.models.org import User, Tenant, TenantConfig, Class, Student, Grade, OrganizationUnit
from app.models.enums import BaseUserRole
from app.services.academic.rollover import build_rollover_plan, next_grade_level, promoted_class_name
from app.services.rbac import (
    build_menu,
    ensure_menu_permissions,
    load_menu_permission_map,
    load_menus,
)
from app.services.org.staff_roles import effective_menu_role, get_staff_role_codes

router = APIRouter(prefix="/auth", tags=["认证"])


async def _public_session():
    """登录专用：裸 session（不注入多租户过滤）。

    登录凭手机号全局定位账号所属学校，登录前不应预知学校代码，
    故这里不使用 get_session 的多租户自动过滤。
    """
    async with AsyncSessionLocal() as s:
        yield s
        await s.commit()


class LoginIn(BaseModel):
    phone: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1)


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    phone: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=6)
    role: BaseUserRole = BaseUserRole.teacher


class UserOut(BaseModel):
    id: int
    name: str
    phone: str
    role: str
    roles: list[str] = Field(default_factory=list)


class SchoolSettingsIn(BaseModel):
    province: str | None = Field(default=None, min_length=2, max_length=50)
    gaokao_mode: str | None = Field(default=None, pattern=r"^(3\+1\+2|3\+3|traditional)$")


class AcademicYearEntry(BaseModel):
    entry_year: int = Field(ge=2000, le=2100)
    status: str = Field(default="active", pattern="^(active|inactive)$")


class AcademicYearsIn(BaseModel):
    years: list[AcademicYearEntry] = Field(default_factory=list, max_length=30)
    current_entry_year: int | None = Field(default=None, ge=2000, le=2100)
    current_academic_year: str | None = Field(default=None, min_length=9, max_length=20)
    current_term: str = Field(default="1", pattern=r"^(1|2)$")


class AcademicYearRolloverIn(BaseModel):
    source_entry_year: int = Field(ge=2000, le=2100)


def _rollover_config_value(config: TenantConfig | None) -> dict:
    return config.config_value if config and isinstance(config.config_value, dict) else {}


async def _academic_year_config(session: AsyncSession, tenant_id: int) -> TenantConfig | None:
    return (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key == "academic_years",
    ))).scalars().first()


def _academic_year_row(entry_year: int, status: str = "active") -> dict:
    return {
        "entry_year": entry_year,
        "cohort_label": f"{entry_year}届",
        "grade_years": {
            "高一": f"{entry_year}-{entry_year + 1}",
            "高二": f"{entry_year + 1}-{entry_year + 2}",
            "高三": f"{entry_year + 2}-{entry_year + 3}",
        },
        "status": status,
    }


def _default_entry_year() -> int:
    now = datetime.now()
    return now.year if now.month >= 8 else now.year - 1


@router.post("/login", summary="登录")
async def login(body: LoginIn, response: Response, session: AsyncSession = Depends(_public_session)):
    # 凭手机号（全局唯一）定位账号，登录前无需预知学校代码
    stmt = select(User).where(User.phone == body.phone)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if (user is None or user.status != "active"
            or not verify_password(body.password, user.password_hash)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    if user.frozen:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"账号已被冻结：{user.freeze_reason or '请联系管理员'}",
        )
    user.last_login_at = datetime.utcnow()
    await session.flush()
    # 由账号决定其所属学校，随登录结果返回，前端无需预先选择
    tenant = await session.get(Tenant, user.tenant_id)
    role_codes = await get_staff_role_codes(session, user.id)
    token = create_access_token(user.id, extra={"tid": user.tenant_id})
    response.set_cookie("lc_access", token, httponly=True, secure=settings.app_env == "prod", samesite="lax", max_age=settings.jwt_access_token_expire_minutes * 60, path="/")
    return {"code": 0, "message": "ok", "data": {
        "user": UserOut(id=user.id, name=user.name, phone=user.phone, role=user.role.value,
                        roles=role_codes).model_dump(),
        "school": {
            "code": tenant.code if tenant else None,
            "name": tenant.name if tenant else None,
            "province": tenant.province if tenant else None,
            "gaokao_mode": tenant.gaokao_mode if tenant else None,
        }}}


@router.post("/register", summary="注册学生/教师")
async def register(body: RegisterIn, session: AsyncSession = Depends(get_session)):
    tid = tenant_id_ctx.get()
    if tid is None:
        raise HTTPException(status_code=400, detail="缺少学校代码头或租户不存在")
    exists = (await session.execute(select(User).where(User.phone == body.phone, User.tenant_id == tid))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="该账号已存在")
    user = User(name=body.name, phone=body.phone, password_hash=get_password_hash(body.password),
                role=body.role, tenant_id=tid)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return {"code": 0, "message": "ok", "data": UserOut(id=user.id, name=user.name,
                                                        phone=user.phone, role=user.role.value).model_dump()}


@router.get("/me", summary="当前用户")
async def me(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    role_codes = await get_staff_role_codes(session, user.id)
    return {"code": 0, "message": "ok", "data": UserOut(id=user.id, name=user.name,
                                                        phone=user.phone, role=user.role.value,
                                                        roles=role_codes).model_dump()}


@router.get("/menus", summary="当前用户的菜单树（按角色工厂构建）")
async def menus(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenant = await session.get(Tenant, user.tenant_id)
    gaokao_mode = tenant.gaokao_mode if tenant else "3+1+2"
    role_codes = await get_staff_role_codes(session, user.id)
    permission_codes = await get_user_permission_codes(session, user.id)
    await ensure_menu_permissions(session)
    menu_permissions = await load_menu_permission_map(session)
    menu_items = await load_menus(session, include_disabled=False)
    return {"code": 0, "message": "ok", "data": {
        "gaokao_mode": gaokao_mode,
        "menus": build_menu(
            effective_menu_role(user.role, role_codes),
            gaokao_mode,
            permission_codes=permission_codes,
            menu_permissions=menu_permissions,
            menu_items=menu_items,
        ),
        }}


@router.get("/school", summary="当前学校设置")
async def school_settings(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="学校不存在")
    return {"code": 0, "message": "ok", "data": {
        "id": tenant.id,
        "code": tenant.code,
        "name": tenant.name,
        "province": tenant.province,
        "gaokao_mode": tenant.gaokao_mode,
    }}


@router.patch("/school", summary="修改当前学校默认高考模式")
async def update_school_settings(
    body: SchoolSettingsIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.role != BaseUserRole.director:
        raise HTTPException(status_code=403, detail="仅校级管理员可以修改学校设置")
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="学校不存在")
    values = body.model_dump(exclude_none=True)
    for key, value in values.items():
        setattr(tenant, key, value)
    await session.commit()
    await session.refresh(tenant)
    return {"code": 0, "message": "ok", "data": {
        "id": tenant.id,
        "code": tenant.code,
        "name": tenant.name,
        "province": tenant.province,
        "gaokao_mode": tenant.gaokao_mode,
    }}


@router.get("/academic-years", summary="查询学校学年届次列表")
async def academic_years(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == user.tenant_id,
        TenantConfig.config_key == "academic_years",
    ))).scalars().first()
    entries = config.config_value.get("years", []) if config and isinstance(config.config_value, dict) else []
    if not entries:
        base_year = _default_entry_year()
        rows = [_academic_year_row(year) for year in range(base_year, base_year - 5, -1)]
    else:
        rows = [_academic_year_row(int(item["entry_year"]), str(item.get("status", "active")))
                for item in entries if isinstance(item, dict) and item.get("entry_year") is not None]
    current = config.config_value.get("current_entry_year") if config and isinstance(config.config_value, dict) else None
    current = current or (rows[0]["entry_year"] if rows else None)
    current_academic_year = config.config_value.get("current_academic_year") if config and isinstance(config.config_value, dict) else None
    current_academic_year = current_academic_year or (f"{current}-{current + 1}" if current else None)
    current_term = config.config_value.get("current_term", "1") if config and isinstance(config.config_value, dict) else "1"
    return {"code": 0, "message": "ok", "data": {"years": rows, "current_entry_year": current, "current_academic_year": current_academic_year, "current_term": current_term}}


@router.put("/academic-years", summary="保存学校学年届次列表")
async def save_academic_years(
    body: AcademicYearsIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.role != BaseUserRole.director:
        raise HTTPException(status_code=403, detail="仅校长可以配置学年届次")
    rows = sorted({item.entry_year: item.status for item in body.years}.items(), reverse=True)
    if body.current_entry_year is not None and body.current_entry_year not in dict(rows):
        raise HTTPException(status_code=422, detail="当前高一届别必须来自届次列表")
    config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == user.tenant_id,
        TenantConfig.config_key == "academic_years",
    ))).scalars().first()
    value = {
        "years": [{"entry_year": year, "status": status} for year, status in rows],
        "current_entry_year": body.current_entry_year or (rows[0][0] if rows else None),
        "current_academic_year": body.current_academic_year or (f"{(body.current_entry_year or (rows[0][0] if rows else 0))}-{(body.current_entry_year or (rows[0][0] if rows else 0)) + 1}"),
        "current_term": body.current_term,
    }
    if config is None:
        config = TenantConfig(tenant_id=user.tenant_id, config_key="academic_years", config_value=value, updated_by=user.id)
        session.add(config)
    else:
        config.config_value = value
        config.updated_by = user.id
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "years": [_academic_year_row(year, status) for year, status in rows],
        "current_entry_year": value["current_entry_year"],
        "current_academic_year": value["current_academic_year"],
        "current_term": value["current_term"],
    }}


@router.post("/academic-year-rollover/preview", summary="预览下一学年滚动")
async def preview_academic_year_rollover(
    body: AcademicYearRolloverIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """只读预览：不修改届次、班级、学生或任教关系。"""
    plan = build_rollover_plan(body.source_entry_year)
    source_label = str(body.source_entry_year)
    classes = (await session.execute(select(Class).where(
        Class.tenant_id == user.tenant_id,
        Class.cohort_label == source_label,
    ))).scalars().all()
    students = (await session.execute(select(Student).where(
        Student.tenant_id == user.tenant_id,
        Student.grade_id.is_not(None),
        Student.status == "studying",
    ))).scalars().all()
    class_ids = {item.id for item in classes}
    current_students = [item for item in students if item.class_id in class_ids]
    grade_counts = {1: 0, 2: 0, 3: 0}
    for item in classes:
        # grade_id 对应的年级层级由后续查询补齐；名称兼容“高一/高二/高三”。
        level = 1 if "高一" in item.name else 2 if "高二" in item.name else 3 if "高三" in item.name else 0
        if level:
            grade_counts[level] += 1
    history_config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == user.tenant_id,
        TenantConfig.config_key == "academic_year_rollover_history",
    ))).scalars().first()
    history = _rollover_config_value(history_config).get("rollovers", [])
    already_done = any(item.get("source_entry_year") == body.source_entry_year for item in history if isinstance(item, dict))
    return {"code": 0, "message": "ok", "data": {
        "source_entry_year": body.source_entry_year,
        "source_cohort_label": source_label,
        "target_entry_year": plan.target_entry_year,
        "target_cohort_label": str(plan.target_entry_year),
        "source_academic_year": plan.source_academic_year,
        "target_academic_year": plan.target_academic_year,
        "class_count": len(classes),
        "student_count": len(current_students),
        "promote_high_one_classes": grade_counts[1],
        "promote_high_two_classes": grade_counts[2],
        "graduate_high_three_classes": grade_counts[3],
        "already_done": already_done,
        "warnings": ([] if classes else [f"未找到 {source_label} 的班级数据，请先检查当前届别编码"]),
    }}


@router.post("/academic-year-rollover/commit", summary="确认滚动到下一学年")
async def commit_academic_year_rollover(
    body: AcademicYearRolloverIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """幂等执行：保留旧班级记录，仅为升年级学生建立新班级并推进当前届次。"""
    if user.role != BaseUserRole.director:
        raise HTTPException(status_code=403, detail="仅校长可以执行学年滚动")
    plan = build_rollover_plan(body.source_entry_year)
    source_label = str(body.source_entry_year)
    history_config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == user.tenant_id,
        TenantConfig.config_key == "academic_year_rollover_history",
    ))).scalars().first()
    history_value = _rollover_config_value(history_config)
    history = history_value.setdefault("rollovers", [])
    if any(item.get("source_entry_year") == body.source_entry_year for item in history if isinstance(item, dict)):
        raise HTTPException(status_code=409, detail="该学年已经滚动过，不能重复执行")

    old_classes = (await session.execute(select(Class).where(
        Class.tenant_id == user.tenant_id, Class.cohort_label == source_label,
    ))).scalars().all()
    old_class_ids = {item.id for item in old_classes}
    students = (await session.execute(select(Student).where(
        Student.tenant_id == user.tenant_id, Student.class_id.in_(old_class_ids), Student.status == "studying",
    ))).scalars().all() if old_class_ids else []
    class_map: dict[int, int] = {}
    grades = (await session.execute(select(Grade).where(Grade.tenant_id == user.tenant_id))).scalars().all()
    grade_by_level = {item.level: item.id for item in grades}
    created_classes = 0
    for old in old_classes:
        level = 1 if "高一" in old.name else 2 if "高二" in old.name else 3 if "高三" in old.name else 0
        if not level or next_grade_level(level) is None:
            continue
        target_grade_id = grade_by_level.get(next_grade_level(level))
        if target_grade_id is None:
            continue
        existing = (await session.execute(select(Class).where(
            Class.tenant_id == user.tenant_id, Class.grade_id == target_grade_id,
            Class.cohort_label == str(plan.target_entry_year), Class.name == promoted_class_name(old.name, level),
        ))).scalars().first()
        new_class = existing or Class(
            tenant_id=user.tenant_id, grade_id=target_grade_id, campus_id=old.campus_id,
            home_room_id=old.home_room_id, class_type=old.class_type,
            planned_student_count=old.planned_student_count, name=promoted_class_name(old.name, level),
            cohort_label=str(plan.target_entry_year), head_teacher_id=old.head_teacher_id,
            deputy_head_teacher_id=old.deputy_head_teacher_id,
        )
        if existing is None:
            session.add(new_class)
            await session.flush()
            created_classes += 1
        class_map[old.id] = new_class.id
    for student in students:
        if student.class_id in class_map:
            student.class_id = class_map[student.class_id]
    # 保存可审计的映射，旧班级记录不删除，便于历史追溯和回滚。
    history.append({"source_entry_year": body.source_entry_year, "target_entry_year": plan.target_entry_year,
                    "student_count": len(students), "created_class_count": created_classes,
                    "class_map": {str(k): v for k, v in class_map.items()}})
    if history_config is None:
        session.add(TenantConfig(tenant_id=user.tenant_id, config_key="academic_year_rollover_history",
                                 config_value=history_value, updated_by=user.id))
    else:
        history_config.config_value = history_value
        history_config.updated_by = user.id
    years_config = await _academic_year_config(session, user.tenant_id)
    years_value = _rollover_config_value(years_config)
    years = {int(item["entry_year"]): item.get("status", "active") for item in years_value.get("years", []) if isinstance(item, dict) and item.get("entry_year") is not None}
    years.setdefault(body.source_entry_year, "active")
    years[plan.target_entry_year] = "active"
    next_value = {"years": [{"entry_year": y, "status": s} for y, s in sorted(years.items(), reverse=True)],
                  "current_entry_year": plan.target_entry_year, "current_academic_year": plan.target_academic_year,
                  "current_term": "1"}
    # 年级部是“届别快照”的组织节点：保留节点 ID 和人员关联，只更新其业务归属。
    grade_units = (await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == user.tenant_id,
        OrganizationUnit.unit_type == "grade_group",
    ))).scalars().all()
    grade_labels = {1: "高一年级部", 2: "高二年级部", 3: "高三年级部"}
    for unit in grade_units:
        level = 1 if "高一" in unit.name else 2 if "高二" in unit.name else 3 if "高三" in unit.name else None
        if level:
            # 每个年级部对应“当前在读届”：滚动后高一是新生届，高二/高三分别沿用上一届。
            cohort_year = plan.target_entry_year - level + 1
            unit.name = f"{cohort_year}届 · {grade_labels[level]}"
            unit.cohort_label = str(cohort_year)
            unit.academic_year = plan.target_academic_year
    if years_config is None:
        session.add(TenantConfig(tenant_id=user.tenant_id, config_key="academic_years", config_value=next_value, updated_by=user.id))
    else:
        years_config.config_value = next_value
        years_config.updated_by = user.id
    await session.commit()
    return {"code": 0, "message": "学年已滚动", "data": {**next_value, "promoted_student_count": len(students), "created_class_count": created_classes}}
