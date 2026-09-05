"""租户级大模型服务商配置表（ChatModel 域）。"""
from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.db.base import TenantMixin, TimestampMixin


class AiProvider(TimestampMixin, TenantMixin, SQLModel, table=True):
    __tablename__ = "ai_provider"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_ai_provider_tenant_name"),
        {"comment": "大模型服务商"},
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=80)
    provider_type: str = Field(default="OPENAI", max_length=32, index=True)
    base_url: str = Field(max_length=300)
    api_key: str = Field(default="", max_length=512)
    chat_model: str | None = Field(default=None, max_length=120)
    vision_model: str | None = Field(default=None, max_length=120)
    image_model: str | None = Field(default=None, max_length=120)
    video_model: str | None = Field(default=None, max_length=120)
    audio_model: str | None = Field(default=None, max_length=120)
    timeout_seconds: int = Field(default=120)
    is_default: bool = Field(default=False, index=True)
    status: int = Field(default=1, index=True, description="1 启用 0 停用")
    sort: int = Field(default=0)
    remark: str | None = Field(default=None, max_length=200)
    last_test_status: int | None = Field(default=None, description="1 通 0 不通")
    last_test_at: datetime | None = Field(default=None)
