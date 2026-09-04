"""租户解析服务 - school_code → tenant_id（A3）

策略：内存 TTL 缓存优先，未命中回源查 tenant 表。
私有化部署固定单值（default_school_code），映射几乎不变，缓存收益高。
生产可替换为 Redis 分布式缓存（见 .env#REDIS_URL）。
"""
from time import time
from loguru import logger
from sqlalchemy import select

from app.models.org import Tenant

# 内存 TTL 缓存：{school_code: (tenant_id, expire_ts)}
_CACHE: dict[str, tuple[int, float]] = {}
_CACHE_TTL = 600  # 10 分钟


async def resolve_tenant_id(school_code: str) -> int | None:
    """按学校代码解析租户 ID。查不到返回 None（放行并由上层决策）。"""
    now = time()
    hit = _CACHE.get(school_code)
    if hit and hit[1] > now:
        return hit[0]

    # 延迟导入避免与 app.db.session 循环依赖
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        stmt = select(Tenant.id).where(Tenant.code == school_code)
        result = await session.execute(stmt)
        tid = result.scalar_one_or_none()

    if tid is not None:
        _CACHE[school_code] = (tid, now + _CACHE_TTL)
    else:
        logger.warning(f"[tenant] 未找到学校代码对应的租户: school_code={school_code}")
    return tid


def invalidate(school_code: str) -> None:
    """租户增删后失效缓存（预留，供组织模块创建学校时调用）"""
    _CACHE.pop(school_code, None)