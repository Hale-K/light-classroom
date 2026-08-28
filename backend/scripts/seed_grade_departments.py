"""Create the three grade departments for an academic year."""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.org import OrganizationUnit, Tenant


async def seed(school_code: str, academic_year: str) -> None:
    start_year = int(academic_year.split("-", 1)[0])
    grade_specs = (
        (1, start_year + 3, "高一"),
        (2, start_year + 2, "高二"),
        (3, start_year + 1, "高三"),
    )

    async with AsyncSessionLocal() as session:
        school = (await session.execute(
            select(Tenant).where(Tenant.code == school_code)
        )).scalar_one_or_none()
        if school is None:
            raise SystemExit(f"School not found: {school_code}")

        parent = (await session.execute(select(OrganizationUnit).where(
            OrganizationUnit.tenant_id == school.id,
            OrganizationUnit.name == "年级管理中心",
            OrganizationUnit.status == "active",
        ))).scalar_one_or_none()
        if parent is None:
            raise SystemExit("Organization unit not found: 年级管理中心")

        created: list[str] = []
        for grade_level, graduation_year, grade_name in grade_specs:
            cohort_label = f"{graduation_year}届"
            name = f"{cohort_label}{grade_name}年级部"
            item = (await session.execute(select(OrganizationUnit).where(
                OrganizationUnit.tenant_id == school.id,
                OrganizationUnit.parent_id == parent.id,
                OrganizationUnit.academic_year == academic_year,
                OrganizationUnit.cohort_label == cohort_label,
            ))).scalar_one_or_none()
            if item is None:
                session.add(OrganizationUnit(
                    tenant_id=school.id,
                    parent_id=parent.id,
                    name=name,
                    unit_type="grade_group",
                    academic_year=academic_year,
                    cohort_label=cohort_label,
                    sort_order=grade_level * 10,
                    status="active",
                ))
                created.append(name)
            else:
                item.name = name
                item.sort_order = grade_level * 10
                item.status = "active"

        await session.commit()
        print(f"school={school.code} academic_year={academic_year}")
        print(f"created={len(created)}")
        for name in created:
            print(f"+ {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-code", required=True)
    parser.add_argument("--academic-year", required=True, help="Example: 2026-2027")
    args = parser.parse_args()
    asyncio.run(seed(args.school_code, args.academic_year))


if __name__ == "__main__":
    main()
