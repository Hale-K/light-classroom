"""Seed two-campus grade, administrative-class and home-room planning.

The operation is idempotent: existing campuses are reused and matching grades,
buildings, rooms and administrative classes are updated instead of duplicated.
It creates planning records only; it does not create student identities.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.facility import Building, Campus, Room
from app.models.org import Class, Grade, Tenant


@dataclass(frozen=True)
class CampusPlan:
    expected_name: str
    student_capacity: int
    campus_code: str
    building_classroom_counts: tuple[int, ...]


PLANS = (
    CampusPlan("崇仁一中", 5000, "CY1", (29, 29, 28, 28)),
    CampusPlan("崇仁二中", 6000, "CY2", (34, 34, 34, 33)),
)
GRADE_LABELS = {1: "高一", 2: "高二", 3: "高三"}


def balanced_sizes(student_count: int, class_count: int) -> list[int]:
    """Distribute students with a difference of at most one per class."""
    base, remainder = divmod(student_count, class_count)
    sizes = [base + 1] * remainder + [base] * (class_count - remainder)
    if not sizes or min(sizes) < 1 or max(sizes) > 45:
        raise ValueError(
            f"Invalid class plan: students={student_count}, classes={class_count}, sizes={sizes[:3]}"
        )
    return sizes


async def get_or_create_building(session, tenant_id: int, campus: Campus, *, name: str, code: str):
    item = (await session.execute(select(Building).where(
        Building.tenant_id == tenant_id,
        Building.campus_id == campus.id,
        Building.name == name,
    ))).scalar_one_or_none()
    if item is None:
        item = Building(
            tenant_id=tenant_id,
            campus_id=campus.id,
            name=name,
            code=code,
            floor_count=7,
            status="active",
        )
        session.add(item)
        await session.flush()
    else:
        item.code = code
        item.floor_count = 7
        item.status = "active"
    return item


async def get_or_create_room(
    session,
    tenant_id: int,
    building: Building,
    *,
    name: str,
    code: str,
    floor: int,
    capacity: int,
    multimedia: bool = False,
) -> Room:
    item = (await session.execute(select(Room).where(
        Room.tenant_id == tenant_id,
        Room.building_id == building.id,
        Room.name == name,
    ))).scalar_one_or_none()
    values = {
        "code": code,
        "floor": floor,
        "capacity": capacity,
        "room_type": "classroom",
        "features": ["multimedia"] if multimedia else [],
        "is_schedulable": True,
        "is_exam_enabled": True,
        "is_meeting_enabled": multimedia,
        "status": "available",
    }
    if item is None:
        item = Room(tenant_id=tenant_id, building_id=building.id, name=name, **values)
        session.add(item)
        await session.flush()
    else:
        for field, value in values.items():
            setattr(item, field, value)
    return item


async def get_or_create_grade(session, tenant_id: int, campus: Campus, level: int) -> Grade:
    item = (await session.execute(select(Grade).where(
        Grade.tenant_id == tenant_id,
        Grade.campus_id == campus.id,
        Grade.level == level,
    ))).scalar_one_or_none()
    name = f"{campus.name}·{GRADE_LABELS[level]}年级"
    if item is None:
        item = Grade(
            tenant_id=tenant_id,
            campus_id=campus.id,
            name=name,
            level=level,
        )
        session.add(item)
        await session.flush()
    else:
        item.name = name
    return item


async def get_or_create_class(
    session,
    tenant_id: int,
    campus: Campus,
    grade: Grade,
    *,
    sequence: int,
    planned_student_count: int,
    room: Room,
) -> Class:
    name = f"{campus.name}·{GRADE_LABELS[grade.level]}（{sequence}）班"
    item = (await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.grade_id == grade.id,
        Class.name == name,
    ))).scalar_one_or_none()
    if item is None:
        item = Class(
            tenant_id=tenant_id,
            grade_id=grade.id,
            campus_id=campus.id,
            home_room_id=room.id,
            planned_student_count=planned_student_count,
            name=name,
        )
        session.add(item)
    else:
        item.campus_id = campus.id
        item.home_room_id = room.id
        item.planned_student_count = planned_student_count
    return item


async def resolve_campuses(session, tenant_id: int) -> list[tuple[Campus, CampusPlan]]:
    campuses = list((await session.execute(select(Campus).where(
        Campus.tenant_id == tenant_id,
    ).order_by(Campus.id))).scalars().all())
    if len(campuses) < 2:
        raise SystemExit("Two existing campuses are required before running this seed.")

    by_name = {item.name: item for item in campuses}
    unused = [item for item in campuses]
    result: list[tuple[Campus, CampusPlan]] = []
    for plan in PLANS:
        campus = by_name.get(plan.expected_name)
        if campus is None:
            campus = next(item for item in unused if item not in [row[0] for row in result])
        result.append((campus, plan))
    return result


async def seed(school_code: str) -> None:
    async with AsyncSessionLocal() as session:
        school = (await session.execute(select(Tenant).where(
            Tenant.code == school_code,
        ))).scalar_one_or_none()
        if school is None:
            raise SystemExit(f"School not found: {school_code}")

        summaries: list[str] = []
        for campus, plan in await resolve_campuses(session, school.id):
            campus.student_capacity = plan.student_capacity
            campus.status = "active"

            buildings: list[Building] = []
            rooms: list[Room] = []
            global_room_sequence = 1
            for building_index, room_count in enumerate(plan.building_classroom_counts, start=1):
                building = await get_or_create_building(
                    session,
                    school.id,
                    campus,
                    name=f"第{building_index}教学楼",
                    code=f"{plan.campus_code}-T{building_index}",
                )
                buildings.append(building)
                for local_index in range(room_count):
                    floor = local_index // 5 + 1
                    door_number = floor * 100 + local_index % 5 + 1
                    rooms.append(await get_or_create_room(
                        session,
                        school.id,
                        building,
                        name=f"行政班固定教室{global_room_sequence:03d}",
                        code=f"{building.code}-{door_number}",
                        floor=floor,
                        capacity=45,
                    ))
                    global_room_sequence += 1

            for multimedia_index in range(1, 3):
                await get_or_create_room(
                    session,
                    school.id,
                    buildings[0],
                    name=f"多媒体教室{multimedia_index}",
                    code=f"{plan.campus_code}-MM{multimedia_index:02d}",
                    floor=multimedia_index,
                    capacity=60,
                    multimedia=True,
                )

            grade_student_counts = (
                (1667, 1667, 1666) if plan.student_capacity == 5000 else (2000, 2000, 2000)
            )
            grade_class_counts = (
                (38, 38, 38) if plan.student_capacity == 5000 else (45, 45, 45)
            )
            room_cursor = 0
            for level, (student_count, class_count) in enumerate(
                zip(grade_student_counts, grade_class_counts, strict=True), start=1
            ):
                grade = await get_or_create_grade(session, school.id, campus, level)
                for sequence, planned_size in enumerate(
                    balanced_sizes(student_count, class_count), start=1
                ):
                    room = rooms[room_cursor]
                    await get_or_create_class(
                        session,
                        school.id,
                        campus,
                        grade,
                        sequence=sequence,
                        planned_student_count=planned_size,
                        room=room,
                    )
                    room_cursor += 1

            summaries.append(
                f"{campus.name}: students={plan.student_capacity}, "
                f"classes={sum(grade_class_counts)}, buildings={len(buildings)}, "
                "multimedia=2"
            )

        await session.commit()
        print(f"school={school.code} tenant_id={school.id}")
        for summary in summaries:
            print(summary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-code", required=True)
    args = parser.parse_args()
    asyncio.run(seed(args.school_code))


if __name__ == "__main__":
    main()
