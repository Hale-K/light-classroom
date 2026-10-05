"""为未提交学生生成可重复的 3+1+2 模拟选科，不覆盖已有记录。"""
import asyncio
import os
import random

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.gaokao import GaokaoScheme, StudentSubjectChoice
from app.models.org import Student, Tenant, TenantConfig


SCHOOL_CODE = os.getenv("SCHOOL_CODE", "nstmy")
RANDOM_SEED = 20261005


async def main() -> None:
    rng = random.Random(RANDOM_SEED)
    async with AsyncSessionLocal() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.code == SCHOOL_CODE))).scalars().first()
        if tenant is None:
            raise RuntimeError(f"学校不存在：{SCHOOL_CODE}")

        config = (await session.execute(select(TenantConfig).where(
            TenantConfig.tenant_id == tenant.id,
            TenantConfig.config_key == "academic_years",
        ))).scalars().first()
        values = config.config_value if config and isinstance(config.config_value, dict) else {}
        academic_year = str(values.get("current_academic_year") or "2026-2027")
        term = str(values.get("current_term") or "2")
        scheme = (await session.execute(select(GaokaoScheme).where(
            GaokaoScheme.tenant_id == tenant.id,
            GaokaoScheme.is_active == True,  # noqa: E712
        ).order_by(GaokaoScheme.entry_year.desc()))).scalars().first()
        if scheme is None or scheme.mode != "3+1+2":
            raise RuntimeError("当前学校没有可用的 3+1+2 选科方案")
        if len(scheme.primary_subject_ids) != 2 or len(scheme.secondary_subject_ids) < 2:
            raise RuntimeError("选科方案的首选或再选科目配置不完整")

        students = list((await session.execute(select(Student).where(
            Student.tenant_id == tenant.id,
        ).order_by(Student.id))).scalars().all())
        existing = set((await session.execute(select(StudentSubjectChoice.student_id).where(
            StudentSubjectChoice.tenant_id == tenant.id,
            StudentSubjectChoice.academic_year == academic_year,
            StudentSubjectChoice.effective_term == term,
        ))).scalars().all())

        created = []
        for student in students:
            if student.id in existing:
                continue
            primary = rng.choice(scheme.primary_subject_ids)
            secondary = rng.sample(scheme.secondary_subject_ids, 2)
            created.append(StudentSubjectChoice(
                tenant_id=tenant.id,
                student_id=student.id,
                scheme_id=scheme.id,
                academic_year=academic_year,
                effective_term=term,
                primary_subject_id=primary,
                secondary_subject_ids=secondary,
                selected_subject_ids=[primary, *sorted(secondary)],
                status="confirmed",
            ))
        session.add_all(created)
        await session.commit()
        print({
            "school": SCHOOL_CODE,
            "academic_year": academic_year,
            "term": term,
            "total_students": len(students),
            "existing_choices": len(existing),
            "created_choices": len(created),
            "seed": RANDOM_SEED,
        })


if __name__ == "__main__":
    asyncio.run(main())
