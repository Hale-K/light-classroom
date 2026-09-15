-- 教师工作台默认菜单备份（2026-09-07）
-- 执行前请确认当前数据库已完成备份；重复执行不会产生重复菜单。

UPDATE menu SET enabled = TRUE, roles_csv = 'teacher', group_key = 'teacher-workbench',
    group_title = '教师工作台', group_icon = 'school', group_sort = 5
WHERE key IN ('teacher-courses', 'teacher-preparation', 'teacher-homework', 'teacher-grades',
               'teacher-students', 'teacher-classes', 'teacher-research', 'teacher-notices');

UPDATE menu SET path = '/teacher-courses' WHERE key = 'teacher-courses';

DELETE FROM menu_permission WHERE menu_key = 'teacher-home';
DELETE FROM menu WHERE key = 'teacher-home';

INSERT INTO permission (module, name, code, sort)
SELECT v.module, v.name, v.code, v.sort
FROM (VALUES
    ('教师工作台', '课程菜单', 'teacher_menu:courses', 10),
    ('教师工作台', '备课菜单', 'teacher_menu:preparation', 20),
    ('教师工作台', '作业菜单', 'teacher_menu:homework', 30),
    ('教师工作台', '成绩菜单', 'teacher_menu:grades', 40),
    ('教师工作台', '学生菜单', 'teacher_menu:students', 50),
    ('教师工作台', '班级菜单', 'teacher_menu:classes', 60),
    ('教师工作台', '教研菜单', 'teacher_menu:research', 70),
    ('教师工作台', '通知菜单', 'teacher_menu:notices', 80)
) AS v(module, name, code, sort)
WHERE NOT EXISTS (SELECT 1 FROM permission p WHERE p.code = v.code);

DELETE FROM menu_permission
WHERE menu_key IN ('teacher-courses', 'teacher-preparation', 'teacher-homework', 'teacher-grades',
                   'teacher-students', 'teacher-classes', 'teacher-research', 'teacher-notices');

INSERT INTO menu_permission (menu_key, permission_id)
SELECT v.menu_key, p.id
FROM (VALUES
    ('teacher-courses', 'teacher_menu:courses'),
    ('teacher-preparation', 'teacher_menu:preparation'),
    ('teacher-homework', 'teacher_menu:homework'),
    ('teacher-grades', 'teacher_menu:grades'),
    ('teacher-students', 'teacher_menu:students'),
    ('teacher-classes', 'teacher_menu:classes'),
    ('teacher-research', 'teacher_menu:research'),
    ('teacher-notices', 'teacher_menu:notices')
) AS v(menu_key, permission_code)
JOIN permission p ON p.code = v.permission_code;

-- 回滚“首页”菜单（需要时执行）
-- INSERT INTO menu (key, name, path, icon, sort, enabled, roles_csv, group_key, group_title, group_icon, group_sort)
-- VALUES ('teacher-home', '首页', '/dashboard', 'home', 10, TRUE, 'teacher', 'teacher-workbench', '教师工作台', 'school', 5);
