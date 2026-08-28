"""Verify generated student counts by campus and grade."""
from __future__ import annotations

import argparse

from sqlalchemy import create_engine, text

from app.core.config import settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-code", required=True)
    parser.add_argument("--campus-name", required=True)
    args = parser.parse_args()

    engine = create_engine(settings.database_url.replace("+asyncpg", ""))
    with engine.connect() as connection:
        rows = connection.execute(text("""
            select grade.level,
                   count(student.id) as student_count,
                   count(student.class_id) as assigned_count
            from student
            join tenant on tenant.id = student.tenant_id
            join campus on campus.id = student.campus_id
            join grade on grade.id = student.grade_id
            where tenant.code = :school_code
              and campus.name = :campus_name
            group by grade.level
            order by grade.level
        """), {
            "school_code": args.school_code,
            "campus_name": args.campus_name,
        }).all()
    print([tuple(row) for row in rows])
    print(f"total={sum(row.student_count for row in rows)}")
    print(f"assigned={sum(row.assigned_count for row in rows)}")


if __name__ == "__main__":
    main()
