"""平台超管模型 - 独立于学校身份的运营端账号

与学校内 User（教师/主任，受 X-School-Code 多租户管控）彻底隔离：
超管跨租户运营，用于创建/管理学校（租户），不参与学校内业务。
"""
from datetime import datetime
from sqlmodel import SQLModel, Field


class PlatformAdmin(SQLModel, table=True):
    """平台超管"""
    __table_args__ = {"comment": "平台超管"}
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(max_length=50, unique=True, index=True, description="登录名")
    name: str = Field(max_length=50, description="姓名/昵称")
    password_hash: str = Field(max_length=255)
    status: str = Field(default="active", max_length=20, description="active/disabled")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: datetime | None = Field(default=None, description="最后登录时间")