"""seed permission/menu/menu_permission catalog data from former rbac_seed

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE permission ADD COLUMN IF NOT EXISTS sort INTEGER NOT NULL DEFAULT 0"))
    for stmt in [
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS key VARCHAR(50)",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS roles_csv VARCHAR(255) NOT NULL DEFAULT ''",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS required_capability VARCHAR(50)",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS group_key VARCHAR(50) NOT NULL DEFAULT 'other'",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS group_title VARCHAR(50) NOT NULL DEFAULT '其他'",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS group_icon VARCHAR(50) NOT NULL DEFAULT 'grid'",
        "ALTER TABLE menu ADD COLUMN IF NOT EXISTS group_sort INTEGER NOT NULL DEFAULT 100",
    ]:
        conn.execute(sa.text(stmt))

    # ---- permission ----
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('dashboard:view', '查看工作台', '工作台', 0) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('paper:view', '查看试卷', '试卷库', 1) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('paper:write', '新建/编辑试卷', '试卷库', 2) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('paper:publish', '发布试卷', '试卷库', 3) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('paper:delete', '删除试卷', '试卷库', 4) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('scan:view', '查看扫描批次', '扫描进卷', 5) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('scan:upload', '上传扫描件', '扫描进卷', 6) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('scan:process', '切分/分配/确认批次', '扫描进卷', 7) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('scheduling:view', '查看课表与任教关系', '排课管理', 8) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('scheduling:assign', '配置任教关系', '排课管理', 9) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('scheduling:generate', '生成课表', '排课管理', 10) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('seating:view', '查看座位表', '班级排座', 11) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('seating:manage', '建立规则并生成座位', '班级排座', 12) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('gaokao:view', '查看选科分布', '选科走班', 13) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('gaokao:manage', '生成教学班/课表', '选科走班', 14) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('students:view', '查看学生名册', '学生档案', 15) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('students:manage', '新增/编辑/删除学生', '学生档案', 16) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('teacher_profiles:view', '查看教师档案', '教师档案', 17) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('classes:view', '查看班级与名单', '行政班管理', 18) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('classes:manage', '调整班级与排座', '行政班管理', 19) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('exam:view', '查看考试与场次', '考试管理', 20) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('exam:manage', '新建/编排考试', '考试管理', 21) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('grading:view', '查看作答与成绩', '打分阅卷', 22) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('grading:write', '录入/修改成绩', '打分阅卷', 23) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('organization:view', '查看组织架构', '组织机构', 24) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('organization:manage', '维护组织与任命', '组织机构', 25) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('facilities:view', '查看空间资源', '空间资源', 26) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('facilities:manage', '维护空间资源', '空间资源', 27) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('staff:view', '查看人员账号', '人员与权限', 28) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('staff:manage', '管理账号与状态', '人员与权限', 29) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('rbac:manage', '管理角色与权限', '人员与权限', 30) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('meetings:view', '查看会议', '会议管理', 31) ON CONFLICT (code) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO permission (code, name, module, sort) VALUES ('meetings:manage', '新建/编辑会议', '会议管理', 32) ON CONFLICT (code) DO NOTHING"))

    # ---- menu ----
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('dashboard', '工作台', '/dashboard', 'dashboard', 10, TRUE, '', NULL, 'overview', '工作台', 'dashboard', 10) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('settings', '系统设置', '/settings', 'settings', 10, TRUE, 'director', NULL, 'school', '学校管理', 'school', 20) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('subjects', '科目管理', '/subjects', 'book', 20, TRUE, 'director,academic_director', NULL, 'school', '学校管理', 'school', 20) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('staff-accounts', '人员账号', '/staff', 'users', 10, TRUE, 'director', NULL, 'staffing', '人员配置', 'users', 30) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('rbac', '角色与权限', '/rbac', 'shield', 20, TRUE, 'director', NULL, 'staffing', '人员配置', 'users', 30) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('facilities', '空间资源', '/campus-buildings', 'building', 10, TRUE, 'director,academic_director', NULL, 'resources', '资源管理', 'building', 40) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('students', '学生档案', '/students', 'user', 10, TRUE, '', NULL, 'enrollment', '学籍管理', 'file-text', 50) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('teacher-profiles', '教师档案', '/teacher-profiles', 'users', 20, TRUE, '', NULL, 'enrollment', '学籍管理', 'file-text', 50) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('classes', '行政班管理', '/classes', 'grid', 30, TRUE, 'director,academic_director', NULL, 'enrollment', '学籍管理', 'file-text', 50) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('gaokao', '学生选课', '/gaokao', 'git-branch', 10, TRUE, 'director,academic_director', 'walk_class', 'placement', '选科走班', 'git-branch', 60) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('stream-choice', '文理分科', '/gaokao', 'git-branch', 20, TRUE, 'director,academic_director', 'stream_choice', 'placement', '选科走班', 'git-branch', 60) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('scheduling', '排课管理', '/scheduling', 'calendar', 10, TRUE, 'director,academic_director', NULL, 'teaching', '教学安排', 'book', 70) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('seating', '班级排座', '/seating', 'grid', 20, TRUE, '', NULL, 'teaching', '教学安排', 'book', 70) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('exams', '试卷库', '/exams', 'book', 10, TRUE, '', NULL, 'exams', '考试实施', 'clipboard', 80) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('exam-scheduling', '排考管理', '/exam-scheduling', 'clipboard', 20, TRUE, 'director,academic_director', NULL, 'exams', '考试实施', 'clipboard', 80) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('scans', '扫描进卷', '/scans', 'scan', 30, TRUE, '', NULL, 'exams', '考试实施', 'clipboard', 80) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('meetings', '会议管理', '/meetings', 'message', 10, TRUE, 'director,academic_director', NULL, 'collaboration', '协同办公', 'message', 90) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('chart', '学情分析', NULL, 'chart', 10, FALSE, '', NULL, 'future', '待开放', 'sparkles', 100) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('practice', '巩固训练', NULL, 'book', 20, FALSE, '', NULL, 'future', '待开放', 'sparkles', 100) ON CONFLICT (key) DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, required_capability, group_key, group_title, group_icon, group_sort) VALUES ('ai', 'AI 押题', NULL, 'sparkles', 30, FALSE, '', NULL, 'future', '待开放', 'sparkles', 100) ON CONFLICT (key) DO NOTHING"))

    # ---- menu_permission ----
    conn.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS menu_permission (
        id SERIAL PRIMARY KEY,
        menu_key VARCHAR(50) NOT NULL,
        permission_id INTEGER NOT NULL,
        CONSTRAINT uq_menu_permission_key_perm UNIQUE (menu_key, permission_id)
    )"""
    ))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'dashboard', p.id FROM permission p WHERE p.code = 'dashboard:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'exams', p.id FROM permission p WHERE p.code = 'exam:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'exams', p.id FROM permission p WHERE p.code = 'paper:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'scans', p.id FROM permission p WHERE p.code = 'scan:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'scheduling', p.id FROM permission p WHERE p.code = 'scheduling:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'gaokao', p.id FROM permission p WHERE p.code = 'gaokao:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'stream-choice', p.id FROM permission p WHERE p.code = 'gaokao:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'exam-scheduling', p.id FROM permission p WHERE p.code = 'exam:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'seating', p.id FROM permission p WHERE p.code = 'seating:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'students', p.id FROM permission p WHERE p.code = 'students:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'teacher-profiles', p.id FROM permission p WHERE p.code = 'teacher_profiles:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'classes', p.id FROM permission p WHERE p.code = 'classes:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'organization', p.id FROM permission p WHERE p.code = 'organization:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'facilities', p.id FROM permission p WHERE p.code = 'facilities:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'subjects', p.id FROM permission p WHERE p.code = 'scheduling:assign' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'staff-accounts', p.id FROM permission p WHERE p.code = 'staff:view' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'rbac', p.id FROM permission p WHERE p.code = 'rbac:manage' ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO menu_permission (menu_key, permission_id) SELECT 'meetings', p.id FROM permission p WHERE p.code = 'meetings:view' ON CONFLICT DO NOTHING"))

    # ---- builtin role permission templates ----
    conn.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS rbac_role_permission_template (
        role_code VARCHAR(50) NOT NULL,
        permission_code VARCHAR(100) NOT NULL,
        PRIMARY KEY (role_code, permission_code)
    )"""
    ))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'dashboard:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'paper:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'paper:write') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'paper:publish') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'paper:delete') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'scan:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'scan:upload') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'scan:process') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'scheduling:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'scheduling:assign') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'scheduling:generate') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'seating:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'seating:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'gaokao:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'gaokao:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'students:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'students:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'teacher_profiles:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'classes:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'classes:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'exam:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'exam:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'grading:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'grading:write') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'organization:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'organization:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'facilities:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'facilities:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'staff:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'staff:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'rbac:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'meetings:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('school_admin', 'meetings:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'classes:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'classes:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'dashboard:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'exam:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'exam:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'facilities:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'facilities:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'gaokao:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'gaokao:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'grading:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'grading:write') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'meetings:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'meetings:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'organization:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'scan:process') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'scan:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'scheduling:assign') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'scheduling:generate') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'scheduling:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'seating:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'seating:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'students:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('academic_director', 'teacher_profiles:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('head_teacher', 'classes:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('head_teacher', 'dashboard:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('head_teacher', 'exam:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('head_teacher', 'grading:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('head_teacher', 'meetings:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('head_teacher', 'scan:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('head_teacher', 'seating:manage') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('head_teacher', 'seating:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('head_teacher', 'students:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('head_teacher', 'teacher_profiles:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('subject_teacher', 'dashboard:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('subject_teacher', 'exam:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('subject_teacher', 'grading:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('subject_teacher', 'grading:write') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('subject_teacher', 'paper:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('subject_teacher', 'paper:write') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('subject_teacher', 'scan:upload') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('subject_teacher', 'scan:view') ON CONFLICT DO NOTHING"))
    conn.execute(sa.text("INSERT INTO rbac_role_permission_template (role_code, permission_code) VALUES ('subject_teacher', 'students:view') ON CONFLICT DO NOTHING"))


def downgrade() -> None:
    # 不回滚业务配置数据
    pass
