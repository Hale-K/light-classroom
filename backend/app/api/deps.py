"""认证与授权依赖 - A4/A6

- get_current_user：解析 JWT，返回当前登录用户
- require_permission：RBAC 权限点校验（缓存角色→权限映射）
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_session, tenant_id_ctx
from app.models.org import User
from app.models.admin import PlatformAdmin
from app.models.rbac import Role, UserRole, Permission, RolePermission

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    """认证依赖：校验 Bearer Token，返回当前用户；失败抛 401。"""
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少令牌")
    try:
        payload = decode_access_token(creds.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌载荷缺失")

    # 令牌携带租户 ID，同步到当前上下文（与 X-School-Code 路由一致）
    tid = payload.get("tid")
    if tid is not None:
        tenant_id_ctx.set(tid)

    user = await session.get(User, int(user_id))
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return user


async def get_current_tenant() -> int:
    """当前请求的租户 ID（由中间件按 X-School-Code 解析）。

    写入操作必须用它显式赋值 tenant_id，否则默认 0 将无法被多租户过滤命中。
    """
    tid = tenant_id_ctx.get()
    if tid is None:
        raise HTTPException(status_code=400, detail="缺少学校代码头或租户不存在")
    return tid


async def get_current_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> PlatformAdmin:
    """平台超管认证依赖：仅接受 scope=admin 的令牌（与学校内用户令牌隔离）。"""
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少令牌")
    try:
        payload = decode_access_token(creds.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")
    if payload.get("scope") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="非平台管理员令牌")
    admin = await session.get(PlatformAdmin, int(payload["sub"]))
    if admin is None or admin.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理员不存在或已停用")
    return admin


async def get_user_permission_codes(session: AsyncSession, user_id: int) -> set[str]:
    """查询某用户拥有的全部权限点编码（user → role → permission）"""
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    result = await session.execute(stmt)
    return set(result.scalars().all())


class require_permission:
    """权限点校验依赖工厂：require_permission("paper:create")"""

    def __init__(self, code: str):
        self.code = code

    async def __call__(
        self,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> User:
        codes = await get_user_permission_codes(session, user.id)
        if self.code not in codes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"无权限: {self.code}",
            )
        return user