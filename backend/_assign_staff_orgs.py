"""
给 tenant=3（广东新高考实验中学）分配老师的组织架构：
A. 建 organizationunit 节点树（匹配截图）
B. 建 staffappointment：每位老师→对应组织+岗位（按姓名模式匹配）
C. 同步 class.head_teacher_id：将班主任名字对应到班级
D. 补 userrole：每位 teacher 用户自动关联“任教老师”角色，director 关联 school_admin
E. 建 teachingassignment：给每位老师生成合理的任教关系（对应 tenant=3 的班级）

所有操作幂等：先查后插，避免重复执行时主键冲突。
"""
import asyncio
import re
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://postgres:123456@localhost:5432/zhiheng"
TENANT_ID = 3
AY = "2026-2027"
TERM = "1"


ORG_TREE = [
    # (name, unit_type, parent_path_tail, academic_year?, cohort_label?, sort_order)
    ("校级管理", "department", None, None, None, 10),
    ("教务处", "department", None, None, None, 20),
    ("年级管理中心", "department", "教务处", None, None, 10),
    ("2029届高一年级部", "grade_group", "年级管理中心", AY, "2029届", 1),
    ("2028届高二年级部", "grade_group", "年级管理中心", AY, "2028届", 2),
    ("2027届高三年级部", "grade_group", "年级管理中心", AY, "2027届", 3),
    ("学科教研中心", "department", "教务处", None, None, 20),
    ("语文教研组", "subject_group", "学科教研中心", None, None, 1),
    ("数学教研组", "subject_group", "学科教研中心", None, None, 2),
    ("英语教研组", "subject_group", "学科教研中心", None, None, 3),
    ("物理教研组", "subject_group", "学科教研中心", None, None, 4),
    ("化学教研组", "subject_group", "学科教研中心", None, None, 5),
    ("生物教研组", "subject_group", "学科教研中心", None, None, 6),
    ("政治教研组", "subject_group", "学科教研中心", None, None, 7),
    ("历史教研组", "subject_group", "学科教研中心", None, None, 8),
    ("地理教研组", "subject_group", "学科教研中心", None, None, 9),
    ("体育教研组", "subject_group", "学科教研中心", None, None, 10),
    ("德育处", "department", None, None, None, 30),
]


GRADE_KEYWORD_TO_INFO = {
    "高一": {"label": "2029届高一年级部", "level": 1},
    "高二": {"label": "2028届高二年级部", "level": 2},
    "高三": {"label": "2027届高三年级部", "level": 3},
}

SUBJECT_KEYWORD_TO_SUBJECT = {
    "语文":   "语文教研组",
    "数学":   "数学教研组",
    "英语":   "英语教研组",
    "物理":   "物理教研组",
    "化学":   "化学教研组",
    "生物":   "生物教研组",
    "政治":   "政治教研组",
    "历史":   "历史教研组",
    "地理":   "地理教研组",
    "体育":   "体育教研组",
}


def parse_teacher_name(name: str):
    """从姓名如「高一语文班主任01」「高一地理任课教师02」「高一地理补充教师01」解析出年级、学科、身份"""
    m = re.match(r"(高一|高二|高三)?(语文|数学|英语|物理|化学|生物|政治|历史|地理|体育)?(班主任|任课教师|补充教师)?(\d+)?", name)
    if not m:
        return None, None, None
    return m.group(1), m.group(2), m.group(3)


async def upsert_org_units(conn):
    """创建/查找组织节点，返回 name -> id"""
    rows = (await conn.execute(text(f"""
        SELECT id, name, parent_id FROM organizationunit WHERE tenant_id = {TENANT_ID}
    """))).mappings().all()
    by_name = {}
    by_id_parent = {}
    for r in rows:
        by_name[r['name']] = r['id']
        by_id_parent[r['id']] = r['parent_id']

    for name, unit_type, parent_name, ay, cohort, sort_order in ORG_TREE:
        if name in by_name:
            continue
        pid_sql = "NULL"
        if parent_name:
            if parent_name not in by_name:
                raise RuntimeError(f"父节点 {parent_name} 还没建，顺序错了")
            pid_sql = str(by_name[parent_name])
        ay_sql = f"'{ay}'" if ay else "NULL"
        cohort_sql = f"'{cohort}'" if cohort else "NULL"

        sql = f"""
            INSERT INTO organizationunit (tenant_id, parent_id, name, unit_type, academic_year, cohort_label, sort_order, status, created_at, updated_at)
            VALUES ({TENANT_ID}, {pid_sql}, :name, :unit_type, {ay_sql}, {cohort_sql}, {sort_order}, 'active', NOW(), NOW())
            RETURNING id
        """
        r = await conn.execute(text(sql), {"name": name, "unit_type": unit_type})
        new_id = r.scalar()
        by_name[name] = new_id
        print(f"    + 新建组织: {name:20s} (id={new_id}, parent={parent_name})")
    return by_name


async def main():
    engine = create_async_engine(DB_URL)
    async with engine.begin() as conn:  # BEGIN transaction, auto-commit on exit
        print("=" * 70)
        print(f"[A] 构建组织架构节点 tenant={TENANT_ID}")
        org_ids = await upsert_org_units(conn)
        print(f"    组织节点总数: {len(org_ids)}")

        # ———————————————————————————————————————————————————————————
        print("\n" + "=" * 70)
        print(f"[B] 查询教师名单与班级、学科、角色基准数据")
        users = (await conn.execute(text(f"""
            SELECT id, name, phone, role, status
            FROM "user" WHERE tenant_id = {TENANT_ID} ORDER BY id
        """))).mappings().all()
        print(f"    教师用户: {len(users)} 人")

        subjects = (await conn.execute(text("SELECT id, name FROM subject ORDER BY id"))).mappings().all()
        subj_by_name = {s['name']: s['id'] for s in subjects}
        subj_by_group_name = {f"{k}组": subj_by_name[v.replace('教研组','')] for k,v in SUBJECT_KEYWORD_TO_SUBJECT.items() if v.replace('教研组','') in subj_by_name}

        classes = (await conn.execute(text(f"""
            SELECT c.id, c.grade_id, c.name, g.name as grade_name, c.head_teacher_id
            FROM class c LEFT JOIN grade g ON c.grade_id = g.id
            WHERE c.tenant_id = {TENANT_ID}
            ORDER BY g.level, c.name
        """))).mappings().all()
        print(f"    班级总数: {len(classes)}")

        # 查role表（先判断字段存在）
        role_cols = (await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='role'
        """))).fetchall()
        role_cols = {r[0] for r in role_cols}
        sel_cols = ['id', 'code', 'name']
        sel_cols_str = ', '.join(c for c in sel_cols if c in role_cols)
        if not sel_cols_str:
            # role表完全不存在或空列，跳过role相关
            roles = []
            print(f"    （role 表无数据）")
        else:
            roles = (await conn.execute(text(f"SELECT {sel_cols_str} FROM role ORDER BY id"))).mappings().all()
            if 'builtin' in role_cols:
                # 加 builtin 列（后续代码不一定用）
                for r in roles:
                    if 'builtin' not in r:
                        r['builtin'] = False
        role_by_code = {}
        for r in roles:
            code = r.get('code')
            if code:
                role_by_code[code] = r['id']
        print(f"    角色: { {r.get('code'): r.get('id') for r in roles} }")
        print(f"    role 表字段: {sorted(role_cols)}")

        # 查现有 staffappointment
        existing_appt = (await conn.execute(text(f"""
            SELECT DISTINCT organization_unit_id, staff_id, position_code, academic_year
            FROM staffappointment WHERE tenant_id = {TENANT_ID}
        """))).fetchall()
        existing_appt = set(existing_appt)

        # ———————————————————————————————————————————————————————————
        print("\n" + "=" * 70)
        print(f"[C] 分配 staffappointment（组织任命）")
        assigned_count = 0
        skipped = 0

        # 先处理校长
        principal = next((u for u in users if u['role'].lower() in ('director', 'principal') or u['name'].endswith('校长')), None)
        if principal:
            # 校长 → 校级管理(principal)、教务处(academic_director)、德育处(member)
            for unit_name, pos in [
                ("校级管理", "principal"),
                ("教务处", "academic_director"),
                ("德育处", "member"),
            ]:
                key = (org_ids[unit_name], principal['id'], pos, None)
                if key not in existing_appt:
                    await conn.execute(text(f"""
                        INSERT INTO staffappointment
                            (tenant_id, organization_unit_id, staff_id, position_code, academic_year, status, created_at, updated_at)
                        VALUES ({TENANT_ID}, :ouid, :sid, :pos, NULL, 'active', NOW(), NOW())
                    """), {"ouid": org_ids[unit_name], "sid": principal['id'], "pos": pos})
                    assigned_count += 1
                    existing_appt.add(key)
            print(f"    校长 {principal['name']}(id={principal['id']}) → 挂到校级管理/教务处/德育处")

        # 分配其他老师
        assigned_pairs = []
        for u in users:
            if u['id'] == getattr(principal, 'id', None):
                continue
            g_kw, s_kw, role_kw = parse_teacher_name(u['name'])
            grade_info = GRADE_KEYWORD_TO_INFO.get(g_kw) if g_kw else None
            subject_group = SUBJECT_KEYWORD_TO_SUBJECT.get(s_kw) if s_kw else None

            appts_for_user = []

            # 班主任 → 对应年级部(head_teacher)；任教/补充 → 对应年级部(member)
            if grade_info:
                unit_name = grade_info['label']
                pos = 'head_teacher' if role_kw == '班主任' else 'member'
                key = (org_ids[unit_name], u['id'], pos, AY)
                if key not in existing_appt:
                    await conn.execute(text(f"""
                        INSERT INTO staffappointment
                            (tenant_id, organization_unit_id, staff_id, position_code, academic_year, status, created_at, updated_at)
                        VALUES ({TENANT_ID}, :ouid, :sid, :pos, :ay, 'active', NOW(), NOW())
                    """), {"ouid": org_ids[unit_name], "sid": u['id'], "pos": pos, "ay": AY})
                    assigned_count += 1
                    existing_appt.add(key)
                appts_for_user.append(("年级部", unit_name, pos))

            # 学科归属 → 学科教研组(member)
            if subject_group:
                unit_name = subject_group
                key = (org_ids[unit_name], u['id'], 'member', None)
                if key not in existing_appt:
                    await conn.execute(text(f"""
                        INSERT INTO staffappointment
                            (tenant_id, organization_unit_id, staff_id, position_code, academic_year, status, created_at, updated_at)
                        VALUES ({TENANT_ID}, :ouid, :sid, 'member', NULL, 'active', NOW(), NOW())
                    """), {"ouid": org_ids[unit_name], "sid": u['id']})
                    assigned_count += 1
                    existing_appt.add(key)
                appts_for_user.append(("教研组", unit_name, "member"))

            # 如果没匹配任何模式 → 兜底：放到"德育处"(member)
            if not appts_for_user:
                unit_name = "德育处"
                key = (org_ids[unit_name], u['id'], 'member', None)
                if key not in existing_appt:
                    await conn.execute(text(f"""
                        INSERT INTO staffappointment
                            (tenant_id, organization_unit_id, staff_id, position_code, academic_year, status, created_at, updated_at)
                        VALUES ({TENANT_ID}, :ouid, :sid, 'member', NULL, 'active', NOW(), NOW())
                    """), {"ouid": org_ids[unit_name], "sid": u['id']})
                    assigned_count += 1
                    existing_appt.add(key)
                skipped += 1

            assigned_pairs.append((u, g_kw, s_kw, role_kw))

        print(f"    新增任命记录 {assigned_count} 条；（兜底进入德育处的 {skipped} 人）")

        # ———————————————————————————————————————————————————————————
        print("\n" + "=" * 70)
        print(f"[D] 同步 class.head_teacher_id 班主任")
        # 策略：按年级level分组，给每个班依次匹配对应年级的"班主任"序列
        from collections import defaultdict
        classes_by_grade_level = defaultdict(list)
        for c in classes:
            # 解析年级level：grade_name 如 崇仁一中·高一年级 → level 1
            level = None
            if "高一" in c['grade_name']: level = 1
            elif "高二" in c['grade_name']: level = 2
            elif "高三" in c['grade_name']: level = 3
            classes_by_grade_level[level].append(c)
        headteachers_by_level = defaultdict(list)
        for u, g_kw, s_kw, role_kw in assigned_pairs:
            if role_kw != '班主任' or not g_kw:
                continue
            level = GRADE_KEYWORD_TO_INFO[g_kw]['level']
            headteachers_by_level[level].append(u)

        updated_cls = 0
        for level, cls_list in classes_by_grade_level.items():
            if level is None:
                continue
            hts = headteachers_by_level.get(level, [])
            if not hts:
                continue
            # 循环分配
            for idx, c in enumerate(cls_list):
                if c['head_teacher_id'] is not None:
                    continue  # 已有班主任，不覆盖
                teacher = hts[idx % len(hts)]
                await conn.execute(text("UPDATE class SET head_teacher_id = :ht WHERE id = :cid"),
                                   {"ht": teacher['id'], "cid": c['id']})
                updated_cls += 1
        print(f"    给 {updated_cls} 个班分配了班主任 head_teacher_id")

        # ———————————————————————————————————————————————————————————
        print("\n" + "=" * 70)
        print(f"[E] 补 userrole 关联（任教老师自动拿 subject_teacher；主任拿 school_admin）")
        school_admin_role = role_by_code.get('school_admin')
        subject_teacher_role = role_by_code.get('subject_teacher')
        head_teacher_role = role_by_code.get('head_teacher')
        academic_director_role = role_by_code.get('academic_director')

        existing_ur = set(
            (await conn.execute(text("SELECT user_id, role_id FROM userrole"))).fetchall()
        )

        def add_ur(uid, rid):
            if rid is None or (uid, rid) in existing_ur:
                return 0
            existing_ur.add((uid, rid))
            return 1

        # 先查 role 表，确认存在
        roles_rows = (await conn.execute(text("SELECT id, code FROM role"))).fetchall()
        print(f"    现有 role 表条目：{[(r[0], r[1]) for r in roles_rows]}")
        if not roles_rows:
            print("    （role 表空，跳过 userrole 补齐）")
        else:
            ur_added = 0
            for u in users:
                # 主任/校长 → school_admin
                if u['role'].lower() in ('director', 'principal') or u['name'].endswith('校长'):
                    ur_added += add_ur(u['id'], school_admin_role)
                    continue
                # teacher 基础角色：班主任 → head_teacher；其他任课老师 → subject_teacher
                _, _, role_kw = parse_teacher_name(u['name'])
                if role_kw == '班主任':
                    ur_added += add_ur(u['id'], head_teacher_role) or add_ur(u['id'], subject_teacher_role)
                else:
                    ur_added += add_ur(u['id'], subject_teacher_role)
            print(f"    新增 userrole {ur_added} 条")

        # ———————————————————————————————————————————————————————————
        print("\n" + "=" * 70)
        print(f"[F] 建 teachingassignment 任教关系（按解析的年级+学科生成）")
        # 统计现有任教
        existing_ta = set(
            (await conn.execute(text(f"""
                SELECT teacher_id, subject_id, class_id FROM teachingassignment WHERE tenant_id={TENANT_ID}
            """))).fetchall()
        )

        # 给每一个用户按 (年级, 学科) 分到该年级的班级
        ta_added = 0
        # 按年级level分组classes
        cls_by_level = defaultdict(list)
        for c in classes:
            level = None
            if "高一" in c['grade_name']: level = 1
            elif "高二" in c['grade_name']: level = 2
            elif "高三" in c['grade_name']: level = 3
            if level is not None:
                cls_by_level[level].append(c)

        for u, g_kw, s_kw, role_kw in assigned_pairs:
            if not s_kw or s_kw not in (subj_by_name.keys()):
                continue
            sid = subj_by_name[s_kw]
            level = GRADE_KEYWORD_TO_INFO[g_kw]['level'] if g_kw else None
            if level is None:
                continue

            # 班主任教自己班的主科；其他老师轮流分配
            cls_list = cls_by_level.get(level, [])
            if not cls_list:
                continue
            user_idx = next(
                (i for i, uu in enumerate(headteachers_by_level.get(level, [])) if uu['id'] == u['id']),
                assigned_pairs.index((u, g_kw, s_kw, role_kw)) % max(len(cls_list),1)
            )

            # 每人分配 2~5 个班任教（班主任只教1~2个班，任课老师教3~5个班）
            if role_kw == '班主任':
                n_classes = 2
            elif role_kw == '补充教师':
                n_classes = 2
            else:  # 任课教师
                n_classes = 5
            periods_per_class = 5 if s_kw in ('语文','数学','英语') else 4 if s_kw in ('物理','化学') else 3

            for k in range(n_classes):
                cls = cls_list[(user_idx + k) % len(cls_list)]
                key = (u['id'], sid, cls['id'])
                if key in existing_ta:
                    continue
                await conn.execute(text(f"""
                    INSERT INTO teachingassignment
                        (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
                    VALUES ({TENANT_ID}, :tid, :sid, :cid, :ay, :term, :wp, NULL)
                """), {"tid": u['id'], "sid": sid, "cid": cls['id'], "ay": AY, "term": TERM, "wp": periods_per_class})
                existing_ta.add(key)
                ta_added += 1

        print(f"    新增 teachingassignment 任教关系 {ta_added} 条")

        print("\n" + "=" * 70)
        print("✓ 全部完成（一个事务内提交）")

    await engine.dispose()

asyncio.run(main())
