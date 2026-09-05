"""Durable, tenant-scoped assistant conversation memory."""
from datetime import datetime

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.base import TenantMixin


class AiConversation(TenantMixin, SQLModel, table=True):
    __tablename__ = "ai_conversation"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_ai_conversation_tenant_user"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    messages: list[dict] = Field(default_factory=list, sa_type=JSON)
    summary: str = Field(default="", max_length=8000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
