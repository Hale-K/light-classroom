"""平台超管 API - 登录 + 学校(租户)管理

平台端与学校端隔离：本模块使用原始 AsyncSessionLocal（不挂载多租户自动过滤），
以便跨租户创建/查询学校与校长号；鉴权走 get_current_admin（scope=admin 令牌）。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import create_admin_access_token, get_password_hash, verify_password
from app.db.session import AsyncSessionLocal
from app.api.deps import get_current_admin
from app.models.admin import PlatformAdmin
from app.models.org import Tenant, User
from app.models.enums import BaseUserRole, TenantType

router = APIRouter(prefix="/admin", tags=["平台管理"])


# ---------- Schemas ----------
class AdminLoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AdminOut(BaseModel):
    id: int
    username: str
    name: str


class SchoolCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$",
                      description="学校代码（业务标识，可读可记）")
    name: str = Field(min_length=1, max_length=100, description="学校名称")
    type: TenantType = TenantType.org
    province: str = Field(min_length=2, max_length=50, description="学校所在省份")
    gaokao_mode: str = Field(pattern=r"^(3\+1\+2|3\+3|traditional)$", description="学校默认高考模式")
    admin_name: str = Field(min_length=1, max_length=50, description="校长姓名")
    admin_phone: str = Field(min_length=5, max_length=20, description="校长登录手机号")
    admin_password: str = Field(min_length=6, description="校长登录密码")


class SchoolOut(BaseModel):
    id: int
    code: str
    name: str
    type: str
    province: str
    gaokao_mode: str
    created_at: str
    admin_phone: str | None = None


class SchoolUpdate(BaseModel):
    """编辑学校：名称与校长手机号可改；学校代码作为业务标识，锁定不可改"""
    name: str | None = Field(default=None, min_length=1, max_length=100, description="学校名称")
    province: str | None = Field(default=None, min_length=2, max_length=50)
    gaokao_mode: str | None = Field(default=None, pattern=r"^(3\+1\+2|3\+3|traditional)$")
    admin_phone: str | None = Field(default=None, min_length=5, max_length=20,
                                    description="校长登录手机号（空则不改）")


class ResetPasswordIn(BaseModel):
    """重置校长登录密码"""
    password: str = Field(min_length=6, max_length=64, description="新密码")


# ---------- 依赖：原始 session（无多租户过滤，供平台跨租户操作） ----------
async def get_admin_session():
    async with AsyncSessionLocal() as session:
        yield session
        await session.commit()
    # 失败回滚由 AsyncSessionLocal 上下文管理器保证


# ---------- 认证 ----------
@router.post("/login", summary="平台超管登录")
async def login(body: AdminLoginIn, session: AsyncSession = Depends(get_admin_session)):
    admin = (await session.execute(
        select(PlatformAdmin).where(PlatformAdmin.username == body.username))).scalar_one_or_none()
    if admin is None or admin.status != "active" or not verify_password(body.password, admin.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    return {"code": 0, "message": "ok", "data": {
        "access_token": create_admin_access_token(admin.id),
        "admin": AdminOut(id=admin.id, username=admin.username, name=admin.name).model_dump(),
    }}


@router.get("/me", summary="当前超管")
async def me(admin: PlatformAdmin = Depends(get_current_admin)):
    return {"code": 0, "message": "ok", "data": AdminOut(id=admin.id, username=admin.username,
                                                         name=admin.name).model_dump()}


# ---------- 学校(租户)管理 ----------
@router.get("/schools", summary="学校列表")
async def list_schools(session: AsyncSession = Depends(get_admin_session),
                       _: PlatformAdmin = Depends(get_current_admin)):
    rows = (await session.execute(
        select(Tenant).order_by(Tenant.id.desc()))).scalars().all()
    # 每校回填其校长手机号（取担任 director 的首位账号）
    out = []
    for t in rows:
        phone = (await session.execute(
            select(User.phone).where(User.tenant_id == t.id, User.role == BaseUserRole.director)
            .limit(1))).scalar_one_or_none()
        out.append(SchoolOut(id=t.id, code=t.code, name=t.name, type=t.type.value,
                             province=t.province, gaokao_mode=t.gaokao_mode,
                             created_at=t.created_at.isoformat(), admin_phone=phone).model_dump())
    return {"code": 0, "message": "ok", "data": out}


@router.post("/schools", summary="创建学校（同时初始化校长号）", status_code=201)
async def create_school(body: SchoolCreate, session: AsyncSession = Depends(get_admin_session),
                        _: PlatformAdmin = Depends(get_current_admin)):
    # 学校代码唯一性校验
    exists = (await session.execute(
        select(Tenant).where(Tenant.code == body.code))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="学校代码已存在")
    # 校长手机号全局唯一性校验（同号不能跨校重复）
    dup = (await session.execute(
        select(User).where(User.phone == body.admin_phone))).scalar_one_or_none()
    if dup:
        raise HTTPException(status_code=409, detail="该校长手机号已被使用")

    tenant = Tenant(
        code=body.code,
        name=body.name,
        type=body.type,
        province=body.province,
        gaokao_mode=body.gaokao_mode,
    )
    session.add(tenant)
    await session.flush()  # 取到 tenant.id

    user = User(name=body.admin_name, phone=body.admin_phone,
                password_hash=get_password_hash(body.admin_password),
                role=BaseUserRole.director, tenant_id=tenant.id)
    session.add(user)
    await session.flush()

    return {"code": 0, "message": "ok", "data": SchoolOut(id=tenant.id, code=tenant.code,
                                                          name=tenant.name, type=tenant.type.value,
                                                          province=tenant.province,
                                                          gaokao_mode=tenant.gaokao_mode,
                                                          created_at=tenant.created_at.isoformat(),
                                                          admin_phone=body.admin_phone).model_dump()}


@router.put("/schools/{school_id}", summary="编辑学校（名称/校长手机号可改，代码锁定）")
async def update_school(school_id: int, body: SchoolUpdate,
                        session: AsyncSession = Depends(get_admin_session),
                        _: PlatformAdmin = Depends(get_current_admin)):
    tenant = (await session.execute(
        select(Tenant).where(Tenant.id == school_id))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="学校不存在")

    if body.name:
        tenant.name = body.name
    if body.province:
        tenant.province = body.province
    if body.gaokao_mode:
        tenant.gaokao_mode = body.gaokao_mode

    # 校长登录账号（手机号）：改则更新该校 director 账号，密码不变，超管身份不变
    if body.admin_phone is not None:
        cur_phone = (await session.execute(
            select(User.phone).where(User.tenant_id == school_id,
                                     User.role == BaseUserRole.director).limit(1))).scalar_one_or_none()
        new_phone = body.admin_phone.strip()
        if new_phone and new_phone != cur_phone:
            dup = (await session.execute(
                select(User.id).where(User.phone == new_phone, User.tenant_id != school_id)
            )).scalar_one_or_none()
            if dup:
                raise HTTPException(status_code=409, detail="该手机号已被其他学校使用")
            await session.execute(
                update(User).where(User.tenant_id == school_id, User.role == BaseUserRole.director)
                .values(phone=new_phone))
            cur_phone = new_phone

    await session.flush()
    phone = (await session.execute(
        select(User.phone).where(User.tenant_id == school_id,
                                 User.role == BaseUserRole.director).limit(1))).scalar_one_or_none()
    return {"code": 0, "message": "ok", "data": SchoolOut(
        id=tenant.id, code=tenant.code, name=tenant.name, type=tenant.type.value,
        province=tenant.province, gaokao_mode=tenant.gaokao_mode,
        created_at=tenant.created_at.isoformat(), admin_phone=phone).model_dump()}


@router.post("/schools/{school_id}/reset-password", summary="重置校长登录密码")
async def reset_password(school_id: int, body: ResetPasswordIn,
                         session: AsyncSession = Depends(get_admin_session),
                         _: PlatformAdmin = Depends(get_current_admin)):
    principal = (await session.execute(
        select(User).where(User.tenant_id == school_id, User.role == BaseUserRole.director)
        .limit(1))).scalar_one_or_none()
    if principal is None:
        raise HTTPException(status_code=404, detail="该校暂无校长账号")
    principal.password_hash = get_password_hash(body.password)
    await session.flush()
    return {"code": 0, "message": "ok", "data": {"school_id": school_id, "phone": principal.phone}}


@router.get("/schools/stats", summary="学校总数")
async def school_stats(session: AsyncSession = Depends(get_admin_session),
                       _: PlatformAdmin = Depends(get_current_admin)):
    total = (await session.execute(select(func.count(Tenant.id)))).scalar_one()
    return {"code": 0, "message": "ok", "data": {"total": total}}
