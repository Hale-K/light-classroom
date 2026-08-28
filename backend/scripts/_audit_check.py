"""临时：检查 auditlog 最近记录（A5 验证）"""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text
from app.db.session import engine


async def main():
    async with engine.connect() as c:
        r = await c.execute(text(
            "select id,user_id,action,resource,ip,created_at from auditlog order by id desc limit 5"))
        rows = r.fetchall()
        if not rows:
            print("auditlog 为空")
        for row in rows:
            print(tuple(row))


asyncio.run(main())