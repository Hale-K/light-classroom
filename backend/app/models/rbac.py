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
    """权限点表（运行时目录以本表为准）"""
    __table_args__ = (
        UniqueConstraint("code", name="uq_permission_code"),
        {"comment": "权限点"},
    )
    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(max_length=100, index=True,
                      description="如 scheduling:view / exam:manage")
    name: str = Field(max_length=50, description="权限名")
    module: str = Field(max_length=50, index=True, description="所属模块")
    sort: int = Field(default=0, description="模块内排序")


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
    """侧栏菜单项（结构以本表为准；可见权限见 menu_permission）"""
    __table_args__ = (
        UniqueConstraint("key", name="uq_menu_key"),
        {"comment": "菜单"},
    )
    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(max_length=50, index=True, description="稳定编码，如 dashboard / rbac")
    parent_id: int | None = Field(default=None, index=True, description="兼容旧字段，可空")
    name: str = Field(max_length=50)
    path: str | None = Field(default=None, max_length=200)
    icon: str | None = Field(default=None, max_length=100)
    sort: int = Field(default=0)
    enabled: bool = Field(default=True, description="产品是否开放")
    roles_csv: str = Field(default="", max_length=255, description="基础角色白名单，逗号分隔；空=不限")
    required_capability: str | None = Field(default=None, max_length=50)
    group_key: str = Field(default="other", max_length=50, index=True)
    group_title: str = Field(default="其他", max_length=50)
    group_icon: str = Field(default="grid", max_length=50)
    group_sort: int = Field(default=100)
    permission_id: int | None = Field(default=None, description="旧字段，已由 menu_permission 取代")


class MenuPermission(SQLModel, table=True):
    """菜单可见性所需权限点（多对多；满足任一即可显示）"""
    __tablename__ = "menu_permission"
    __table_args__ = (
        UniqueConstraint("menu_key", "permission_id", name="uq_menu_permission_key_perm"),
        {"comment": "菜单-权限点映射"},
    )
    id: int | None = Field(default=None, primary_key=True)
    menu_key: str = Field(max_length=50, index=True, description="对应 MENU_CATALOG.key")
    permission_id: int = Field(index=True, description="permission.id")
