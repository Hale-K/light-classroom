"""Create deterministic, unassigned student records for one campus."""
from __future__ import annotations

import argparse
import asyncio
from datetime import date

from sqlalchemy import delete, select

from app.db.session import AsyncSessionLocal, engine
from app.models.enums import Gender, StudentStatus
from app.models.facility import Campus
from app.models.org import Grade, Student, Tenant


SURNAMES = (
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
    "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
)
GIVEN_NAMES = (
    "子涵", "宇轩", "浩然", "雨桐", "欣怡", "嘉怡", "梓轩", "思源", "明哲", "佳宁",
    "俊杰", "诗涵", "文博", "若曦", "泽宇", "梦瑶", "天佑", "语彤", "奕辰", "可欣",
)

GIVEN_NAME_CHARS = (
    "子", "宇", "浩", "雨", "欣", "嘉", "梓", "思", "明", "佳",
    "俊", "诗", "文", "若", "泽", "梦", "天", "语", "奕", "可",
)

UNIQUE_SURNAMES = (
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
    "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
    "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧",
    "程", "曹", "袁", "邓", "许", "傅", "沈", "曾", "彭", "吕",
    "苏", "卢", "蒋", "蔡", "贾", "丁", "魏", "薛", "叶", "阎",
    "余", "潘", "杜", "戴", "夏", "钟", "汪", "田", "任", "姜",
    "范", "方", "石", "姚", "谭", "廖", "邹", "熊", "金", "陆",
    "郝", "孔", "白", "崔", "康", "毛", "邱", "秦", "江", "史",
    "顾", "侯", "邵", "孟", "龙", "万", "段", "雷", "钱", "汤",
    "尹", "黎", "易", "常", "武", "乔", "贺", "赖", "龚", "文",
)
UNIQUE_GIVEN_NAMES = (
    "子涵", "宇轩", "浩然", "雨桐", "欣怡", "嘉怡", "梓轩", "思源", "明哲", "佳宁",
    "俊杰", "诗涵", "文博", "若曦", "泽宇", "梦瑶", "天佑", "语嫣", "奕辰", "可欣",
    "晨曦", "睿哲", "安然", "子墨", "思远", "嘉禾", "亦凡", "清妍", "景行", "知夏",
    "星辰", "书瑶", "锦程", "沐阳", "语桐", "皓轩", "婉清", "一诺", "予安", "云舒",
    "怀瑾", "知远", "允和", "令仪", "昭宁", "砚秋", "承宇", "以宁", "南乔", "君泽",
    "清越", "安歌", "望舒", "慕言", "时雨", "若安", "景明", "修远", "嘉言", "云帆",
)


def grade_population(total: int, grade_count: int) -> list[int]:
    if total < 1 or grade_count < 1:
        raise ValueError("total and grade_count must be positive")
    base, remainder = divmod(total, grade_count)
    return [base + (1 if index < remainder else 0) for index in range(grade_count)]


def student_name(index: int) -> str:
    capacity = len(UNIQUE_SURNAMES) * len(UNIQUE_GIVEN_NAMES)
    if index < 0 or index >= capacity:
        raise ValueError(f"student name index must be between 0 and {capacity - 1}")
    surname = UNIQUE_SURNAMES[index % len(UNIQUE_SURNAMES)]
    given_name = UNIQUE_GIVEN_NAMES[index // len(UNIQUE_SURNAMES)]
    return surname + given_name


async def seed(
    school_code: str,
    campus_name: str,
    total: int,
    replace_existing: bool = False,
) -> None:
    engine.echo = False
    async with AsyncSessionLocal() as session:
        school = (await session.execute(select(Tenant).where(
            Tenant.code == school_code,
        ))).scalar_one_or_none()
        if school is None:
            raise SystemExit(f"School not found: {school_code}")

        campus = (await session.execute(select(Campus).where(
            Campus.tenant_id == school.id,
            Campus.name == campus_name,
        ))).scalar_one_or_none()
        if campus is None:
            raise SystemExit(f"Campus not found: {campus_name}")

        grades = list((await session.execute(select(Grade).where(
            Grade.tenant_id == school.id,
            Grade.campus_id == campus.id,
        ).order_by(Grade.level))).scalars().all())
        if [grade.level for grade in grades] != [1, 2, 3]:
            raise SystemExit("The campus must have exactly grade levels 1, 2 and 3.")

        prefix = "CY1"
        existing = list((await session.execute(select(Student).where(
            Student.tenant_id == school.id,
            Student.student_no.like(f"{prefix}-G%"),
        ))).scalars().all())
        if replace_existing:
            await session.execute(delete(Student).where(
                Student.tenant_id == school.id,
                Student.campus_id == campus.id,
            ))
            existing = []
        existing_by_number = {student.student_no: student for student in existing}

        created = 0
        global_index = 0
        counts = grade_population(total, len(grades))
        for grade, count in zip(grades, counts, strict=True):
            birth_year = 2011 - grade.level
            for sequence in range(1, count + 1):
                global_index += 1
                student_no = f"{prefix}-G{grade.level}-{sequence:04d}"
                values = {
                    "campus_id": campus.id,
                    "grade_id": grade.id,
                    "class_id": None,
                    "name": student_name(global_index - 1),
                    "gender": Gender.male if global_index % 2 else Gender.female,
                    "birth_date": date(
                        birth_year,
                        global_index % 12 + 1,
                        global_index % 28 + 1,
                    ),
                    "parent_phone": f"139{global_index:08d}",
                    "height_cm": float(150 + global_index % 37),
                    "roster_order": sequence,
                    "status": StudentStatus.studying,
                }
                student = existing_by_number.get(student_no)
                if student is None:
                    session.add(Student(
                        tenant_id=school.id,
                        student_no=student_no,
                        **values,
                    ))
                    created += 1
                else:
                    for field, value in values.items():
                        setattr(student, field, value)

        await session.commit()
        print(f"school={school.code} campus={campus.name}")
        print(f"students={total} created={created} unassigned={total}")
        print(f"grade_counts={counts}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-code", required=True)
    parser.add_argument("--campus-name", required=True)
    parser.add_argument("--total", type=int, default=5000)
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args()
    asyncio.run(seed(
        args.school_code,
        args.campus_name,
        args.total,
        replace_existing=args.replace_existing,
    ))


if __name__ == "__main__":
    main()
