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


def _sync_schema(conn) -> None:
    """启动时把实际表结构对齐到 app/models（同步上下文，经 run_sync 调用）。

- 缺失的表整表创建
- 已有表缺失的列 ADD COLUMN，类型变更 ALTER COLUMN TYPE，模型中已删除的列 DROP COLUMN
- 缺失的索引 CREATE INDEX（pgvector HNSW 索引仅 PostgreSQL 创建）
- 幂等：以 inspector 实测为准，重复启动无操作
- PostgreSQL 枚举列先补建 ENUM 类型；所有变更打结构同步日志
"""
    from sqlalchemy import Enum as SaEnum, inspect
    from sqlalchemy.schema import CreateColumn, CreateTable

    dialect = conn.dialect
    is_pg = dialect.name == "postgresql"
    preparer = dialect.identifier_preparer
    q = preparer.quote

    if is_pg:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # 补建缺失的枚举类型（DO block 幂等；新表/新列的建表语句不负责 CREATE TYPE）
        seen_enums: set[str] = set()
        for table in SQLModel.metadata.sorted_tables:
            for col in table.columns:
                if not isinstance(col.type, SaEnum):
                    continue
                name = getattr(col.type, "name", None)
                if not name or name in seen_enums:
                    continue
                seen_enums.add(name)
                labels = ", ".join(f"'{v}'" for v in col.type.enums)
                conn.execute(text(
                    f"DO $enum$ BEGIN CREATE TYPE {q(name)} AS ENUM ({labels}); "
                    f"EXCEPTION WHEN duplicate_object THEN NULL; END $enum$;"
                ))

    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    created_tables: list[str] = []
    added_columns: list[str] = []
    dropped_columns: list[str] = []
    altered_types: list[str] = []
    created_indexes: list[str] = []

    for table in SQLModel.metadata.sorted_tables:
        if table.name not in existing_tables:
            # CreateTable 编译仅生成 CREATE TABLE（枚举已由上方 DO block 保证存在）
            conn.execute(text(str(CreateTable(table).compile(dialect=dialect))))
            for idx in table.indexes:
                ddl = _index_ddl(idx, dialect)
                if ddl:
                    conn.execute(text(ddl))
            created_tables.append(table.name)
            continue

        db_cols = {c["name"]: c for c in inspector.get_columns(table.name)}
        model_cols = {col.name: col for col in table.columns}

        # 1) 新增列
        for col in table.columns:
            if col.name not in db_cols:
                ddl = str(CreateColumn(col).compile(dialect=dialect))
                conn.execute(text(f"ALTER TABLE {q(table.name)} ADD COLUMN {ddl}"))
                added_columns.append(f"{table.name}.{col.name}")

        # 2) 类型变更（仅 PostgreSQL；SQLite 不支持原地改类型）
        if is_pg:
            for col in table.columns:
                info = db_cols.get(col.name)
                if info is None:
                    continue
                try:
                    db_type = str(info["type"].compile(dialect=dialect)).lower().replace(" ", "")
                    model_type = str(col.type.compile(dialect=dialect)).lower().replace(" ", "")
                except Exception:
                    continue  # 无法编译比较的类型（如 VECTOR）跳过
                # PG 中 FLOAT 即 double precision，属同一类型，避免每次启动空转 ALTER
                db_type = db_type.replace("doubleprecision", "float")
                if db_type and model_type and db_type != model_type:
                    new_type = str(col.type.compile(dialect=dialect))
                    conn.execute(text(
                        f"ALTER TABLE {q(table.name)} ALTER COLUMN {q(col.name)} "
                        f"TYPE {new_type} USING {q(col.name)}::text::{new_type}"
                    ))
                    altered_types.append(f"{table.name}.{col.name}: {db_type} -> {model_type}")

        # 3) 删除模型中已移除的列（可经 SCHEMA_SYNC_DROP=false 关闭）
        if settings.schema_sync_drop:
            for name in list(db_cols):
                if name not in model_cols:
                    conn.execute(text(
                        f"ALTER TABLE {q(table.name)} DROP COLUMN {q(name)} CASCADE"
                    ))
                    dropped_columns.append(f"{table.name}.{name}")

        # 4) 缺失索引
        try:
            db_indexes = {i["name"] for i in inspector.get_indexes(table.name)}
        except Exception:
            db_indexes = set()
        for idx in table.indexes:
            if idx.name in db_indexes:
                continue
            ddl = _index_ddl(idx, dialect)
            if ddl is None:
                continue  # HNSW 等 dialect 专属索引在 SQLite 跳过
            conn.execute(text(ddl))
            created_indexes.append(idx.name)

    if created_tables:
        logger.info(f"[schema] 新建表: {', '.join(created_tables)}")
    if added_columns:
        logger.info(f"[schema] 新增列: {', '.join(added_columns)}")
    if altered_types:
        logger.info(f"[schema] 类型变更: {', '.join(altered_types)}")
    if dropped_columns:
        logger.warning(f"[schema] 已删除列: {', '.join(dropped_columns)}")
    if created_indexes:
        logger.info(f"[schema] 新建索引: {', '.join(created_indexes)}")
    if not (created_tables or added_columns or altered_types or dropped_columns or created_indexes):
        logger.info("[schema] 表结构已与模型一致")


def _index_ddl(idx, dialect) -> str | None:
    """编译建索引语句；带 dialect 专属参数（如 hnsw）在不支持的方言上返回 None。"""
    using = idx.dialect_options["postgresql"]["using"]
    if using and dialect.name != "postgresql":
        return None
    preparer = dialect.identifier_preparer
    q = preparer.quote
    cols = ", ".join(q(c.name) for c in idx.columns)
    unique = "UNIQUE " if idx.unique else ""
    if using:
        ops = idx.dialect_options["postgresql"]["ops"] or {}
        col_sql = ", ".join(
            f"{q(c.name)} {ops[c.name]}" if c.name in ops else q(c.name) for c in idx.columns)
        return f"CREATE {unique}INDEX IF NOT EXISTS {q(idx.name)} ON {q(idx.table.name)} USING {using} ({col_sql})"
    return f"CREATE {unique}INDEX IF NOT EXISTS {q(idx.name)} ON {q(idx.table.name)} ({cols})"


async def init_db() -> None:
    """初始化数据库：建表 + 补列补索引（含 pgvector 扩展）+ 默认租户/平台超管/学科字典种子。

表结构以 app/models 为唯一真相，启动时自动对齐：缺失的表整表创建；已有表缺失的列/索引
自动补齐（ADD COLUMN / CREATE INDEX，幂等）。这样客户拉取新代码后重启即可完成升级，
无需手工迁移。列删除与类型变更不做自动处理（避免数据丢失），仅记录告警日志。"""
    async with engine.begin() as conn:
        await conn.run_sync(_sync_schema)

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
