"""RBAC 权限体系六表
role / user_role / permission / role_permission / menu / role_menu
数据范围（三级视角）由关系推导，不在角色层面表达。
"""
from datetime import datetime
from sqlmodel import SQLModel, Field, UniqueConstraint


class Role(SQLModel, table=True):
    """角色表"""
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_role_tenant_code"),
        {"comment": "角色"},
    )
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int | None = Field(default=None, index=True, description="所属学校；空值仅用于兼容历史内置角色")
    code: str = Field(max_length=50, index=True, description="角色编码 teacher/director")
    name: str = Field(max_length=50, description="角色名")
    description: str | None = Field(default=None, max_length=255)


class UserRole(SQLModel, table=True):
    """用户-角色关联（多对多，一用户可多角色）"""
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_userrole_user_role"),
        {"comment": "用户-角色关联"},
    )
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    role_id: int = Field(index=True)


class Permission(SQLModel, table=True):
    """权限点表"""
    __table_args__ = {"comment": "权限点"}
    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(max_length=100, unique=True, index=True,
                      description="如 paper:create / scan:upload / score:write")
    name: str = Field(max_length=50, description="权限名")
    module: str = Field(max_length=50, index=True, description="所属模块")


class RolePermission(SQLModel, table=True):
    """角色-权限关联"""
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_rolepermission_role_perm"),
        {"comment": "角色-权限关联"},
    )
    id: int | None = Field(default=None, primary_key=True)
    role_id: int = Field(index=True)
    permission_id: int = Field(index=True)


class Menu(SQLModel, table=True):
    """菜单表（树形）"""
    __table_args__ = {"comment": "菜单"}
    id: int | None = Field(default=None, primary_key=True)
    parent_id: int | None = Field(default=None, index=True, description="父菜单，树形")
    name: str = Field(max_length=50)
    path: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default=None, max_length=100)
    sort: int = Field(default=0)
    permission_id: int | None = Field(default=None, description="关联权限点，无则默认可见")


class RoleMenu(SQLModel, table=True):
    """角色-菜单关联"""
    __table_args__ = (
        UniqueConstraint("role_id", "menu_id", name="uq_rolemenu_role_menu"),
        {"comment": "角色-菜单关联"},
    )
    id: int | None = Field(default=None, primary_key=True)
    role_id: int = Field(index=True)
    menu_id: int = Field(index=True)
