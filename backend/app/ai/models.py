"""租户级大模型服务商配置。"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON
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


class AiRun(TenantMixin, SQLModel, table=True):
    """可恢复查看的助手请求；执行器中断后明确标记，绝不自动重放写操作。"""
    __tablename__ = "ai_run"
    id: str = Field(primary_key=True, max_length=32)
    user_id: int = Field(index=True)
    request_hash: str = Field(max_length=64)
    status: str = Field(default="running", max_length=20)
    phase: str = Field(default="received", max_length=30)
    message: str = Field(default="已收到，正在准备处理", max_length=300)
    events: list[dict] = Field(default_factory=list, sa_type=JSON)
    result: dict | None = Field(default=None, sa_type=JSON)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    phase_started_at: datetime = Field(default_factory=datetime.utcnow)
