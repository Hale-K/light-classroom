"""草稿确认域的数据表。"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON
from sqlmodel import Field, SQLModel

from app.db.base import TenantMixin


class AiAction(TenantMixin, SQLModel, table=True):
    """用户确认的不可变规则草稿及执行回执。"""
    __tablename__ = "ai_action"

    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True, max_length=32)
    user_id: int = Field(index=True)
    status: str = Field(default="pending", max_length=20)
    payload: dict = Field(sa_type=JSON)
    result: dict | None = Field(default=None, sa_type=JSON)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
