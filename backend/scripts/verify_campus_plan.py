"""Print compact aggregate checks for the seeded campus plan."""
from __future__ import annotations

import argparse

from sqlalchemy import create_engine, text

from app.core.config import settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-code", required=True)
    args = parser.parse_args()
    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    with engine.connect() as connection:
        tenant_id = connection.execute(
            text("select id from tenant where code = :code"), {"code": args.school_code}
        ).scalar_one()
        campuses = connection.execute(text("""
            select campus.id, campus.name, campus.student_capacity,
                   count(distinct building.id) as building_count,
                   count(distinct room.id) as room_count,
                   count(distinct class.id) as class_count
            from campus
            left join building on building.campus_id = campus.id
            left join room on room.building_id = building.id
            left join class on class.campus_id = campus.id
            where campus.tenant_id = :tenant_id
            group by campus.id
            order by campus.id
        """), {"tenant_id": tenant_id}).all()
        class_plans = connection.execute(text("""
            select campus_id, sum(planned_student_count), min(planned_student_count),
                   max(planned_student_count), count(distinct home_room_id)
            from class
            where tenant_id = :tenant_id and campus_id is not null
            group by campus_id
            order by campus_id
        """), {"tenant_id": tenant_id}).all()
        grades = connection.execute(text("""
            select campus_id, level, count(id)
            from grade
            where tenant_id = :tenant_id and campus_id is not null
            group by campus_id, level
            order by campus_id, level
        """), {"tenant_id": tenant_id}).all()
        multimedia_count = connection.execute(text("""
            select count(id) from room
            where tenant_id = :tenant_id and features::text like '%multimedia%'
        """), {"tenant_id": tenant_id}).scalar_one()

    print("campuses", [tuple(row) for row in campuses])
    print("grades", [tuple(row) for row in grades])
    print("class_plans", [tuple(row) for row in class_plans])
    print("multimedia", multimedia_count)


if __name__ == "__main__":
    main()
