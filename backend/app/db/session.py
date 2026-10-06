"""数据库 session - SQLModel + 多租户中间件

对标 MyBatis-Plus 的「多租户插件」：通过 ContextVar 携带当前请求的 tenant_id，
所有查询自动注入 tenant_id 过滤条件，防越权靠中间件强制。
"""
from contextvars import ContextVar
import json
from pathlib import Path
from time import perf_counter
from typing import AsyncGenerator
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import event, select, text
from sqlalchemy.orm import with_loader_criteria
from loguru import logger
from app.core.config import settings
from app.services.org.tenant import resolve_tenant_id

# ---------- 多租户上下文 ----------
# ContextVar 携带当前请求的 tenant_id（由中间件从 X-School-Code 解析后写入）
tenant_id_ctx: ContextVar[int | None] = ContextVar("tenant_id", default=None)
school_code_ctx: ContextVar[str | None] = ContextVar("school_code", default=None)


# ---------- 引擎与 Session 工厂 ----------
engine = create_async_engine(
    settings.database_url,
    # 保留中文原文，方便直接查看数据库中的 JSON 消息和业务数据。
    json_serializer=lambda value: json.dumps(value, ensure_ascii=False),
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    echo=settings.db_echo,  # 开发调试才开，默认关，避免日志刷屏导致终端会话被回收
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# DB_ECHO includes bound parameter values. Keep the diagnostic file logger
# statement-only so student names, identifiers and other values aren't copied
# into application logs.
if settings.db_sql_log:
    _sql_log_path = Path(__file__).resolve().parents[2] / "logs" / "sql.log"
    _sql_log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(_sql_log_path),
        filter=lambda record: record["extra"].get("sql_statement") is True,
        level="INFO",
        rotation="20 MB",
        retention="7 days",
        enqueue=True,
        encoding="utf-8",
    )

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _start_sql_timer(conn, cursor, statement, parameters, context, executemany):
        context._light_classroom_sql_started_at = perf_counter()

    @event.listens_for(engine.sync_engine, "after_cursor_execute")
    def _write_sql_log(conn, cursor, statement, parameters, context, executemany):
        started_at = getattr(context, "_light_classroom_sql_started_at", None)
        elapsed_ms = (perf_counter() - started_at) * 1000 if started_at is not None else 0
        logger.bind(sql_statement=True).info("{:.1f} ms | {}", elapsed_ms, statement)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每请求一个 session"""
    async with AsyncSessionLocal() as session:
        # 注入 before_execute 钩子：自动给所有查询拼 tenant_id 条件
        # （对标 MyBatis-Plus 多租户拦截器）
        @event.listens_for(session.sync_session, "do_orm_execute")
        def _add_tenant_filter(execute_state):
            tid = tenant_id_ctx.get()
            if tid is None:
                return
            if not execute_state.is_select:
                return
            # 遍历查询涉及的实体，凡含 tenant_id 列者，自动追加 tenant_id == tid
            # include_aliases=True 使其同时作用于 join/子查询中的别名
            options = []
            for desc in execute_state.statement.column_descriptions:
                entity = desc.get("entity")
                if entity is not None and hasattr(entity, "__table__") and "tenant_id" in entity.__table__.columns:
                    criterion = lambda cls: cls.tenant_id == tid
                    options.append(
                        with_loader_criteria(
                            entity,
                            criterion,
                            include_aliases=True,
                        )
                    )
            if options:
                execute_state.statement = execute_state.statement.options(*options)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------- 多租户中间件 ----------
async def tenant_middleware(request, call_next):
    """从请求头 X-School-Code 解析 tenant_id，写入 ContextVar

    所有请求默认携带学校代码（Julia 拍板 NF-01a）；缺失则回退默认代码。
    """
    school_code = request.headers.get("X-School-Code") or settings.default_school_code
    school_code_ctx.set(school_code)
    # A3: school_code → tenant_id 解析（带缓存），写入 ContextVar 供查询注入使用
    tenant_id = await resolve_tenant_id(school_code)
    tenant_id_ctx.set(tenant_id)
    response = await call_next(request)
    return response


async def init_db() -> None:
    """初始化数据库（建表 + 默认租户/平台超管种子，开发期用；生产走 Alembic 迁移）"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(SQLModel.metadata.create_all)

    # 开发期种子：默认租户，保证 default_school_code 可解析（A3）
    from app.models.org import Subject, Tenant
    async with AsyncSessionLocal() as session:
        stmt = select(Tenant).where(Tenant.code == settings.default_school_code)
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            session.add(Tenant(code=settings.default_school_code, name=settings.app_name))
            await session.commit()
            logger.info(f"[tenant] 种子租户已创建: {settings.default_school_code}")

    # 排课基础字典：普通高中九大学科
    async with AsyncSessionLocal() as session:
        existing_subjects = set((await session.execute(select(Subject.name))).scalars().all())
        names = ["语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"]
        session.add_all([Subject(name=name) for name in names if name not in existing_subjects])
        await session.commit()

    # 开发期种子：平台超管（创建学校后台）
    from app.models.admin import PlatformAdmin
    from app.core.security import get_password_hash
    async with AsyncSessionLocal() as session:
        exists = (await session.execute(
            select(PlatformAdmin).where(PlatformAdmin.username == settings.admin_username))).scalar_one_or_none()
        if exists is None:
            session.add(PlatformAdmin(username=settings.admin_username, name=settings.admin_name,
                                      password_hash=get_password_hash(settings.admin_password)))
            await session.commit()
            logger.info(f"[admin] 平台超管已创建: {settings.admin_username}")
