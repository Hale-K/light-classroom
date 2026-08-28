"""A2/A3 验证：种子租户 + school_code→tenant 解析 + 查询过滤注入"""
import asyncio
from sqlalchemy import select, event
from app.db.session import init_db, get_session, tenant_id_ctx, engine
from app.services.tenant import resolve_tenant_id
from app.models.org import Student
from app.models.exam import Exam

captured: list[str] = []
@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _cap(conn, cursor, statement, parameters, context, executemany):
    if statement.startswith("SELECT FROM student") or statement.startswith("SELECT FROM exam") \
       or "FROM student" in statement or "FROM exam" in statement:
        captured.append(statement)


async def main():
    await init_db()
    tid = await resolve_tenant_id("demo")
    print(f"[1] demo -> tenant_id={tid}")
    assert tid is not None, "默认租户种子失败"
    print(f"[2] no_such_school -> {await resolve_tenant_id('no_such_school')}")

    async for session in get_session():
        tenant_id_ctx.set(tid)
        await session.execute(select(Student).limit(5))
        await session.execute(select(Exam).limit(5))
        tenant_id_ctx.set(None)
        await session.execute(select(Student).limit(5))  # 不应注入

    injected = lambda s: "tenant_id =" in s  # WHERE 注入条件（区别于 SELECT 列名）
    student_sql = [s for s in captured if "FROM student" in s]
    exam_sql = [s for s in captured if "FROM exam" in s]
    print("[3] student with-tenant:", student_sql and student_sql[0])
    assert any(injected(s) for s in student_sql), "Student 未注入"
    assert any(injected(s) for s in exam_sql), "Exam 未注入"
    assert any(not injected(s) for s in student_sql), "无上下文仍被注入"
    print("✅ 多租户解析+注入验证通过")


if __name__ == "__main__":
    asyncio.run(main())