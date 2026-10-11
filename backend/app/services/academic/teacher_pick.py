"""教学班选课名额：提交与已分班学生按学生去重，草稿不占名额。"""
from sqlalchemy import select

from app.models.gaokao import StudentSubjectChoice, TeachingClassStudent


async def class_selection_members(session, tenant_id, academic_year, term, class_ids):
    members = {class_id: set() for class_id in class_ids}
    if not members:
        return members
    rows = (await session.execute(select(TeachingClassStudent).where(
        TeachingClassStudent.tenant_id == tenant_id,
        TeachingClassStudent.teaching_class_id.in_(class_ids),
    ))).scalars().all()
    for row in rows:
        members[row.teaching_class_id].add(row.student_id)
    choices = (await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == tenant_id,
        StudentSubjectChoice.academic_year == academic_year,
        StudentSubjectChoice.effective_term == term,
        StudentSubjectChoice.status.in_(['confirmed', 'locked']),
    ))).scalars().all()
    for choice in choices:
        for class_id in (choice.teaching_class_preferences or {}).values():
            if class_id in members:
                members[class_id].add(choice.student_id)
    return members
