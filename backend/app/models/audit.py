"""基础设施模型
audit_log
"""
from datetime import datetime
from typing import Any
from sqlmodel import SQLModel, Field
from sqlalchemy import JSON

from app.db.base import TenantMixin


class AuditLog(TenantMixin, SQLModel, table=True):
    """审计日志"""
    __table_args__ = {"comment": "审计日志"}
    id: int | None = Field(default=None, primary_key=True)
    user_id: int | None = Field(default=None, index=True, description="谁")
    action: str = Field(max_length=100, description="操作")
    resource: str | None = Field(default=None, max_length=100, description="资源")
    resource_id: int | None = Field(default=None)
    old_value: dict | None = Field(default=None, sa_type=JSON, description="原值")
    new_value: dict | None = Field(default=None, sa_type=JSON, description="新值")
    ip: str | None = Field(default=None, max_length=50)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)