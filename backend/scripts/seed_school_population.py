"""Seed a realistic 5,500-student high-school population for the demo tenant.

The script is idempotent: it reuses grades/classes/teachers identified by their
stable names or demo phone numbers and only creates missing students and
teaching assignments.
"""
from __future__ import annotations

import asyncio
import random
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal, engine
from app.models.enums import BaseUserRole, ExamStatus, ExamType, Gender, PaperStatus, SeatLayout, SeatRule, SeatStatus
from app.models.exam import Exam, Paper
from app.models.gaokao import GaokaoScheme, StudentSubjectChoice
from app.models.org import Class, Grade, SeatArrangement, Student, Subject, TeachingAssignment, Tenant, User
from app.services.scheduling import arrange_students


ACADEMIC_YEAR = "2026-2027"
TERM = "1"
STUDENTS_PER_CLASS = 40
GRADE_PLAN = (("高一年级", "高一", 1, 46), ("高二年级", "高二", 2, 46), ("高三年级", "高三", 3, 46))
SUBJECT_PLAN = (
    ("语文", 5, 46),
    ("数学", 5, 46),
    ("英语", 5, 46),
    ("物理", 3, 28),
    ("化学", 3, 28),
    ("生物", 3, 28),
    ("政治", 2, 18),
    ("历史", 2, 18),
    ("地理", 2, 18),
)
LEGACY_TEACHER_RANGES = {
    "语文": range(1, 10), "数学": range(10, 19), "英语": range(19, 28),
    "物理": range(28, 33), "化学": range(33, 38), "生物": range(38, 43),
    "政治": range(43, 47), "历史": range(47, 51), "地理": range(51, 55),
}
SURNAMES = tuple("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜")
GIVEN_NAMES = (
    "子涵", "宇轩", "梓萱", "浩然", "欣怡", "雨桐", "俊杰", "思源", "嘉怡", "博文",
    "语嫣", "晨曦", "致远", "若溪", "明轩", "诗涵", "睿哲", "佳宁", "天佑", "雅琪",
    "泽宇", "可欣", "文昊", "梦瑶", "嘉豪", "依诺", "承泽", "欣妍", "景行", "婉清",
)


def person_name(index: int) -> str:
    return SURNAMES[index % len(SURNAMES)] + GIVEN_NAMES[(index // len(SURNAMES)) % len(GIVEN_NAMES)]


async def seed() -> None:
    engine.echo = False
    randomizer = random.Random(20260824)
    async with AsyncSessionLocal() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.code == settings.default_school_code))).scalar_one()
        tenant_id = tenant.id
        assert tenant_id is not None

        grades_by_level = {
            grade.level: grade
            for grade in (await session.execute(select(Grade).where(Grade.tenant_id == tenant_id))).scalars()
        }
        classes_by_name = {
            school_class.name: school_class
            for school_class in (await session.execute(select(Class).where(Class.tenant_id == tenant_id))).scalars()
        }

        target_classes: list[Class] = []
        target_class_specs: list[tuple[Class, int, int, int]] = []
        for grade_name, class_prefix, level, class_count in GRADE_PLAN:
            grade = grades_by_level.get(level)
            if grade is None:
                grade = Grade(tenant_id=tenant_id, name=grade_name, level=level)
                session.add(grade)
                await session.flush()
                grades_by_level[level] = grade
            for class_number in range(1, class_count + 1):
                class_name = f"{class_prefix}({class_number})班"
                school_class = classes_by_name.get(class_name)
                if school_class is None:
                    school_class = Class(tenant_id=tenant_id, grade_id=grade.id, name=class_name)
                    session.add(school_class)
                    await session.flush()
                    classes_by_name[class_name] = school_class
                target_classes.append(school_class)
                full_class_cutoff = 40 if level == 1 else 39
                target_size = 40 if class_number <= full_class_cutoff else 39
                target_class_specs.append((school_class, level, class_number, target_size))

        subjects_by_name = {
            subject.name: subject for subject in (await session.execute(select(Subject))).scalars()
        }
        for subject_name, _, _ in SUBJECT_PLAN:
            if subject_name not in subjects_by_name:
                subject = Subject(name=subject_name)
                session.add(subject)
                await session.flush()
                subjects_by_name[subject_name] = subject

        teacher_specs: list[tuple[str, int]] = []
        next_new_teacher_number = 55
        for subject_name, _, teacher_count in SUBJECT_PLAN:
            phone_numbers = list(LEGACY_TEACHER_RANGES[subject_name])
            missing_count = teacher_count - len(phone_numbers)
            phone_numbers.extend(range(next_new_teacher_number, next_new_teacher_number + missing_count))
            next_new_teacher_number += missing_count
            teacher_specs.extend((subject_name, number) for number in phone_numbers)
        teacher_phones = [f"1882026{number:04d}" for _, number in teacher_specs]
        existing_teachers = {
            teacher.phone: teacher
            for teacher in (
                await session.execute(
                    select(User).where(User.tenant_id == tenant_id, User.phone.in_(teacher_phones))
                )
            ).scalars()
        }
        shared_password_hash = get_password_hash("Teacher@2026")
        subject_teachers: dict[str, list[User]] = defaultdict(list)
        for subject_name, teacher_number in teacher_specs:
                phone = f"1882026{teacher_number:04d}"
                teacher = existing_teachers.get(phone)
                if teacher is None:
                    teacher = User(
                        tenant_id=tenant_id,
                        name=person_name(6000 + teacher_number),
                        phone=phone,
                        password_hash=shared_password_hash,
                        role=BaseUserRole.teacher,
                    )
                    session.add(teacher)
                    await session.flush()
                    existing_teachers[phone] = teacher
                subject_teachers[subject_name].append(teacher)

        existing_assignment_rows = list(
            (
                await session.execute(
                    select(TeachingAssignment).where(
                        TeachingAssignment.tenant_id == tenant_id,
                        TeachingAssignment.academic_year == ACADEMIC_YEAR,
                        TeachingAssignment.term == TERM,
                    )
                )
            ).scalars()
        )
        existing_assignments = {
            (item.teacher_id, item.subject_id, item.class_id, item.academic_year, item.term)
            for item in existing_assignment_rows
        }
        existing_class_subjects = {(item.class_id, item.subject_id): item for item in existing_assignment_rows}
        teacher_loads: dict[int, int] = defaultdict(int)
        for item in existing_assignment_rows:
            teacher_loads[item.teacher_id] += item.weekly_periods
        assignments_by_class: dict[int, list[int]] = defaultdict(list)
        added_assignments = 0
        for school_class in target_classes:
            for subject_name, weekly_periods, _ in SUBJECT_PLAN:
                subject = subjects_by_name[subject_name]
                teachers = subject_teachers[subject_name]
                covered = existing_class_subjects.get((school_class.id, subject.id))
                if covered is not None:
                    assignments_by_class[school_class.id].append(covered.teacher_id)
                    continue
                teacher = min(teachers, key=lambda item: (teacher_loads[item.id], item.id))
                key = (teacher.id, subject.id, school_class.id, ACADEMIC_YEAR, TERM)
                assignments_by_class[school_class.id].append(teacher.id)
                if key not in existing_assignments:
                    session.add(
                        TeachingAssignment(
                            tenant_id=tenant_id,
                            teacher_id=teacher.id,
                            subject_id=subject.id,
                            class_id=school_class.id,
                            academic_year=ACADEMIC_YEAR,
                            term=TERM,
                            weekly_periods=weekly_periods,
                            room=school_class.name,
                        )
                    )
                    existing_assignments.add(key)
                    existing_class_subjects[(school_class.id, subject.id)] = True
                    teacher_loads[teacher.id] += weekly_periods
                    added_assignments += 1

        used_head_teachers: set[int] = set()
        for school_class in target_classes:
            if school_class.head_teacher_id is not None:
                used_head_teachers.add(school_class.head_teacher_id)
                continue
            candidates = assignments_by_class[school_class.id]
            school_class.head_teacher_id = next((teacher_id for teacher_id in candidates if teacher_id not in used_head_teachers), candidates[0])
            used_head_teachers.add(school_class.head_teacher_id)
            session.add(school_class)

        target_class_ids = [school_class.id for school_class in target_classes]
        existing_students = list(
            (
                await session.execute(
                    select(Student).where(Student.tenant_id == tenant_id, Student.class_id.in_(target_class_ids))
                )
            ).scalars()
        )
        students_by_class: dict[int, list[Student]] = defaultdict(list)
        existing_student_numbers = {student.student_no for student in existing_students if student.student_no}
        for student in existing_students:
            students_by_class[student.class_id].append(student)

        added_students = 0
        global_student_index = 0
        for class_position, (school_class, grade_level, class_number, target_size) in enumerate(target_class_specs):
            current_count = len(students_by_class[school_class.id])
            for roster_order in range(current_count + 1, target_size + 1):
                global_student_index = sum(spec[3] for spec in target_class_specs[:class_position]) + roster_order
                student_no = f"2026{grade_level:02d}{class_number:02d}{roster_order:02d}"
                if student_no in existing_student_numbers:
                    continue
                birth_year = 2010 - grade_level
                session.add(
                    Student(
                        tenant_id=tenant_id,
                        class_id=school_class.id,
                        name=person_name(global_student_index - 1),
                        gender=Gender.male if global_student_index % 2 else Gender.female,
                        birth_date=date(birth_year, randomizer.randint(1, 12), randomizer.randint(1, 28)),
                        parent_phone=f"177{global_student_index:08d}",
                        student_no=student_no,
                        roster_order=roster_order,
                    )
                )
                existing_student_numbers.add(student_no)
                added_students += 1

        await session.commit()

        director_phone = "18820269999"
        director = (
            await session.execute(
                select(User).where(User.tenant_id == tenant_id, User.phone == director_phone)
            )
        ).scalar_one_or_none()
        if director is None:
            director = User(
                tenant_id=tenant_id,
                name="教务测试管理员",
                phone=director_phone,
                password_hash=get_password_hash("Admin@2026"),
                role=BaseUserRole.director,
            )
            session.add(director)
            await session.flush()
        exam_specs = (
            ("2026-2027学年第一学期第一次月考", ExamType.monthly),
            ("2026-2027学年第一学期期中考试", ExamType.midterm),
            ("2026-2027学年第一学期期末考试", ExamType.final),
        )
        existing_exams = {
            exam.name: exam
            for exam in (
                await session.execute(select(Exam).where(Exam.tenant_id == tenant_id))
            ).scalars()
        }
        seeded_exams: list[Exam] = []
        for exam_name, exam_type in exam_specs:
            exam = existing_exams.get(exam_name)
            if exam is None:
                exam = Exam(
                    tenant_id=tenant_id,
                    name=exam_name,
                    exam_type=exam_type,
                    academic_year=ACADEMIC_YEAR,
                    created_by=director.id if director else None,
                    status=ExamStatus.preparing,
                )
                session.add(exam)
                await session.flush()
            seeded_exams.append(exam)

        existing_paper_keys = {
            (paper.exam_id, paper.grade_id, paper.subject_id)
            for paper in (
                await session.execute(
                    select(Paper).where(Paper.tenant_id == tenant_id, Paper.exam_id.in_([exam.id for exam in seeded_exams]))
                )
            ).scalars()
        }
        added_papers = 0
        for exam in seeded_exams:
            for grade in grades_by_level.values():
                for subject_name, _, _ in SUBJECT_PLAN:
                    subject = subjects_by_name[subject_name]
                    key = (exam.id, grade.id, subject.id)
                    if key in existing_paper_keys:
                        continue
                    teacher = subject_teachers[subject_name][(grade.level - 1) % len(subject_teachers[subject_name])]
                    session.add(
                        Paper(
                            tenant_id=tenant_id,
                            exam_id=exam.id,
                            subject_id=subject.id,
                            grade_id=grade.id,
                            teacher_id=teacher.id,
                            title=f"{exam.name}·{grade.name}{subject.name}试卷",
                            total_score=Decimal("150") if subject_name in {"语文", "数学", "英语"} else Decimal("100"),
                            status=PaperStatus.finalized,
                        )
                    )
                    existing_paper_keys.add(key)
                    added_papers += 1

        first_class = target_classes[0]
        existing_seat = (
            await session.execute(
                select(SeatArrangement).where(SeatArrangement.tenant_id == tenant_id, SeatArrangement.class_id == first_class.id)
            )
        ).scalars().first()
        if existing_seat is None:
            first_class_students = list(
                (
                    await session.execute(
                        select(Student).where(Student.tenant_id == tenant_id, Student.class_id == first_class.id).order_by(Student.roster_order)
                    )
                ).scalars()
            )
            seats = arrange_students(
                [student.model_dump() for student in first_class_students], rows=7, cols=6, order="roster", layout="snake"
            )
            session.add(
                SeatArrangement(
                    tenant_id=tenant_id,
                    class_id=first_class.id,
                    rows=7,
                    cols=6,
                    rule=SeatRule.roster,
                    layout=SeatLayout.snake,
                    student_map={"seats": [seat.__dict__ for seat in seats]},
                    effective_from=date(2026, 9, 1),
                    status=SeatStatus.active,
                    created_by=director.id if director else None,
                )
            )

        required_ids = [subjects_by_name[name].id for name in ("语文", "数学", "英语")]
        primary_ids = [subjects_by_name[name].id for name in ("物理", "历史")]
        secondary_ids = [subjects_by_name[name].id for name in ("化学", "生物", "政治", "地理")]
        schemes_by_year = {
            item.entry_year: item for item in (
                await session.execute(select(GaokaoScheme).where(GaokaoScheme.tenant_id == tenant_id))
            ).scalars()
        }
        for entry_year in (2024, 2025, 2026):
            if entry_year not in schemes_by_year:
                scheme = GaokaoScheme(
                    tenant_id=tenant_id,
                    name=f"{entry_year}级3+1+2新高考方案",
                    province="全国通用测试",
                    mode="3+1+2",
                    entry_year=entry_year,
                    required_subject_ids=required_ids,
                    primary_subject_ids=primary_ids,
                    secondary_subject_ids=secondary_ids,
                    is_active=True,
                )
                session.add(scheme)
                await session.flush()
                schemes_by_year[entry_year] = scheme

        combination_names = [
            ("物理", ("化学", "生物")), ("物理", ("化学", "生物")),
            ("物理", ("化学", "地理")), ("物理", ("化学", "政治")),
            ("物理", ("生物", "地理")), ("物理", ("生物", "政治")),
            ("物理", ("政治", "地理")),
            ("历史", ("化学", "生物")), ("历史", ("化学", "地理")),
            ("历史", ("化学", "政治")), ("历史", ("生物", "地理")),
            ("历史", ("生物", "政治")), ("历史", ("政治", "地理")),
        ]
        existing_choice_students = set((await session.execute(select(StudentSubjectChoice.student_id).where(
            StudentSubjectChoice.tenant_id == tenant_id,
            StudentSubjectChoice.academic_year == ACADEMIC_YEAR,
            StudentSubjectChoice.effective_term == TERM,
        ))).scalars().all())
        class_levels = {school_class.id: level for school_class, level, _, _ in target_class_specs}
        all_students = list((await session.execute(select(Student).where(
            Student.tenant_id == tenant_id,
            Student.class_id.in_([item.id for item in target_classes]),
        ).order_by(Student.id))).scalars().all())
        added_choices = 0
        for index, student in enumerate(all_students):
            if student.id in existing_choice_students:
                continue
            primary_name, secondary_names = combination_names[index % len(combination_names)]
            level = class_levels[student.class_id]
            scheme = schemes_by_year[2027 - level]
            session.add(StudentSubjectChoice(
                tenant_id=tenant_id,
                student_id=student.id,
                scheme_id=scheme.id,
                academic_year=ACADEMIC_YEAR,
                effective_term=TERM,
                round_no=1,
                primary_subject_id=subjects_by_name[primary_name].id,
                secondary_subject_ids=[subjects_by_name[name].id for name in secondary_names],
                status="confirmed",
            ))
            added_choices += 1
        await session.commit()

        final_students = len(
            (
                await session.execute(
                    select(Student.id).where(Student.tenant_id == tenant_id, Student.class_id.in_(target_class_ids))
                )
            ).scalars().all()
        )
        print(
            f"tenant={tenant.code} classes={len(target_classes)} students={final_students} "
            f"teachers={sum(len(items) for items in subject_teachers.values())} "
            f"assignments={len(target_classes) * len(SUBJECT_PLAN)} exams={len(seeded_exams)} "
            f"papers={len(existing_paper_keys)} choices={len(existing_choice_students) + added_choices} "
            f"added_students={added_students} added_assignments={added_assignments} "
            f"added_papers={added_papers} added_choices={added_choices}"
        )


if __name__ == "__main__":
    asyncio.run(seed())
