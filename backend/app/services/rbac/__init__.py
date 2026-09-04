"""RBAC 领域服务包

分组：
- seed：新环境空库初始化数据
- catalog：权限点目录
- roles：角色 / 成员 / 角色权限
- menu：侧栏菜单结构与可见权限映射
"""

from app.services.rbac.catalog import (
    create_permission,
    delete_permission,
    ensure_permission_schema,
    ensure_permissions,
    list_permissions,
    update_permission,
)
from app.services.rbac.menu import (
    DEFAULT_MENU_PERMISSIONS,
    MENU_PERMISSIONS,
    build_menu,
    create_menu,
    delete_menu,
    ensure_menu_permissions,
    ensure_menu_schema,
    ensure_menus,
    list_menu_permission_bindings,
    load_menu_permission_map,
    load_menus,
    preview_menu_by_permissions,
    seed_menu_items,
    set_menu_permissions,
    update_menu,
)
from app.services.rbac.roles import (
    BUILTIN_ROLE_CODES,
    create_role,
    delete_role,
    ensure_builtin_roles,
    list_role_members,
    list_role_permissions,
    list_roles,
    role_belongs_to_tenant,
    role_by_code,
    set_role_members,
    set_role_permissions,
    update_role,
)
from app.services.rbac.seed import (
    BUILTIN_ROLE_PERMISSION_SEED,
    BUILTIN_ROLE_SEED,
    MENU_PERMISSION_SEED,
    MENU_SEED,
    PERMISSION_SEED,
)

__all__ = [
    "BUILTIN_ROLE_CODES",
    "BUILTIN_ROLE_PERMISSION_SEED",
    "BUILTIN_ROLE_SEED",
    "DEFAULT_MENU_PERMISSIONS",
    "MENU_PERMISSIONS",
    "MENU_PERMISSION_SEED",
    "MENU_SEED",
    "PERMISSION_SEED",
    "build_menu",
    "create_menu",
    "create_permission",
    "create_role",
    "delete_menu",
    "delete_permission",
    "delete_role",
    "ensure_builtin_roles",
    "ensure_menu_permissions",
    "ensure_menu_schema",
    "ensure_menus",
    "ensure_permission_schema",
    "ensure_permissions",
    "list_menu_permission_bindings",
    "list_permissions",
    "list_role_members",
    "list_role_permissions",
    "list_roles",
    "load_menu_permission_map",
    "load_menus",
    "preview_menu_by_permissions",
    "role_belongs_to_tenant",
    "role_by_code",
    "seed_menu_items",
    "set_menu_permissions",
    "set_role_members",
    "set_role_permissions",
    "update_menu",
    "update_permission",
    "update_role",
]
