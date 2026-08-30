import asyncio
from sqlmodel import select
from sqlalchemy import func
from app.db.session import AsyncSessionLocal
from app.models.facility import Campus
from app.models.org import Grade, OrganizationUnit, Student, StudentGradeMembership, Tenant

async def main():
    async with AsyncSessionLocal() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.code == "nstmy"))).scalar_one_or_none()
        print("tenant", tenant.id if tenant else None, tenant.name if tenant else None)
        if not tenant:
            return
        campuses = (await session.execute(select(Campus).where(Campus.tenant_id == tenant.id))).scalars().all()
        grades = (await session.execute(select(Grade).where(Grade.tenant_id == tenant.id))).scalars().all()
        units = (await session.execute(select(OrganizationUnit).where(OrganizationUnit.tenant_id == tenant.id))).scalars().all()
        print("campuses", [(c.id, c.name) for c in campuses])
        print("grades", [(g.id, g.campus_id, g.name, g.level) for g in grades])
        print("units", [(u.id, u.name, u.unit_type, u.grade_id, u.academic_year, u.cohort_label, u.status) for u in units])
        grade_unit = next((u for u in units if u.grade_id == 12 and u.cohort_label == "2026届"), None)
        if grade_unit and campuses:
            student_count = (await session.execute(select(func.count(Student.id)).where(
                Student.tenant_id == tenant.id,
                Student.campus_id == campuses[0].id,
                Student.grade_id == 12,
                Student.class_id.is_(None),
            ))).scalar_one()
            membership_count = (await session.execute(select(func.count(StudentGradeMembership.id)).where(
                StudentGradeMembership.tenant_id == tenant.id,
                StudentGradeMembership.grade_unit_id == grade_unit.id,
                StudentGradeMembership.grade_id == 12,
                StudentGradeMembership.academic_year == "2026-2027",
                StudentGradeMembership.status == "active",
            ))).scalar_one()
            print("verification", {
                "grade_campus_id": next((g.campus_id for g in grades if g.id == 12), None),
                "student_campus_id": campuses[0].id,
                "grade_unit_id": grade_unit.id,
                "waiting_students": student_count,
                "active_memberships": membership_count,
            })

if __name__ == "__main__":
    asyncio.run(main())
