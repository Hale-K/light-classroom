import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://postgres:123456@localhost:5432/zhiheng"

async def main():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        # 1. 租户信息
        print("=" * 60)
        print("[1] 租户列表")
        rows = (await conn.execute(text("SELECT id, code, name, province, gaokao_mode FROM tenant"))).mappings().all()
        for r in rows:
            print(f"  id={r['id']} code={r['code']} name={r['name']} {r['province']} 高考模式={r['gaokao_mode']}")

        # 2. 用户列表（教师）
        print()
        print("=" * 60)
        print("[2] 教师用户列表")
        rows = (await conn.execute(text("""
            SELECT id, tenant_id, name, phone, role, status
            FROM "user"
            ORDER BY tenant_id, id
        """))).mappings().all()
        for r in rows:
            print(f"  id={r['id']:3d}  tenant={r['tenant_id']}  name={r['name']:<8}  phone={r['phone']:<14}  role={r['role']:20s} status={r['status']}")

        # 3. 学科字典
        print()
        print("=" * 60)
        print("[3] 学科字典")
        rows = (await conn.execute(text("SELECT id, name FROM subject ORDER BY id"))).mappings().all()
        for r in rows:
            print(f"  id={r['id']}  {r['name']}")

        # 4. 年级列表
        print()
        print("=" * 60)
        print("[4] 年级列表")
        rows = (await conn.execute(text("SELECT id, tenant_id, name, level, campus_id FROM grade ORDER BY tenant_id, level"))).mappings().all()
        for r in rows:
            print(f"  id={r['id']:2d}  tenant={r['tenant_id']}  name={r['name']:<10}  level={r['level']}  campus={r['campus_id']}")

        # 5. 班级列表
        print()
        print("=" * 60)
        print("[5] 班级列表（含班主任）")
        rows = (await conn.execute(text("""
            SELECT c.id, c.tenant_id, c.name, g.name as grade_name,
                   c.class_type, c.head_teacher_id, u.name as head_teacher_name,
                   c.home_room_id
            FROM class c
            LEFT JOIN grade g ON c.grade_id = g.id
            LEFT JOIN "user" u ON c.head_teacher_id = u.id
            ORDER BY c.tenant_id, g.level, c.name
        """))).mappings().all()
        for r in rows:
            ht = f" 班主任={r['head_teacher_name']}(id={r['head_teacher_id']})" if r['head_teacher_id'] else "  无班主任"
            print(f"  id={r['id']:2d}  tenant={r['tenant_id']}  {r['grade_name']:<6} {r['name']:<8} type={r['class_type']:10s} {ht}")

        # 6. 组织机构节点
        print()
        print("=" * 60)
        print("[6] OrganizationUnit 组织机构节点")
        rows = (await conn.execute(text("""
            SELECT id, tenant_id, parent_id, name, unit_type, academic_year, cohort_label, sort_order, status
            FROM organization_unit
            ORDER BY tenant_id, COALESCE(parent_id, 0), sort_order, id
        """))).mappings().all()
        for r in rows:
            print(f"  id={r['id']:2d} tenant={r['tenant_id']} parent={r['parent_id']!s:<4} type={r['unit_type']:<15s} name={r['name']:<12s} ay={str(r['academic_year']):<10s} cohort={str(r['cohort_label']):<6s} order={r['sort_order']} status={r['status']}")

        # 7. 人员岗位任命
        print()
        print("=" * 60)
        print("[7] StaffAppointment 人员岗位任命（组织架构分配）")
        rows = (await conn.execute(text("""
            SELECT sa.id, sa.tenant_id, ou.name as ou_name, ou.unit_type,
                   u.name as staff_name, sa.position_code, sa.academic_year, sa.status
            FROM staff_appointment sa
            LEFT JOIN organization_unit ou ON sa.organization_unit_id = ou.id
            LEFT JOIN "user" u ON sa.staff_id = u.id
            ORDER BY sa.tenant_id, ou.name, u.name
        """))).mappings().all()
        if not rows:
            print("  （空：暂无任命记录）")
        for r in rows:
            print(f"  id={r['id']:2d} tenant={r['tenant_id']} [{r['unit_type']:<12}] {r['ou_name']:<10s} → {r['staff_name']:<8s} position={r['position_code']:<10s} ay={str(r['academic_year']):<10s} status={r['status']}")

        # 8. 任教关系
        print()
        print("=" * 60)
        print("[8] TeachingAssignment 任教关系")
        rows = (await conn.execute(text("""
            SELECT ta.id, ta.teacher_id, u.name as teacher_name,
                   s.name as subject, c.name as class_name, g.name as grade_name,
                   ta.academic_year, ta.term, ta.weekly_periods, ta.room
            FROM teaching_assignment ta
            LEFT JOIN "user" u ON ta.teacher_id = u.id
            LEFT JOIN subject s ON ta.subject_id = s.id
            LEFT JOIN class c ON ta.class_id = c.id
            LEFT JOIN grade g ON c.grade_id = g.id
            ORDER BY ta.tenant_id, g.level, c.name, s.name
        """))).mappings().all()
        if not rows:
            print("  （空：暂无任教关系）")
        for r in rows:
            print(f"  id={r['id']:2d} {r['teacher_name']:<6s} 教 {r['grade_name']}{r['class_name']:<6s} 的 {r['subject']:<4s}  {r['academic_year']}第{r['term']}学期 周{r['weekly_periods']}节 教室={r['room']}")

    await engine.dispose()

asyncio.run(main())
