"""Create the reusable, permanent organization skeleton for one school."""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.org import OrganizationUnit, Tenant


async def ensure_unit(
    session,
    *,
    tenant_id: int,
    name: str,
    unit_type: str,
    sort_order: int,
    parent_id: int | None = None,
) -> tuple[OrganizationUnit, bool]:
    item = (await session.execute(select(OrganizationUnit).where(
        OrganizationUnit.tenant_id == tenant_id,
        OrganizationUnit.parent_id == parent_id,
        OrganizationUnit.name == name,
    ))).scalar_one_or_none()
    if item is not None:
        if item.status != "active":
            item.status = "active"
        return item, False
    item = OrganizationUnit(
        tenant_id=tenant_id,
        parent_id=parent_id,
        name=name,
        unit_type=unit_type,
        sort_order=sort_order,
        status="active",
    )
    session.add(item)
    await session.flush()
    return item, True


async def seed(school_code: str) -> None:
    async with AsyncSessionLocal() as session:
        school = (await session.execute(
            select(Tenant).where(Tenant.code == school_code)
        )).scalar_one_or_none()
        if school is None:
            raise SystemExit(f"School not found: {school_code}")

        created: list[str] = []
        for name, order in (("校级管理", 10), ("德育处", 30)):
            _, was_created = await ensure_unit(
                session, tenant_id=school.id, name=name,
                unit_type="department", sort_order=order,
            )
            if was_created:
                created.append(name)

        academic, was_created = await ensure_unit(
            session, tenant_id=school.id, name="教务处",
            unit_type="department", sort_order=20,
        )
        if was_created:
            created.append("教务处")

        grade_center, was_created = await ensure_unit(
            session, tenant_id=school.id, parent_id=academic.id,
            name="年级管理中心", unit_type="department", sort_order=10,
        )
        if was_created:
            created.append("教务处 / 年级管理中心")

        subject_center, was_created = await ensure_unit(
            session, tenant_id=school.id, parent_id=academic.id,
            name="学科教研中心", unit_type="department", sort_order=20,
        )
        if was_created:
            created.append("教务处 / 学科教研中心")

        subjects = ("语文", "数学", "英语", "物理", "历史", "化学", "生物", "政治", "地理")
        for order, subject in enumerate(subjects, start=1):
            name = f"{subject}教研组"
            _, was_created = await ensure_unit(
                session, tenant_id=school.id, parent_id=subject_center.id,
                name=name, unit_type="subject_group", sort_order=order * 10,
            )
            if was_created:
                created.append(f"教务处 / 学科教研中心 / {name}")

        await session.commit()
        print(f"school={school.name} code={school.code}")
        print(f"created={len(created)}")
        for path in created:
            print(f"+ {path}")
        print(f"grade_parent_id={grade_center.id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-code", required=True)
    args = parser.parse_args()
    asyncio.run(seed(args.school_code))


if __name__ == "__main__":
    main()
