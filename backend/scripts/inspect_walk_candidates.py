"""Inspect the real walk API's candidate slots in a read-only DB transaction."""
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.models  # Register mappings before queries.
from sqlalchemy import select, text
from app.db.session import AsyncSessionLocal, engine, tenant_id_ctx
from app.models.org import User
from app.api.v1.gaokao import WalkRecommendationIn, recommend_walk_configuration
from app.services.scheduling.walk_recommendation import recommend_walk_slots


def inspect(classes, members, rooms, slots, **kwargs):
    roster = defaultdict(set)
    for cid, sid in members:
        roster[cid].add(sid)
    candidates = {}
    for c in classes:
        candidates[c['id']] = {
            slot for slot in slots
            if slot not in kwargs.get('blocked_subjects', {}).get(c['subject_id'], set())
            and slot not in kwargs.get('blocked_teachers', {}).get(c['teacher_id'], set())
            and not any(slot in kwargs.get('blocked_students', {}).get(sid, set()) for sid in roster[c['id']])
            and any(r['capacity'] >= len(roster[c['id']]) and slot not in kwargs.get('blocked_rooms', {}).get(r['name'], set()) for r in rooms)
        }
    print(json.dumps(dict(grid_slot_count=len(slots), max_period=max(p for _, p in slots),
                         common_slots=sorted(set.intersection(*candidates.values())),
                         groups=[dict(id=c['id'], teacher_id=c['teacher_id'], subject_id=c['subject_id'],
                                      required=c['weekly_periods'], candidates=sorted(candidates[c['id']])) for c in classes])), flush=True)
    return recommend_walk_slots(classes, members, rooms, slots, **kwargs)


async def main():
    async with AsyncSessionLocal() as session:
        if engine.dialect.name == 'postgresql':
            await session.execute(text('SET TRANSACTION READ ONLY'))
        tenant_id = (await session.execute(select(User.tenant_id).where(User.phone == sys.argv[1]))).scalar_one()
        token = tenant_id_ctx.set(tenant_id)
        try:
            with patch('app.services.scheduling.walk_recommendation.recommend_walk_slots', inspect):
                result = await recommend_walk_configuration(
                    WalkRecommendationIn(grade_id=12, academic_year='2026-2027', term='2'), session, tenant_id)
            print(json.dumps({key: value for key, value in result['data'].items()
                              if key not in {'placements', 'rule_results', 'recommended_slots'}},
                             ensure_ascii=False), flush=True)
        finally:
            await session.rollback()
            tenant_id_ctx.reset(token)
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
