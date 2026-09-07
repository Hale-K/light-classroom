"""ORM 基础 - 对标 MyBatis-Plus 的 BaseModel + BaseMapper(CRUD)

- TimestampMixin：字段自动填充（created_at/updated_at）
- SoftDeleteMixin：逻辑删除（is_deleted + 查询过滤）
- TenantMixin：多租户（tenant_id 字段，由 session 中间件自动注入）
- BaseRepo：通用 CRUD 基类（对标 BaseMapper，含 select_by_filter 等条件构造）
"""
from datetime import datetime
from typing import Any, Generic, TypeVar, Type
from sqlmodel import SQLModel, Field, select, func
from sqlalchemy import event, inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

T = TypeVar("T", bound=SQLModel)


class TimestampMixin(SQLModel):
    """字段自动填充：created_at / updated_at"""
    created_at: datetime | None = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime | None = Field(default_factory=datetime.utcnow, nullable=False,
                                         sa_column_kwargs={"onupdate": datetime.utcnow})


class SoftDeleteMixin(SQLModel):
    """逻辑删除：is_deleted（查询默认过滤）"""
    is_deleted: bool = Field(default=False, nullable=False, index=True)


class TenantMixin(SQLModel):
    """多租户：tenant_id（由 session 中间件自动注入，不靠业务代码带）"""
    tenant_id: int = Field(default=0, nullable=False, index=True, description="租户 ID（学校）")


# ---------- CRUD 基类（对标 MyBatis-Plus BaseMapper） ----------
class BaseRepo(Generic[T]):
    """通用 CRUD 基类：所有 Repo 继承它，减少样板代码

    - 逻辑删除：模型含 `is_deleted` 列时，查询/分页自动追加 `is_deleted == False`
      过滤；delete() 自动走软删。
    - 条件构造：支持操作符后缀 `field__in` / `field__like` / `field__gt` …
      示例：`select_by_filter(status__in=["done","failed"], name__like="张")`
    - 分页：`page()` 返回 (total, items)。
    """

    model: Type[T]

    def __init__(self, session: AsyncSession):
        self.session = session

    # ---------- 条件构造（对标 QueryWrapper） ----------
    _OPS: dict[str, Any] = {
        "eq": lambda c, v: c == v,
        "ne": lambda c, v: c != v,
        "gt": lambda c, v: c > v,
        "gte": lambda c, v: c >= v,
        "lt": lambda c, v: c < v,
        "lte": lambda c, v: c <= v,
        "like": lambda c, v: c.like(f"%{v}%"),
        "ilike": lambda c, v: c.ilike(f"%{v}%"),  # 大小写不敏感
        "startswith": lambda c, v: c.startswith(v),
        "endswith": lambda c, v: c.endswith(v),
        "in": lambda c, v: c.in_(v),
        "isnull": lambda c, v: c.is_(None) if v else c.is_not(None),
    }

    def _build_stmt(self, filters: dict) -> Any:
        """由 filters 拼 where：普通值走 eq，`field__op` 走指定操作符。"""
        stmt = select(self.model)
        for key, value in filters.items():
            if "__" in key:
                field, op = key.rsplit("__", 1)
            else:
                field, op = key, "eq"
            if not hasattr(self.model, field):
                continue
            col = getattr(self.model, field)
            cond = self._OPS.get(op, lambda c, v: c == v)(col, value)
            stmt = stmt.where(cond)
        return stmt

    def _has_soft_delete(self) -> bool:
        """模型是否含 is_deleted 列（表模型查列，普通模型查 pydantic 字段）。"""
        table = getattr(self.model, "__table__", None)
        if table is not None:
            return "is_deleted" in table.columns
        return "is_deleted" in getattr(self.model, "model_fields", {})

    def _apply_soft_delete(self, stmt) -> Any:
        """逻辑删除自动过滤：模型含 is_deleted 列时默认只查未删除记录。"""
        if self._has_soft_delete():
            stmt = stmt.where(self.model.is_deleted == False)  # noqa: E712
        return stmt

    def _apply_order(self, stmt, order_by: str | None = None, desc: bool = False) -> Any:
        if order_by and hasattr(self.model, order_by):
            col = getattr(self.model, order_by)
            stmt = stmt.order_by(col.desc() if desc else col.asc())
        return stmt

    async def _count(self, stmt) -> int:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        result = await self.session.execute(count_stmt)
        return result.scalar_one()

    # ---------- 基本查询 ----------
    async def get_by_id(self, pk: int) -> T | None:
        obj = await self.session.get(self.model, pk)
        if obj is None or (self._has_soft_delete() and obj.is_deleted):  # type: ignore[attr-defined]
            return None
        return obj

    async def get_one_by_filter(self, **filters: Any) -> T | None:
        """按条件取单条（未命中返回 None）。"""
        stmt = self._apply_soft_delete(self._build_stmt(filters)).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_all(
        self,
        offset: int = 0,
        limit: int = 20,
        order_by: str | None = None,
        desc: bool = False,
    ) -> list[T]:
        """分页列出全部记录（名为 list_all 以免遮蔽内置 list）。"""
        stmt = self._apply_soft_delete(
            self._apply_order(select(self.model), order_by, desc)
        ).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, **filters: Any) -> int:
        stmt = self._apply_soft_delete(self._build_stmt(filters))
        return await self._count(stmt)

    async def page(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        order_by: str | None = None,
        desc: bool = False,
        **filters: Any,
    ) -> tuple[int, list[T]]:
        """分页查询：返回 (总条数, 当前页列表)。page 从 1 起。

        示例：repo.page(1, 10, status="done", name__like="张", order_by="created_at", desc=True)
        """
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        stmt = self._build_stmt(filters)
        total = await self._count(self._apply_soft_delete(stmt))
        stmt = (
            self._apply_soft_delete(self._apply_order(stmt, order_by, desc))
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        result = await self.session.execute(stmt)
        return total, result.scalars().all()

    # ---------- 条件查询 ----------
    async def select_by_filter(
        self,
        order_by: str | None = None,
        desc: bool = False,
        **filters: Any,
    ) -> list[T]:
        """条件构造（对标 QueryWrapper）：传 key=value 自动拼 where，自动加逻辑删除过滤。

        支持操作符后缀：`status__in=[...]`、`name__like=...`、`age__gte=18`、`deleted_at__isnull=True`。
        示例：repo.select_by_filter(name="张三", status__in=["done","failed"], order_by="created_at")
        """
        stmt = self._build_stmt(filters)
        stmt = self._apply_soft_delete(self._apply_order(stmt, order_by, desc))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # ---------- 写操作 ----------
    async def create(self, obj: T) -> T:
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update(self, obj: T) -> T:
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def delete(self, pk: int) -> bool:
        """逻辑删除（若模型含 SoftDeleteMixin）或物理删除"""
        obj = await self.get_by_id(pk)
        if not obj:
            return False
        if self._has_soft_delete():
            obj.is_deleted = True  # type: ignore[attr-defined]
            await self.session.flush()
        else:
            await self.session.delete(obj)
            await self.session.flush()
        return True


# ---------- 全局 updated_at 自动刷新 ----------
# SQLAlchemy 的 onupdate 是列级触发，只在该列自身被赋值时才生效，
# 不会因为同一行其他字段被改而自动刷新。因此用 before_flush 事件
# 全局兜底：所有 TimestampMixin 子类的 dirty 实例在 flush 前自动更新 updated_at。
# 若业务代码显式设置了 updated_at（如补录历史数据），则保留业务值不覆盖。
@event.listens_for(Session, "before_flush")
def _auto_refresh_updated_at(session, context, instances):
    for obj in session.dirty:
        if isinstance(obj, TimestampMixin):
            hist = sa_inspect(obj).attrs.updated_at.history
            if not hist.has_changes():
                obj.updated_at = datetime.utcnow()
