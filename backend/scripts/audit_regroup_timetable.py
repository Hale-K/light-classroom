"""Read-only audit of persisted public + walk timetables; writes no data files."""
import argparse
import asyncio
from collections import Counter, defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, text
from app.db.session import AsyncSessionLocal, engine, tenant_id_ctx
from app.api.v1.gaokao import WalkRegroupAutoIn, _regroup_roster
from app.api.v1.scheduling import GenerateIn, _generation_assignment_payloads, _load_rule_group
from app.models.org import User, Schedule, StudentClassMembership
from app.models.gaokao import TeachingClass, TeachingClassStudent, TeachingClassSchedule
from app.services.scheduling.walk_regroup_save import validate_candidate_rules


async def audit(args):
    async with AsyncSessionLocal() as session:
        await session.execute(text('SET TRANSACTION READ ONLY'))
        user = (await session.execute(select(User).where(User.phone == args.phone))).scalar_one()
        token = tenant_id_ctx.set(user.tenant_id)
        try:
            body = WalkRegroupAutoIn(grade_id=args.grade, academic_year=args.year, term=args.term)
            _, choices, admins = await _regroup_roster(body, session, user.tenant_id)
            memberships = (await session.execute(select(StudentClassMembership).where(
                StudentClassMembership.tenant_id == user.tenant_id,
                StudentClassMembership.grade_id == args.grade,
                StudentClassMembership.academic_year == args.year,
                StudentClassMembership.term == args.term,
                StudentClassMembership.status == 'active',
                StudentClassMembership.student_id.in_(choices)))).scalars().all()
            assert len(memberships) == len(choices)
            assert admins == {m.student_id: m.class_id for m in memberships}, '本学期行政班归属不一致'
            assignments = await _generation_assignment_payloads(session, GenerateIn(
                academic_year=args.year, term=args.term, class_ids=sorted(set(admins.values()))), user.tenant_id)
            classes = list((await session.execute(select(TeachingClass).where(
                TeachingClass.tenant_id == user.tenant_id, TeachingClass.grade_id == args.grade,
                TeachingClass.academic_year == args.year, TeachingClass.term == args.term))).scalars())
            members = list((await session.execute(select(TeachingClassStudent.teaching_class_id,
                TeachingClassStudent.student_id).where(TeachingClassStudent.tenant_id == user.tenant_id,
                TeachingClassStudent.teaching_class_id.in_([c.id for c in classes])))).all())
            walk = list((await session.execute(select(TeachingClassSchedule).where(
                TeachingClassSchedule.tenant_id == user.tenant_id,
                TeachingClassSchedule.teaching_class_id.in_([c.id for c in classes])))).scalars())
            public = list((await session.execute(select(Schedule).where(Schedule.tenant_id == user.tenant_id,
                Schedule.academic_year == args.year, Schedule.term == args.term,
                Schedule.class_id.in_(set(admins.values()))))).scalars())
            cls = {c.id: c for c in classes}
            actual_choices, roster = defaultdict(list), defaultdict(list)
            for cid, sid in members:
                actual_choices[sid].append(cls[cid].subject_id); roster[cid].append(sid)
            assert {sid: sorted(v) for sid, v in actual_choices.items()} == {
                sid: sorted(v) for sid, v in choices.items()}, '选科/名单不一致'
            assert all(len(roster[c.id]) <= c.capacity for c in classes), '班额超限'
            students, teachers, rooms = Counter(), Counter(), Counter()
            public_hours, walk_hours = Counter(), Counter()
            admin_roster = defaultdict(list)
            for sid, cid in admins.items(): admin_roster[cid].append(sid)
            for row in public + walk:
                slot = row.weekday, row.period
                legs = ['odd', 'even'] if getattr(row, 'week_parity', 'all') == 'all' else [row.week_parity]
                room = row.room.split(' · ')[-1] if row.room else None
                for leg in legs:
                    teachers[row.teacher_id, leg, slot] += 1
                    if room: rooms[room, leg, slot] += 1
                    pupils = admin_roster[row.class_id] if isinstance(row, Schedule) else roster[row.teaching_class_id]
                    for sid in pupils: students[sid, leg, slot] += 1
                if isinstance(row, Schedule): public_hours[row.class_id, row.subject_id, row.weekday == 6] += 1
                else:
                    walk_hours[row.teaching_class_id] += 1
                    assert row.teacher_id == cls[row.teaching_class_id].teacher_id, '教师不一致'
            assert max(teachers.values()) == max(rooms.values()) == 1, '教师/教室冲突'
            assert all(students[sid, leg, (d, p)] == 1 for sid in choices for leg in ['odd', 'even']
                       for d in range(1, 7) for p in range(1, 8)), '学生冲突或1–7空节'
            assert all(walk_hours[c.id] == c.weekly_periods for c in classes), '走班课时错误'
            assert all(public_hours[a['class_id'], a['subject_id'], False] == a['weekday_periods']
                and public_hours[a['class_id'], a['subject_id'], True] == a['saturday_periods']
                for a in assignments), '行政课时错误'
            # Also count other grades' actual teacher/room use against this saved scope.
            for model in (Schedule, TeachingClassSchedule):
                query = select(model).where(model.tenant_id == user.tenant_id,
                    model.academic_year == args.year, model.term == args.term)
                query = query.where(model.class_id.not_in(set(admins.values()))) if model == Schedule else query.where(
                    model.teaching_class_id.not_in(cls))
                for row in (await session.execute(query)).scalars():
                    for leg in ['odd', 'even'] if getattr(row, 'week_parity', 'all') == 'all' else [row.week_parity]:
                        assert not teachers[row.teacher_id, leg, (row.weekday, row.period)], '跨年级教师冲突'
                        if row.room:
                            assert not rooms[row.room.split(' · ')[-1], leg, (row.weekday, row.period)], '跨年级教室冲突'
            candidate = {'calendar': {'public': [dict(r.model_dump(), id=r.id) for r in public]},
                'placements': [r.model_dump() for r in walk], 'members': members}
            group = await _load_rule_group(session, user.tenant_id, args.year, args.term, grade_id=args.grade)
            validate_candidate_rules(group, candidate, admins)
            print({'students': len(choices), 'teaching_classes': len(classes), 'public_lessons': len(public),
                'walk_lessons': len(walk), 'student_conflicts': 0, 'teacher_conflicts': 0,
                'room_conflicts': 0, 'gaps_1_7': 0, 'hour_errors': 0, 'rules': 'pass'})
        finally: tenant_id_ctx.reset(token)
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phone')
    parser.add_argument('--grade', type=int, default=12)
    parser.add_argument('--year', default='2026-2027')
    parser.add_argument('--term', choices=['1', '2'], default='2')
    asyncio.run(audit(parser.parse_args()))
