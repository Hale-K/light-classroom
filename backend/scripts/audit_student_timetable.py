"""Read-only audit of saved public + walk timetables in the current tenant/term."""
import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.models
from sqlalchemy import select, text
from app.api.v1.gaokao import WalkRecommendationIn, recommend_walk_configuration
from app.api.v1.scheduling import _load_rule_group
from app.db.session import AsyncSessionLocal, engine, tenant_id_ctx
from app.models.org import User, Schedule, Class, CourseHourPlan
from app.models.gaokao import TeachingClassSchedule
from app.services.scheduling.core import ScheduleItem
from app.services.scheduling.rules import evaluate_rule_group


async def main(args):
    captured = {}

    def capture(classes, members, rooms, slots, **kwargs):
        captured.update(classes=classes, members=members, rooms=rooms, kwargs=kwargs)
        return {'status': 'audit_only', 'message': 'Read-only audit; no solve or save'}

    async with AsyncSessionLocal() as session:
        await session.execute(text('SET TRANSACTION READ ONLY'))
        user = (await session.execute(select(User).where(User.phone == args.phone))).scalar_one()
        token = tenant_id_ctx.set(user.tenant_id)
        try:
            with patch('app.services.scheduling.walk_recommendation.recommend_walk_slots', capture):
                await recommend_walk_configuration(WalkRecommendationIn(grade_id=12,
                    academic_year='2026-2027', term='2'), session, user.tenant_id)
            kwargs = captured['kwargs']
            classes = {c['id']: c for c in captured['classes']}
            roster = defaultdict(set)
            for cid, sid in captured['members']:
                roster[cid].add(sid)
            walks = list((await session.execute(select(TeachingClassSchedule).where(
                TeachingClassSchedule.tenant_id == user.tenant_id,
                TeachingClassSchedule.academic_year == '2026-2027', TeachingClassSchedule.term == '2'))).scalars().all())
            admin = list((await session.execute(select(Schedule).where(Schedule.tenant_id == user.tenant_id,
                Schedule.academic_year == '2026-2027', Schedule.term == '2'))).scalars().all())
            grade_ids = set((await session.execute(select(Class.id).where(Class.tenant_id == user.tenant_id,
                Class.grade_id == 12, Class.academic_year == '2026-2027', Class.term == '2'))).scalars().all())
            grade_admin = [r for r in admin if r.class_id in grade_ids]
            current_walks = [r for r in walks if r.teaching_class_id in classes]
            occupied = {parity: {sid: set(slots) for sid, slots in fixed.items()}
                for parity, fixed in kwargs['student_fixed_by_parity'].items()}
            public_walk_conflicts = 0
            affected_students = set()
            student_counts = Counter()
            for row in current_walks:
                for sid in roster[row.teaching_class_id]:
                    for parity in ('odd', 'even'):
                        slot = row.weekday, row.period
                        conflict = slot in occupied[parity].get(sid, set())
                        public_walk_conflicts += conflict
                        if conflict:
                            affected_students.add(sid)
                        student_counts[parity, sid, *slot] += 1
                        occupied[parity].setdefault(sid, set()).add(slot)
            teacher_counts, admin_counts, room_counts = Counter(), Counter(), Counter()
            relevant_teachers = {r.teacher_id for r in grade_admin + current_walks}
            for row in admin:
                for parity in ('odd', 'even'):
                    if row.week_parity not in ('all', parity):
                        continue
                    if row.teacher_id in relevant_teachers:
                        teacher_counts[parity, row.teacher_id, row.weekday, row.period] += 1
                    if row.class_id in grade_ids:
                        admin_counts[parity, row.class_id, row.weekday, row.period] += 1
                    if row.room:
                        room_counts[parity, row.room, row.weekday, row.period] += 1
            for row in walks:
                for parity in ('odd', 'even'):
                    if row.teacher_id in relevant_teachers:
                        teacher_counts[parity, row.teacher_id, row.weekday, row.period] += 1
                    if row.room:
                        room_counts[parity, row.room, row.weekday, row.period] += 1
            walk_counts = Counter(r.teaching_class_id for r in current_walks)
            walk_hour_errors = sum(walk_counts[cid] != c['weekly_periods'] for cid, c in classes.items())
            plans = list((await session.execute(select(CourseHourPlan).where(
                CourseHourPlan.tenant_id == user.tenant_id, CourseHourPlan.class_id.in_(grade_ids),
                CourseHourPlan.academic_year == '2026-2027', CourseHourPlan.term == '2'))).scalars().all())
            expected, actual = defaultdict(float), defaultdict(float)
            for plan in plans:
                expected[plan.class_id, plan.subject_id] += float(plan.weekly_periods)
            for row in grade_admin:
                if row.period <= 12:
                    actual[row.class_id, row.subject_id] += 1 if row.week_parity == 'all' else .5
            admin_hour_errors = sum(expected[k] != actual[k] for k in expected.keys() | actual.keys())
            group = await _load_rule_group(session, user.tenant_id, '2026-2027', '2', grade_id=12)
            admin_items = [ScheduleItem(assignment_id=r.id, class_id=r.class_id, subject_id=r.subject_id,
                teacher_id=r.teacher_id, weekday=r.weekday, period=r.period, room=r.room,
                week_parity=r.week_parity) for r in grade_admin]
            walk_items = [ScheduleItem(assignment_id=-r.teaching_class_id, class_id=-r.teaching_class_id,
                subject_id=r.subject_id, teacher_id=r.teacher_id, weekday=r.weekday,
                period=r.period, room=r.room) for r in current_walks]
            from app.services.scheduling.student_gaps import build_student_self_study
            study_periods = {}
            for rule in group.rules:
                if rule.enabled and rule.code == 'student_contiguous' and rule.params.get('fill_self_study'):
                    for day in rule.weekdays or range(1, 8):
                        study_periods.setdefault(day, set()).update(rule.periods)
            studies = build_student_self_study(occupied, study_periods)
            validations = {mode: evaluate_rule_group(group, items, schedule_mode=mode,
                shared_items=admin_items if mode == 'walk' else [], student_occupied_by_parity=occupied,
                student_self_study_by_parity=studies if mode == 'walk' else None)
                for mode, items in [('admin', admin_items), ('walk', walk_items)]}
            report = dict(term='2026-2027/2', student_count=len({sid for _, sid in captured['members']}),
                public_or_walk_student_conflicts=public_walk_conflicts,
                students_with_public_walk_conflicts=len(affected_students),
                walk_student_duplicate_slots=sum(n > 1 for n in student_counts.values()),
                administrative_class_duplicate_slots=sum(n > 1 for n in admin_counts.values()),
                teacher_conflicting_slots=sum(n > 1 for n in teacher_counts.values()),
                room_conflicting_slots=sum(n > 1 for n in room_counts.values()),
                walk_classes_with_wrong_hours=walk_hour_errors, public_subjects_with_wrong_hours=admin_hour_errors,
                rules={mode: {'valid': validation.valid, 'results': [r.model_dump(mode='json') for r in validation.results]}
                    for mode, validation in validations.items()})
            print(json.dumps(report, ensure_ascii=False))
        finally:
            await session.rollback()
            tenant_id_ctx.reset(token)
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phone')
    asyncio.run(main(parser.parse_args()))
