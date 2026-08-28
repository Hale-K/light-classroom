"""初始化数据库：建库 + 建表
用法：DATABASE_URL=... python scripts/init_db.py
仅在开发期使用（生产走 Alembic 迁移）。
"""
import asyncio
import os

import psycopg2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  注册全部表模型
from sqlmodel import SQLModel

# 解析 DATABASE_URL 用于建库（asyncpg 连接串 → psycopg2 连接参数）
db_url = os.environ["DATABASE_URL"]
# postgresql+asyncpg://user:pass@host:port/db
body = db_url.split("://", 1)[1]
userinfo, rest = body.split("@")
user, pw = userinfo.split(":")
hostport, dbname = rest.split("/", 1)


def create_database() -> None:
    host, port = hostport.rsplit(":", 1)
    conn = psycopg2.connect(host=host, port=port, user=user, password=pw, dbname="postgres")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{dbname}"')
            print(f"DB {dbname} created")
        else:
            print(f"DB {dbname} already exists")
    conn.close()


async def create_tables() -> None:
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # 检查实际表数量
        rs = await conn.execute(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        )
        print(f"Tables created: {rs.scalar()}")
    await engine.dispose()


if __name__ == "__main__":
    create_database()
    asyncio.run(create_tables())
    print("init done")