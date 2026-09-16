from datetime import datetime

from sqlmodel import Field, SQLModel

from app.db.base import TenantMixin


class AiMemory(TenantMixin, SQLModel, table=True):
    __tablename__ = "ai_memory"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    type: str = Field(max_length=32, index=True)
    subject: str = Field(max_length=64)
    predicate: str = Field(max_length=64)
    value: str = Field(max_length=1000)
    confidence: float = Field(default=0.8)
    importance: int = Field(default=50)
    status: str = Field(default="active", max_length=20, index=True)
    source_message: str | None = Field(default=None, max_length=4000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
