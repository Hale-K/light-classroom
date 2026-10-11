"""Read exam capacity from the school's physical space inventory."""
from collections import Counter

from sqlalchemy import select

from app.models.exam import ExamRoom
from app.models.facility import Building, Campus, Room


async def exam_room_catalog(session, tenant_id):
    spaces = list((await session.execute(select(Room).where(
        Room.tenant_id == tenant_id).order_by(Room.building_id, Room.floor, Room.id))).scalars().all())
    if not spaces:
        # Keep explicitly registered historical exam rooms usable during migration.
        # Never manufacture classroom names or capacities from class records.
        return list((await session.execute(select(ExamRoom).where(
            ExamRoom.tenant_id == tenant_id, ExamRoom.is_deleted == False  # noqa: E712
        ).order_by(ExamRoom.id))).scalars().all())
    buildings = {b.id: b for b in (await session.execute(select(Building).where(
        Building.tenant_id == tenant_id))).scalars().all()}
    campuses = {c.id: c for c in (await session.execute(select(Campus).where(
        Campus.tenant_id == tenant_id))).scalars().all()}
    counts = Counter(r.name for r in spaces)
    result = []
    for room in spaces:
        # Ordinary classrooms are usable for school-wide exams when classes stop.
        # Other spaces require explicit exam enablement (e.g. labs or meeting rooms).
        if room.room_type != 'classroom' and not room.is_exam_enabled:
            continue
        building = buildings.get(room.building_id)
        campus = campuses.get(building.campus_id) if building else None
        status = room.status
        if not building or not campus or building.status != 'active' or campus.status != 'active':
            status = 'disabled'
        name = room.name if counts[room.name] == 1 else f'{building.name if building else room.building_id} · {room.name} [#{room.id}]'
        result.append(ExamRoom(id=room.id, tenant_id=tenant_id, name=name,
            capacity=room.capacity, building=building.name if building else None,
            room_type='standard' if room.room_type == 'classroom' else 'special', status=status))
    return result
