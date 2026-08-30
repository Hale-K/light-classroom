"""菜单目录服务 - 菜单单一真源 + 按用户角色工厂构建树

设计说明：
- MENU_CATALOG 在此集中定义（产品菜单清单，含是否开放、可见角色），后端作为菜单来源，
  前端只负责渲染本文返回的树。
- build_menu() 以"工厂"方式产出当前用户的菜单树：available=False 的节点前端渲染为
  "待开放"占位（仍下发，保证视觉一致），不直接暴露到路由导航。
- 未来接 RBAC 角色-菜单表后，可将本目录迁移为 DB 持久化，接口签名不变。
"""
from typing import Any

from app.services.gaokao import get_subject_choice_strategy


class _MenuCat:
    """阈值/元数据封装：定义单个菜单项目录配置"""

    def __init__(
        self,
        key: str,
        title: str,
        icon: str,
        path: str | None,
        enabled: bool = True,
        roles: list[str] | None = None,
        required_capability: str | None = None,
    ):
        self.key = key
        self.title = title
        self.icon = icon
        self.path = path
        self.enabled = enabled          # 产品是否已开放
        self.roles = roles or []        # 空 = 所有基础角色可见
        self.required_capability = required_capability

    def visible_to(self, role: str, capabilities: frozenset[str]) -> bool:
        role_visible = not self.roles or role in self.roles
        capability_visible = not self.required_capability or self.required_capability in capabilities
        return self.enabled and role_visible and capability_visible


# 产品菜单清单（排序即目录顺序）
MENU_CATALOG: list[_MenuCat] = [
    _MenuCat("dashboard",  "工作台",         "dashboard",  "/dashboard"),
    _MenuCat("exams",      "试卷库",         "book",       "/exams"),
    _MenuCat("scans",      "扫描进卷",       "scan",       "/scans"),
    _MenuCat("scheduling", "排课管理",       "calendar",   "/scheduling", roles=["director", "academic_director"]),
    _MenuCat(
        "gaokao", "学生选课", "git-branch", "/gaokao",
        roles=["director", "academic_director"], required_capability="walk_class",
    ),
    _MenuCat(
        "stream-choice", "文理分科", "git-branch", "/gaokao",
        roles=["director", "academic_director"], required_capability="stream_choice",
    ),
    _MenuCat("exam-scheduling", "排考管理",  "clipboard",  "/exam-scheduling", roles=["director", "academic_director"]),
    _MenuCat("seating",    "班级排座",       "grid",       "/seating"),
    _MenuCat("students",   "学生档案",       "user",       "/students"),
    _MenuCat("teacher-profiles", "教师档案", "users",    "/teacher-profiles"),
    _MenuCat("classes",    "行政班管理",     "grid",       "/classes", roles=["director", "academic_director"]),
    _MenuCat("organization", "组织机构",     "sitemap",    "/organization", roles=["director"]),
    _MenuCat("facilities", "空间资源", "building", "/campus-buildings", roles=["director", "academic_director"]),
    _MenuCat("staff-accounts", "人员账号",   "users",      "/staff", roles=["director"]),
    _MenuCat("roles",         "角色管理",     "id-badge",   "/roles", roles=["director"]),
    _MenuCat("permissions",   "权限管理",     "shield",     "/permissions", roles=["director"]),
    _MenuCat("meetings", "会议管理", "message", "/meetings", roles=["director", "academic_director"]),
    _MenuCat("chart",      "学情分析",       "chart",      None, enabled=False),
    _MenuCat("practice",   "巩固训练",       "book",       None, enabled=False),
    _MenuCat("ai",         "AI 押题",        "sparkles",   None, enabled=False),
    _MenuCat("settings",   "系统设置",       "settings",   "/settings", roles=["director"]),
    _MenuCat("subjects",   "科目管理",       "book",       "/subjects", roles=["director", "academic_director"]),
]

MENU_GROUPS = (
    ("overview", "工作台", ("dashboard",)),
    ("school", "学校管理", ("settings", "subjects")),
    ("staffing", "人员配置", ("staff-accounts", "roles", "permissions")),
    ("resources", "资源管理", ("facilities",)),
    ("enrollment", "学籍管理", ("students", "teacher-profiles", "classes")),
    ("placement", "选科走班", ("gaokao", "stream-choice")),
    ("teaching", "教学安排", ("scheduling", "seating")),
    ("exams", "考试实施", ("exams", "exam-scheduling", "scans")),
    ("collaboration", "协同办公", ("meetings",)),
)

MENU_GROUP_ICONS = {
    "overview": "dashboard",
    "school": "school",
    "staffing": "users",
    "enrollment": "file-text",
    "placement": "git-branch",
    "teaching": "book",
    "exams": "clipboard",
    "collaboration": "message",
    "resources": "building",
}

MENU_PERMISSIONS: dict[str, set[str]] = {
    "dashboard": {"dashboard:view"},
    "exams": {"paper:view", "exam:view"},
    "scans": {"scan:view"},
    "scheduling": {"scheduling:view"},
    "gaokao": {"gaokao:view"},
    "stream-choice": {"gaokao:view"},
    "exam-scheduling": {"exam:view"},
    "seating": {"seating:view"},
    "students": {"students:view"},
    "teacher-profiles": {"teacher_profiles:view"},
    "classes": {"classes:view"},
    "organization": {"organization:view"},
    "facilities": {"facilities:view"},
    "subjects": {"scheduling:assign"},
    "staff-accounts": {"staff:view"},
    "roles": {"rbac:manage"},
    "permissions": {"rbac:manage"},
    "meetings": {"meetings:view"},
}


def build_menu(
    role: str,
    gaokao_mode: str = "3+1+2",
    permission_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return usable items in the order the school's core business is performed."""
    capabilities = get_subject_choice_strategy(gaokao_mode).capabilities

    def is_visible(item: _MenuCat) -> bool:
        if not item.enabled or not item.path:
            return False
        if item.required_capability and item.required_capability not in capabilities:
            return False
        if permission_codes is None or role == "director":
            return item.visible_to(role, capabilities)
        required = MENU_PERMISSIONS.get(item.key)
        if required is not None:
            return bool(required & permission_codes)
        return not item.roles or role in item.roles

    visible_items = {
        c.key: {
            "key": c.key,
            "title": c.title,
            "icon": c.icon,
            "path": c.path,
            "available": True,
            "children": [],
        }
        for c in MENU_CATALOG
        if is_visible(c)
    }
    groups = []
    for key, title, item_keys in MENU_GROUPS:
        children = [visible_items[item_key] for item_key in item_keys if item_key in visible_items]
        if children:
            groups.append({
                "key": key,
                "title": title,
                "icon": MENU_GROUP_ICONS[key],
                "path": None,
                "available": True,
                "children": children,
            })
    return groups
