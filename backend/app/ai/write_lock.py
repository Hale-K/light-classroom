"""Acquire a database write lock on a stable tenant row, including SQLite."""
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import OperationalError

from app.models.org import Tenant


async def lock_tenant_write(session, tenant_id: int) -> None:
    # Unlike SELECT FOR UPDATE this acquires a SQLite write reservation as well.
    # A stable row also serializes the first request when no AiRun exists yet.
    try:
        result = await session.execute(update(Tenant).where(Tenant.id == tenant_id)
            .values(id=Tenant.id).execution_options(synchronize_session=False))
    except OperationalError as exc:
        await session.rollback()
        raise HTTPException(409, '当前有其他配置操作正在提交，请稍后重试') from exc
    if result.rowcount == 0:
        raise HTTPException(404, '学校不存在')
