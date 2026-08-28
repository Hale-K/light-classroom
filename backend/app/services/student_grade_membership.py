"""Maintain the student -> grade-group snapshot relationship."""
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.org import Grade, OrganizationUnit, Student, StudentGradeMembership
async def sync_student_grade_membership(
    session: AsyncSession,
    *,
    tenant_id: int,
    student: Student,
    grade_id: int,
    academic_year: str,
    status: str = "active",
) -> StudentGradeMembership:
    """Create/update one idempotent grade-group snapshot for a student."""
    grade = await session.get(Grade, grade_id)
    if grade is None or grade.tenant_id != tenant_id:
        raise ValueError("学生所属年级不存在")
    unit_candidates = list((await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.unit_type == "grade_group",
        OrganizationUnit.grade_id == grade_id,
        OrganizationUnit.academic_year == academic_year,
        OrganizationUnit.status == "active",
    ).order_by(OrganizationUnit.id))).scalars().all())
    if len(unit_candidates) > 1:
        raise ValueError(f"当前学年存在多个与{grade.name}关联的年级部，请先修正组织架构")
    unit = unit_candidates[0] if unit_candidates else None
    if unit is None:
        raise ValueError(f"当前学年尚未建立与{grade.name}关联的年级部")
    membership = (await session.execute(select(StudentGradeMembership).where(
        StudentGradeMembership.tenant_id == tenant_id,
        StudentGradeMembership.student_id == student.id,
        StudentGradeMembership.academic_year == academic_year,
    ))).scalar_one_or_none()
    if membership is None:
        membership = StudentGradeMembership(
            tenant_id=tenant_id,
            student_id=student.id,
            grade_id=grade_id,
            grade_unit_id=unit.id,
            academic_year=academic_year,
            cohort_label=unit.cohort_label,
            status=status,
        )
        session.add(membership)
    else:
        membership.grade_id = grade_id
        membership.grade_unit_id = unit.id
        membership.cohort_label = unit.cohort_label
        membership.status = status
    return membership
