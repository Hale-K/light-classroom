"""Replace the task's gap preference with a term-2 contiguous hard rule.

Never generate or save a timetable. Back up the catalog before updating it.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.models
from sqlalchemy import select
from app.api.v1.scheduling import _load_rule_catalog, save_rule_group
from app.api.v1.gaokao import WalkRecommendationIn, recommend_walk_configuration
from app.db.session import AsyncSessionLocal, engine, tenant_id_ctx
from app.models.org import User
from app.services.scheduling.rules import RuleDefinition, compile_rule_group


async def main(args):
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.phone == args.phone))).scalar_one()
        token = tenant_id_ctx.set(user.tenant_id)
        try:
            groups, active = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '2')
            group = next(g for g in groups if g.grade_id == 12 and g.id == active)
            first, first_active = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '1')
            first_dump = [g.model_dump() for g in first]
            rule = RuleDefinition(id='student-gap-minimize', title='行政课连续（末尾可空）',
                code='class_gap_free', priority='hard', schedule_scope='admin',
                target={'type': 'global'}, weekdays=[1, 2, 3, 4, 5, 6], periods=[1, 2, 7, 8, 9],
                params={'trailing_empty': True})
            old = next(r for r in group.rules if r.id == rule.id)
            if old.code not in {'student_gap_minimize', 'student_contiguous', 'class_gap_free'}:
                raise RuntimeError('Refusing to overwrite a different rule')
            proposal = group.model_copy(update={'rules': [rule if r.id == rule.id else r for r in group.rules]})
            assert all(r.status == 'ready' for r in compile_rule_group(proposal))
            print(json.dumps(rule.model_dump(mode='json'), ensure_ascii=False))
            if not args.apply:
                return
            if group.model_dump() != proposal.model_dump():
                backup = Path(__file__).resolve().parents[2] / '.codex/backups' / (
                    'before-student-contiguous-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_text(json.dumps({'active_id': active, 'groups': [g.model_dump(mode='json') for g in groups]},
                    ensure_ascii=False, indent=2), encoding='utf-8')
                await save_rule_group(proposal, session, user, user.tenant_id)
            after, after_active = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '2')
            assert after_active == active
            assert next(g for g in after if g.id == group.id).model_dump() == proposal.model_dump()
            assert [g.model_dump() for g in after if g.id != group.id] == [g.model_dump() for g in groups if g.id != group.id]
            first_after, first_active_after = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '1')
            assert first_dump == [g.model_dump() for g in first_after] and first_active == first_active_after
            print('Saved term-2 rule only; all timetables unchanged.')
        finally:
            await session.rollback()
            tenant_id_ctx.reset(token)
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phone')
    parser.add_argument('--apply', action='store_true')
    asyncio.run(main(parser.parse_args()))
