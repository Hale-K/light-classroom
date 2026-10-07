"""Read-only regrouping experiment; never replaces persisted rosters or schedules."""
import argparse
import asyncio
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.models
from sqlalchemy import select, text
from ortools.sat.python import cp_model
from app.db.session import AsyncSessionLocal, engine, tenant_id_ctx
from app.models.org import User, Student, Class, Schedule
from app.models.gaokao import TeachingClass, TeachingClassSchedule, StudentSubjectChoice
from app.api.v1.gaokao import (WalkRecommendationIn, recommend_walk_configuration,
                              _map_student_admin_classes_to_term)
from app.api.v1.scheduling import GenerateIn, _generation_assignment_payloads, _load_rule_group
from app.services.scheduling.rules import generation_subject_allowed_slots, rules_for_schedule
from app.services.scheduling.walk_regroup import regroup_walk_students


from app.services.scheduling.walk_regroup_calendar import trial_calendar, audit_draft


async def main(args):
    data = {}
    def capture(classes, members, rooms, slots, **kwargs):
        data.update(classes=classes, members=members, rooms=rooms)
        return {'status': 'preview_only'}
    async with AsyncSessionLocal() as session:
        await session.execute(text('SET TRANSACTION READ ONLY'))
        user = (await session.execute(select(User).where(User.phone == args.phone))).scalar_one()
        token = tenant_id_ctx.set(user.tenant_id)
        try:
            with patch('app.services.scheduling.walk_recommendation.recommend_walk_slots', capture):
                await recommend_walk_configuration(WalkRecommendationIn(grade_id=12,
                    academic_year='2026-2027', term='2'), session, user.tenant_id)
            ids = {sid for _, sid in data['members']}
            students = list((await session.execute(select(Student).where(Student.id.in_(ids)))).scalars())
            source_ids = {s.class_id for s in students}
            sources = list((await session.execute(select(Class).where(Class.id.in_(source_ids)))).scalars())
            targets = list((await session.execute(select(Class).where(Class.tenant_id == user.tenant_id,
                Class.grade_id == 12, Class.academic_year == '2026-2027', Class.term == '2'))).scalars())
            mapping = _map_student_admin_classes_to_term(source_ids, sources, targets)
            admins = {s.id: mapping[s.class_id] for s in students}
            choices, teacher_pool = defaultdict(set), defaultdict(set)
            old = {c['id']: c for c in data['classes']}
            for cid, sid in data['members']:
                choices[sid].add(old[cid]['subject_id'])
            confirmed = list((await session.execute(select(StudentSubjectChoice).where(
                StudentSubjectChoice.tenant_id == user.tenant_id,
                StudentSubjectChoice.student_id.in_(ids), StudentSubjectChoice.academic_year == '2026-2027',
                StudentSubjectChoice.effective_term == '2',
                StudentSubjectChoice.status.in_(['confirmed', 'locked'])))).scalars())
            assert {c.student_id: set(c.secondary_subject_ids) for c in confirmed} == dict(choices), 'Roster does not match confirmed choices'
            for c in old.values():
                teacher_pool[c['subject_id']].add(c['teacher_id'])
            capacity = min((await session.execute(select(TeachingClass.capacity)
                .where(TeachingClass.id.in_(old)))).scalars())
            assignments = await _generation_assignment_payloads(session, GenerateIn(
                academic_year='2026-2027', term='2', class_ids=sorted(set(admins.values()))), user.tenant_id)
            rule_group = await _load_rule_group(session, user.tenant_id, '2026-2027', '2', grade_id=12)
            subject_allowed = generation_subject_allowed_slots(rules_for_schedule(rule_group, 'admin'))
            # This experiment deliberately refuses silently changed hour-plan inputs.
            assert all(c['weekly_periods'] == 4 for c in old.values())
            totals = defaultdict(lambda: [0, 0])
            for a in assignments:
                totals[a['class_id']][0] += a['weekday_periods']
                totals[a['class_id']][1] += a['saturday_periods']
            assert all(hours == [30, 4] for hours in totals.values()), 'Hour plans changed; redesign phase template'
            external = set()
            for model_type in (Schedule, TeachingClassSchedule):
                query = select(model_type).where(model_type.tenant_id == user.tenant_id,
                    model_type.academic_year == '2026-2027', model_type.term == '2')
                query = query.where(model_type.class_id.not_in(set(admins.values()))) if model_type == Schedule else query.where(model_type.teaching_class_id.not_in(old))
                for row in (await session.execute(query)).scalars():
                    external.add((row.teacher_id, (row.weekday, row.period)))
            counts = Counter(admins.values())
            subjects = sorted(teacher_pool)
            rng = random.Random(42)
            print(json.dumps({'students': len(ids), 'capacity': capacity,
                'rooms': len(data['rooms']), 'admin_counts': counts}, ensure_ascii=False), flush=True)
            for attempt in range(40):
                partitions = []
                for _ in range(2):
                    for retry in range(1000):
                        ordered = list(counts); rng.shuffle(ordered)
                        groups = [ordered[:3], ordered[3:6], ordered[6:8], ordered[8:]]
                        if all(sum(counts[c] for c in g) <= 3 * capacity for g in groups):
                            partitions.append({c: i for i, g in enumerate(groups) for c in g}); break
                    else:
                        raise RuntimeError('No capacity-compatible partition found')
                ag, bg = partitions
                excluded = {i: subjects[(i + attempt) % len(subjects)] for i in range(4)}
                draft = regroup_walk_students(choices, admins, ag, bg, excluded, capacity=capacity)
                if draft['status'] != 'feasible':
                    print(f'attempt {attempt}: roster {draft["status"]}', flush=True); continue
                result = trial_calendar(draft, assignments, counts, ag, bg, teacher_pool, len(data['rooms']), external,
                                        subject_allowed=subject_allowed)
                print(json.dumps({'attempt': attempt, 'classes': len(draft['classes']),
                    'calendar': {k: v for k, v in result.items() if k in ('status', 'seconds')}}, ensure_ascii=False), flush=True)
                if result['status'] in ('OPTIMAL', 'FEASIBLE'):
                    audit, placements = audit_draft(draft, result, choices, admins,
                        assignments, data['rooms'], external)
                    artifact = {'scope': {'tenant_id': user.tenant_id, 'grade_id': 12,
                        'academic_year': '2026-2027', 'term': '2'},
                        'draft': draft, 'a_groups': ag, 'b_groups': bg,
                        'calendar': result, 'placements': placements, 'audit': audit,
                        'note': 'READ ONLY: old reservation rules must be replaced before applying'}
                    if args.output:
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(json.dumps({'audit': audit, 'output': str(args.output) if args.output else None}, ensure_ascii=False), flush=True)
                    break
            else:
                raise RuntimeError('No validated candidate; database unchanged')
        finally:
            await session.rollback()
            tenant_id_ctx.reset(token)
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phone')
    parser.add_argument('--output', type=Path)
    asyncio.run(main(parser.parse_args()))
