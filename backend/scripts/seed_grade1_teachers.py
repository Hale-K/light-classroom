"""Generate unique high-one teaching staff for the current demo school.

The seed is idempotent. It creates one head teacher for every high-one class
that does not already have one, rotates head-teacher subjects across Chinese,
Math and English, and creates enough additional subject teachers for the
first-term all-subject timetable.
"""
from __future__ import annotations

import asyncio
import argparse
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal, engine
from app.models.enums import BaseUserRole
from app.models.org import Class, Grade, Student, Subject, TeachingAssignment, Tenant, User
from app.services.staff_roles import replace_staff_roles


ACADEMIC_YEAR = "2026-2027"
TERM = "1"
HEAD_SUBJECTS = ("语文", "数学", "英语")
ALL_SUBJECTS = ("语文", "数学", "英语", "物理", "历史", "化学", "生物", "政治", "地理")
WEEKLY_PERIODS = {"语文": 5, "数学": 5, "英语": 5, "物理": 3, "历史": 3, "化学": 2, "生物": 2, "政治": 2, "地理": 2}
EXTRA_TEACHER_COUNTS = {"物理": 8, "历史": 8, "化学": 5, "生物": 5, "政治": 5, "地理": 5}


async def seed() -> None:
    engine.echo = False
    async with AsyncSessionLocal() as session:
        school_code = getattr(seed, "school_code", settings.default_school_code)
        tenant = (await session.execute(select(Tenant).where(Tenant.code == school_code))).scalar_one()
        grade = (await session.execute(
            select(Grade)
            .join(Class, Class.grade_id == Grade.id)
            .join(Student, Student.class_id == Class.id)
            .where(Grade.tenant_id == tenant.id, Grade.level == 1)
            .group_by(Grade.id)
            .order_by(func.count(Student.id).desc(), Grade.id)
        )).scalars().first()
        if grade is None:
            raise SystemExit("未找到高一年级，请先创建高一年级")
        classes = list((await session.execute(
            select(Class).where(Class.tenant_id == tenant.id, Class.grade_id == grade.id).order_by(Class.id)
        )).scalars().all())
        if not classes:
            raise SystemExit("高一年级暂无行政班，请先生成班级")

        subjects = {item.name: item for item in (await session.execute(select(Subject))).scalars().all()}
        for name in ALL_SUBJECTS:
            if name not in subjects:
                subject = Subject(name=name)
                session.add(subject)
                await session.flush()
                subjects[name] = subject

        existing_users = {
            item.phone: item
            for item in (await session.execute(select(User).where(User.tenant_id == tenant.id))).scalars().all()
        }
        password_hash = get_password_hash("Teacher@2026")
        subject_pools: dict[str, list[User]] = defaultdict(list)
        created_accounts = 0

        def phone_for(number: int) -> str:
            return f"1882027{number:04d}"

        async def ensure_teacher(number: int, name: str, roles: list[str]) -> User:
            nonlocal created_accounts
            phone = phone_for(number)
            teacher = existing_users.get(phone)
            if teacher is None:
                teacher = User(
                    tenant_id=tenant.id,
                    name=name,
                    phone=phone,
                    password_hash=password_hash,
                    role=BaseUserRole.teacher,
                )
                session.add(teacher)
                await session.flush()
                existing_users[phone] = teacher
                created_accounts += 1
            await replace_staff_roles(session, teacher.id, roles, tenant.id)
            return teacher

        next_number = 1
        head_subject_by_teacher: dict[int, str] = {}
        for position, school_class in enumerate(classes, start=1):
            subject_name = HEAD_SUBJECTS[(position - 1) % len(HEAD_SUBJECTS)]
            if school_class.head_teacher_id is None:
                teacher = await ensure_teacher(
                    next_number,
                    f"高一{subject_name}班主任{position:02d}",
                    ["head_teacher", "subject_teacher"],
                )
                next_number += 1
                school_class.head_teacher_id = teacher.id
                session.add(school_class)
                head_subject_by_teacher[teacher.id] = subject_name
                subject_pools[subject_name].append(teacher)
            else:
                existing_head = await session.get(User, school_class.head_teacher_id)
                if existing_head is not None:
                    assignments = list((await session.execute(select(TeachingAssignment).where(
                        TeachingAssignment.tenant_id == tenant.id,
                        TeachingAssignment.teacher_id == existing_head.id,
                        TeachingAssignment.class_id == school_class.id,
                        TeachingAssignment.academic_year == ACADEMIC_YEAR,
                        TeachingAssignment.term == TERM,
                    ))).scalars().all())
                    if assignments:
                        subject_name = next((name for name, item in subjects.items() if item.id == assignments[0].subject_id), subject_name)
                    subject_pools[subject_name].append(existing_head)

        for subject_name, count in EXTRA_TEACHER_COUNTS.items():
            for index in range(1, count + 1):
                teacher = await ensure_teacher(
                    next_number,
                    f"高一{subject_name}任课教师{index:02d}",
                    ["subject_teacher"],
                )
                next_number += 1
                subject_pools[subject_name].append(teacher)

        existing_assignments = {
            (item.teacher_id, item.subject_id, item.class_id, item.academic_year, item.term): item
            for item in (await session.execute(select(TeachingAssignment).where(
                TeachingAssignment.tenant_id == tenant.id,
                TeachingAssignment.class_id.in_([item.id for item in classes]),
                TeachingAssignment.academic_year == ACADEMIC_YEAR,
                TeachingAssignment.term == TERM,
            ))).scalars().all()
        }
        class_subject_assignments = {(item.class_id, item.subject_id): item for item in existing_assignments.values()}
        loads: dict[int, int] = defaultdict(int)
        for item in existing_assignments.values():
            loads[item.teacher_id] += item.weekly_periods

        added_assignments = 0
        for school_class in classes:
            head_subject = head_subject_by_teacher.get(school_class.head_teacher_id)
            for subject_name in ALL_SUBJECTS:
                subject_id = subjects[subject_name].id
                if (school_class.id, subject_id) in class_subject_assignments:
                    continue
                pool = subject_pools[subject_name]
                if not pool:
                    continue
                teacher = next((item for item in pool if item.id == school_class.head_teacher_id), None) if subject_name == head_subject else None
                teacher = teacher or min(pool, key=lambda item: (loads[item.id], item.id))
                assignment = TeachingAssignment(
                    tenant_id=tenant.id,
                    teacher_id=teacher.id,
                    subject_id=subject_id,
                    class_id=school_class.id,
                    academic_year=ACADEMIC_YEAR,
                    term=TERM,
                    weekly_periods=WEEKLY_PERIODS[subject_name],
                    room=school_class.name,
                )
                session.add(assignment)
                class_subject_assignments[(school_class.id, subject_id)] = assignment
                loads[teacher.id] += WEEKLY_PERIODS[subject_name]
                added_assignments += 1

        await session.commit()
        print(f"高一班级：{len(classes)} 个")
        print(f"新建教师账号：{created_accounts} 个")
        print(f"新增任教关系：{added_assignments} 条")
        print("班主任主科：语文、数学、英语轮换")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("school_code", nargs="?", default=settings.default_school_code)
    args = parser.parse_args()
    seed.school_code = args.school_code
    asyncio.run(seed())
