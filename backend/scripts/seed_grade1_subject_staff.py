"""Seed the exact high-one subject-group staffing plan for the demo school.

This script is idempotent. It creates only teacher accounts, places them in
their matching subject groups, and assigns exactly one core-subject head
teacher to each high-one administrative class. It intentionally does not
create teaching assignments or grade-group appointments.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal
from app.models.enums import BaseUserRole
from app.models.org import Class, Grade, OrganizationUnit, StaffAppointment, Tenant, User
from app.services.staff_roles import replace_staff_roles


ACADEMIC_YEAR = "2026-2027"
SUBJECTS = ("语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理", "体育")
HEAD_SUBJECTS = ("语文", "数学", "英语")
# 38 classes: 13/13/12 head teachers, with head teachers covering two
# classes at most and other subject teachers covering three classes at most.
TARGET_COUNTS = {
    "语文": 17,
    "数学": 17,
    "英语": 17,
    "物理": 13,
    "化学": 13,
    "生物": 13,
    "政治": 13,
    "历史": 13,
    "地理": 13,
    "体育": 13,
}


async def seed(school_code: str) -> None:
    async with AsyncSessionLocal() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.code == school_code))).scalar_one()
        classes = list((await session.execute(
            select(Class)
            .join(Grade, Grade.id == Class.grade_id)
            .where(Class.tenant_id == tenant.id, Grade.tenant_id == tenant.id, Grade.level == 1)
            .order_by(Class.id)
        )).scalars().all())
        if len(classes) < 1:
            raise SystemExit("未找到高一年级班级，请先生成高一行政班")

        units = list((await session.execute(
            select(OrganizationUnit).where(
                OrganizationUnit.tenant_id == tenant.id,
                OrganizationUnit.unit_type == "subject_group",
                OrganizationUnit.status == "active",
            )
        )).scalars().all())
        subject_units = {subject: next(
            (unit for unit in units if unit.name == f"{subject}教研组"), None
        ) for subject in SUBJECTS}
        if len(subject_units) != len(SUBJECTS):
            raise SystemExit("学科教研组不完整，请先初始化学校组织架构")

        users_by_phone = {
            user.phone: user
            for user in (await session.execute(select(User).where(User.tenant_id == tenant.id))).scalars().all()
        }
        password_hash = get_password_hash("Teacher@2026")
        subject_teachers: dict[str, list[User]] = defaultdict(list)
        created = 0
        appointment_created = 0
        assigned_heads = 0

        async def ensure_teacher(phone: str, name: str, roles: list[str]) -> User:
            nonlocal created
            teacher = users_by_phone.get(phone)
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
                users_by_phone[phone] = teacher
                created += 1
            await replace_staff_roles(session, teacher.id, roles, tenant.id)
            return teacher

        number = 1
        for subject in SUBJECTS:
            head_count = 0
            if subject in HEAD_SUBJECTS:
                head_count = (len(classes) + 2) // 3 if subject in ("语文", "数学") else len(classes) // 3
            target = TARGET_COUNTS[subject]
            for index in range(1, target + 1):
                is_head = index <= head_count
                label = "班主任" if is_head else "任课教师"
                phone = f"1882027{number:04d}"
                teacher = await ensure_teacher(
                    phone,
                    f"高一{subject}{label}{index:02d}",
                    ["head_teacher", "subject_teacher"] if is_head else ["subject_teacher"],
                )
                number += 1
                subject_teachers[subject].append(teacher)
                exists = (await session.execute(select(StaffAppointment).where(
                    StaffAppointment.tenant_id == tenant.id,
                    StaffAppointment.organization_unit_id == subject_units[subject].id,
                    StaffAppointment.staff_id == teacher.id,
                    StaffAppointment.position_code == "member",
                    StaffAppointment.academic_year.is_(None),
                    StaffAppointment.status == "active",
                ))).scalar_one_or_none()
                if exists is None:
                    session.add(StaffAppointment(
                        tenant_id=tenant.id,
                        organization_unit_id=subject_units[subject].id,
                        staff_id=teacher.id,
                        position_code="member",
                        academic_year=None,
                        status="active",
                    ))
                    appointment_created += 1

        # Rotate 38 class head teachers across Chinese, Math and English.
        pools = {subject: list(subject_teachers[subject][:13 if subject != "英语" else 12]) for subject in HEAD_SUBJECTS}
        for position, school_class in enumerate(classes):
            if school_class.head_teacher_id is not None:
                continue
            subject = HEAD_SUBJECTS[position % len(HEAD_SUBJECTS)]
            pool = pools[subject]
            teacher = pool[position // len(HEAD_SUBJECTS)]
            school_class.head_teacher_id = teacher.id
            session.add(school_class)
            assigned_heads += 1

        await session.commit()
        print(f"高一班级：{len(classes)} 个")
        print(f"新建教师账号：{created} 个")
        print(f"新增学科教研组任职：{appointment_created} 条")
        print(f"新增班主任绑定：{assigned_heads} 个")
        print("目标总量：语文17、数学17、英语17，其余学科各13；未生成任教关系或年级部任职")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("school_code", nargs="?", default=settings.default_school_code)
    args = parser.parse_args()
    asyncio.run(seed(args.school_code))
