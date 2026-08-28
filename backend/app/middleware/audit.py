"""审计日志中间件（A5）

- 在响应返回后异步落一条 AuditLog：动作、资源、用户、IP、耗时、结果。
- 默认只记录写操作（POST/PUT/PATCH/DELETE）以控制冗余；读密集接口走留痕开关。
- 精细的 old/new 值差异属业务层职责，需在 Service 中显式调用。
"""
import time

from fastapi import Request
from loguru import logger

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import AsyncSessionLocal, tenant_id_ctx
from app.models.audit import AuditLog

# 不参与审计的系统接口（健康检查/文档等）
_SKIP = {"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json", "/api/v1/openapi.json"}

_MUTATION = {"POST", "PUT", "PATCH", "DELETE"}


def _extract_user_id(request: Request) -> int | None:
    """从 Bearer 令牌解析 user_id；解析失败返回 None（未登录场景）。"""
    auth = request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    try:
        payload = decode_access_token(auth[7:])
        sub = payload.get("sub")
        return int(sub) if sub is not None else None
    except Exception:
        return None


async def audit_middleware(request: Request, call_next):
    if not settings.audit_enabled or request.url.path.rstrip("/") in _SKIP:
        return await call_next(request)

    if settings.audit_log_mutations_only and request.method not in _MUTATION:
        return await call_next(request)

    start = time.monotonic()
    response = await call_next(request)
    duration_ms = int((time.monotonic() - start) * 1000)

    # 写在响应之后：此时 tenant_middleware 已解析完成，可读到 tenant_id
    try:
        tid = tenant_id_ctx.get()
        async with AsyncSessionLocal() as session:
            session.add(
                AuditLog(
                    tenant_id=tid or 0,
                    user_id=_extract_user_id(request),
                    action=f"{request.method} {request.url.path}",
                    resource=request.url.path.split("/")[-1],
                    ip=request.client.host if request.client else None,
                    old_value=None,
                    new_value=None,
                )
            )
            await session.commit()
        logger.debug(
            f"[audit] {request.method} {request.url.path} -> {response.status_code} {duration_ms}ms"
        )
    except Exception as e:  # 审计失败不影响主流程
        logger.warning(f"[audit] 记录失败: {e}")

    return response