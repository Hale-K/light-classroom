"""助手任务域的数据表。"""
from datetime import datetime

from sqlalchemy import JSON
from sqlmodel import Field, SQLModel

from app.db.base import TenantMixin


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
