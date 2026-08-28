"""A7 BaseRepo 增强验证（分页 / 条件构造**操作符 / 逻辑删除过滤）"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import SQLModel, Field, select
from app.db.session import AsyncSessionLocal
from app.db.base import BaseRepo, SoftDeleteMixin
from app.models.org import Student


class SoftRow(SoftDeleteMixin, SQLModel):
    """仅用于测试软删过滤的临时模型（非表）"""
    name: str = Field(max_length=50)


class StudentRepo(BaseRepo[Student]):
    model = Student


class SoftRepo(BaseRepo[SoftRow]):
    model = SoftRow


async def main():
    async with AsyncSessionLocal() as session:
        repo = StudentRepo(session)

        # 1) 逻辑删除默认过滤——用含 SoftDeleteMixin 的临时模型验证
        soft_repo = SoftRepo(session)
        assert soft_repo._has_soft_delete(), "SoftRow 应检测到 is_deleted"
        assert not repo._has_soft_delete(), "Student 不应判定为软删"
        print("[ok] 软删检测：SoftRow=True, Student=False")

        # 2) 无软删模型的查询不受影响（Student 无 is_deleted 也能正常 page）
        total, items = await repo.page(1, 10, order_by="id", desc=True)
        print(f"[ok] page(无软删模型) total={total} items={len(items)}")

        # 3) 条件构造操作符（惰性，仅检查 SQL 片段）
        stmt = repo._build_stmt({"name__like": "张", "id__in": [1, 2]})
        sql = str(stmt)
        assert "LIKE" in sql.upper() or "like" in sql, sql
        print("[ok] 条件构造操作符:", sql[:150])

        # 4) count + get_one_by_filter
        c = await repo.count()
        one = await repo.get_one_by_filter()
        print(f"[ok] count={c} get_one_by_filter -> {'None' if one is None else type(one).__name__}")

    print("\nA7 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())