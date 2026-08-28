import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://postgres:123456@localhost:5432/zhiheng"

async def main():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        # 1. 所有表名
        print("=" * 80)
        print("[1] 数据库里的所有表名（public schema）")
        rows = (await conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))).fetchall()
        for (t,) in rows:
            print("  ", t)

        # 2. 只查 tenant=广东新高考实验中学 的相关数据
        print()
        print("=" * 80)
        print("[2] 租户及ID匹配")
        rows = (await conn.execute(text("SELECT id, code, name, province FROM tenant ORDER BY id"))).mappings().all()
        for r in rows:
            print(f"  tenant_id={r['id']} code={r['code']!r} name={r['name']!r} province={r['province']}")

        # 3. 取第一个非崇仁租户的详细（从用户截图是 广东新高考实验中学）
        print()
        print("=" * 80)
        print("[3] 用户列表（按 teacher 汇总，只看 广东新高考实验中学 tenant）")
        # 先找到对应tenant_id
        trow = (await conn.execute(text("SELECT id FROM tenant WHERE name LIKE '%广东%' OR name LIKE '%新高考%' LIMIT 1"))).first()
        if trow:
            target_tid = trow[0]
        else:
            # fallback: 取不是崇仁的第一个租户
            trow2 = (await conn.execute(text("SELECT id FROM tenant WHERE name NOT LIKE '%崇仁%' LIMIT 1"))).first()
            target_tid = trow2[0] if trow2 else 1
        print(f"  目标tenant_id = {target_tid}")

        users = (await conn.execute(text(f"""
            SELECT id, name, phone, role, status FROM "user" WHERE tenant_id = {target_tid} ORDER BY id
        """))).mappings().all()
        print(f"  该校教师总数 = {len(users)}")
        for r in users[:50]:
            print(f"    id={r['id']:3d} name={r['name']:<16} phone={r['phone']:<14} role={r['role']:<18} status={r['status']}")
        if len(users) > 50:
            print(f"    ... 还有 {len(users)-50} 条")

        # 4. 年级
        print()
        print("=" * 80)
        print("[4] 年级列表 (tenant_id={})".format(target_tid))
        rows = (await conn.execute(text(f"""
            SELECT id, name, level, campus_id FROM grade WHERE tenant_id = {target_tid} ORDER BY level, id
        """))).mappings().all()
        for r in rows:
            print(f"    grade_id={r['id']:2d} name={r['name']:<14} level={r['level']} campus={r['campus_id']}")
        grade_ids_by_name = {r['name'].replace('崇仁一中·','').replace('崇仁二中·','').replace('广东新高考实验中学·','').replace('校区·',''): r['id'] for r in rows}
        print("    精简映射: ", grade_ids_by_name)

        # 5. 学科
        print()
        print("=" * 80)
        print("[5] 学科字典")
        rows = (await conn.execute(text("SELECT id, name FROM subject ORDER BY id"))).mappings().all()
        subject_id_by_name = {r['name']: r['id'] for r in rows}
        for r in rows:
            print(f"    subject_id={r['id']}  {r['name']}")

        # 6. 班级（按年级分组，取每年级前5个）
        print()
        print("=" * 80)
        print(f"[6] 班级列表（每年级前5班，tenant={target_tid}）")
        rows = (await conn.execute(text(f"""
            SELECT c.id, c.name, g.name as grade_name, c.head_teacher_id, u.name as head_teacher_name, c.class_type
            FROM class c
            LEFT JOIN grade g ON c.grade_id = g.id
            LEFT JOIN "user" u ON c.head_teacher_id = u.id
            WHERE c.tenant_id = {target_tid}
            ORDER BY g.level, c.name
        """))).mappings().all()
        from collections import defaultdict
        cls_by_grade = defaultdict(list)
        for r in rows:
            cls_by_grade[r['grade_name']].append(r)
        for gname, clist in cls_by_grade.items():
            print(f"  {gname} 共 {len(clist)} 个班：")
            for r in clist[:5]:
                ht = f" 班主任={r['head_teacher_name']}(id={r['head_teacher_id']})" if r['head_teacher_id'] else "  无班主任"
                print(f"    id={r['id']:3d} name={r['name']:<16}{ht}")
            if len(clist) > 5:
                print(f"    ... 还有 {len(clist)-5} 个班")

        # 7. 任教关系摘要
        print()
        print("=" * 80)
        print(f"[7] 任教关系总数 (tenant={target_tid})")
        cnt = (await conn.execute(text(f"SELECT COUNT(*) FROM teaching_assignment WHERE tenant_id={target_tid}"))).scalar()
        print(f"  count = {cnt}")
        if cnt:
            rows = (await conn.execute(text(f"""
                SELECT u.name as tname, s.name as sname, COUNT(DISTINCT c.id) as n_class,
                       SUM(ta.weekly_periods) as total_week
                FROM teaching_assignment ta
                LEFT JOIN "user" u ON ta.teacher_id = u.id
                LEFT JOIN subject s ON ta.subject_id = s.id
                LEFT JOIN class c ON ta.class_id = c.id
                WHERE ta.tenant_id = {target_tid}
                GROUP BY u.name, s.name
                ORDER BY u.name, s.name
                LIMIT 30
            """))).mappings().all()
            for r in rows:
                print(f"    {r['tname']:<12} 教 {r['sname']:<4} 覆盖 {r['n_class']:2} 个班，每周 {r['total_week']} 节")

    await engine.dispose()

asyncio.run(main())
