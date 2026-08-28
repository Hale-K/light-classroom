"""Create idempotent high-one paper-library fixtures for a demo school."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models.enums import ExamStatus, ExamType, PaperStatus
from app.models.exam import Exam, Paper
from app.models.org import Class, Grade, Student, Subject, TeachingAssignment, Tenant, User


ACADEMIC_YEAR = "2026-2027"
EXAM_SPECS = (
    ("高一上学期第一次月考", ExamType.monthly),
    ("高一上学期期中考试", ExamType.midterm),
    ("高一上学期期末考试", ExamType.final),
    ("高一上学期综合模拟", ExamType.mock),
)
SUBJECTS = ("语文", "数学", "英语", "物理", "历史", "化学", "生物", "政治", "地理")


async def seed(school_code: str) -> None:
    engine.echo = False
    async with AsyncSessionLocal() as session:
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
            raise SystemExit("未找到有学生的高一年级")
        subject_map = {item.name: item for item in (await session.execute(select(Subject))).scalars().all()}
        missing = [name for name in SUBJECTS if name not in subject_map]
        if missing:
            raise SystemExit(f"缺少学科：{', '.join(missing)}")
        creator = (await session.execute(select(User).where(
            User.tenant_id == tenant.id,
            User.role == "director",
        ).order_by(User.id))).scalars().first()
        assignments = list((await session.execute(select(TeachingAssignment).where(
            TeachingAssignment.tenant_id == tenant.id,
            TeachingAssignment.class_id.in_(select(Class.id).where(Class.tenant_id == tenant.id, Class.grade_id == grade.id)),
            TeachingAssignment.academic_year == ACADEMIC_YEAR,
            TeachingAssignment.term == "1",
        ))).scalars().all())
        teacher_by_subject = {}
        for assignment in assignments:
            teacher_by_subject.setdefault(assignment.subject_id, assignment.teacher_id)
        existing_exams = {item.name: item for item in (await session.execute(select(Exam).where(Exam.tenant_id == tenant.id))).scalars().all()}
        existing_papers = {(item.exam_id, item.subject_id, item.grade_id): item for item in (await session.execute(select(Paper).where(Paper.tenant_id == tenant.id))).scalars().all()}
        created_exams = 0
        created_papers = 0
        for exam_name, exam_type in EXAM_SPECS:
            exam = existing_exams.get(exam_name)
            if exam is None:
                exam = Exam(
                    tenant_id=tenant.id,
                    name=exam_name,
                    exam_type=exam_type,
                    academic_year=ACADEMIC_YEAR,
                    created_by=creator.id if creator else None,
                    status=ExamStatus.preparing,
                )
                session.add(exam)
                await session.flush()
                existing_exams[exam_name] = exam
                created_exams += 1
            for subject_name in SUBJECTS:
                subject = subject_map[subject_name]
                key = (exam.id, subject.id, grade.id)
                if key in existing_papers:
                    continue
                core = subject_name in {"语文", "数学", "英语"}
                paper = Paper(
                    tenant_id=tenant.id,
                    exam_id=exam.id,
                    subject_id=subject.id,
                    grade_id=grade.id,
                    teacher_id=teacher_by_subject.get(subject.id),
                    title=f"{exam_name}·高一{subject_name}试卷",
                    total_score=150 if core else 100,
                    status=PaperStatus.finalized if exam_type in {ExamType.midterm, ExamType.final} else PaperStatus.building,
                    exam_year=2026,
                )
                session.add(paper)
                existing_papers[key] = paper
                created_papers += 1
        await session.commit()
        print(f"目标年级：{grade.name}（{grade.id}）")
        print(f"新增考试：{created_exams} 场")
        print(f"新增试卷：{created_papers} 张")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("school_code", nargs="?", default="gaokao312")
    args = parser.parse_args()
    asyncio.run(seed(args.school_code))
