import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB_URL = "postgresql+asyncpg://postgres:123456@localhost:5432/zhiheng"

TABLES_OF_INTEREST = [
    'organizationunit', 'staffappointment', 'teachingassignment',
    'organization_unit', 'staff_appointment', 'teaching_assignment',
    'tenantconfig', 'tenant_config', 'userrole', 'user_role',
]

async def main():
    engine = create_async_engine(DB_URL)
    async with engine.connect() as conn:
        # 列所有表
        rows = (await conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))).fetchall()
        all_tables = {r[0] for r in rows}

        print("=== 探测需要的表 ===")
        found = {}
        for want in TABLES_OF_INTEREST:
            if want in all_tables:
                found[want] = True
                print(f"  ✓ {want}")
            else:
                print(f"  ✗ {want}  （不存在）")

        # 同时打印每个存在的表的列结构
        print("\n=== 表结构 ===")
        for t in sorted(found.keys()):
            cols = (await conn.execute(text(f"""
                SELECT column_name, data_type, character_maximum_length, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = '{t}'
                ORDER BY ordinal_position
            """))).mappings().all()
            print(f"\n  [{t}] ({len(cols)} cols)")
            for c in cols:
                nullable = 'NULL' if c['is_nullable'] == 'YES' else 'NOT NULL'
                extra = f"({c['character_maximum_length']})" if c['character_maximum_length'] else ''
                print(f"    - {c['column_name']:<30s} {c['data_type']}{extra:<20s} {nullable}")

        # 再确认organization接口用的表，从表名中猜对应关系
        print("\n=== 实际表名映射 ===")
        mapping = {}
        for logical, candidates in {
            "OrganizationUnit": ["organizationunit", "organization_unit"],
            "StaffAppointment": ["staffappointment", "staff_appointment"],
            "TeachingAssignment": ["teachingassignment", "teaching_assignment"],
            "TenantConfig":    ["tenantconfig", "tenant_config"],
            "UserRole":        ["userrole", "user_role"],
        }.items():
            for cand in candidates:
                if cand in all_tables:
                    mapping[logical] = cand
                    print(f"  {logical:20s} → {cand}")
                    break
            else:
                print(f"  {logical:20s} → (MISSING, will need CREATE TABLE)")

    await engine.dispose()

asyncio.run(main())
