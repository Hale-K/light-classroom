"""Set term-2 administrative-only reservations; never generate or save timetables.

Without --apply this prints the proposed configuration. Existing reservations
are not silently replaced. The previous catalog is backed up before applying.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app.models
from sqlalchemy import select
from app.api.v1.scheduling import _load_rule_catalog, save_rule_group
from app.db.session import AsyncSessionLocal, engine, tenant_id_ctx
from app.models.org import User
from app.services.scheduling.rules import (
    RuleDefinition, RuleTarget, compile_rule_group,
    generation_global_forbidden_slots, rules_for_schedule,
)


async def main(args):
    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).where(User.phone == args.phone))).scalar_one()
        token = tenant_id_ctx.set(user.tenant_id)
        try:
            groups, active = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '2')
            group = next(g for g in groups if g.grade_id == 12)
            if group.id != active:
                raise RuntimeError('Target rule group is not active; refusing to change activation.')
            ids = {'walk-reserve-689', 'walk-reserve-7'}
            if any(r.id != 'R01' and r.id not in ids for r in group.rules):
                raise RuntimeError('Unexpected existing rules: inspect them before changing configuration.')
            common = dict(code='slot_forbidden', priority='hard', schedule_scope='admin',
                          target=RuleTarget(type='global'), week_parity='all')
            reservations = [
                RuleDefinition(id='walk-reserve-689', title='走班预留：第6、8、9节',
                               weekdays=[1, 2, 3, 4, 5, 6], periods=[6, 8, 9], **common),
                RuleDefinition(id='walk-reserve-7', title='走班预留：第7节（周五除外）',
                               weekdays=[1, 2, 3, 4, 6], periods=[7], **common),
            ]
            proposal = group.model_copy(update={'rules': [r for r in group.rules if r.id not in ids] + reservations})
            assert all(r.status == 'ready' for r in compile_rule_group(proposal))
            reserved = generation_global_forbidden_slots(rules_for_schedule(proposal, 'admin'))
            assert len(reserved) == 23 and (5, 7) not in reserved
            assert not generation_global_forbidden_slots(rules_for_schedule(proposal, 'walk'))
            first_before, first_active = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '1')
            first_dump = [g.model_dump(mode='json') for g in first_before]
            print(json.dumps({'apply': args.apply, 'year': proposal.academic_year, 'term': proposal.term,
                              'grade_id': proposal.grade_id, 'reserved_common_slots': len(reserved),
                              'rules': [r.model_dump(mode='json') for r in proposal.rules]}, ensure_ascii=False), flush=True)
            if args.apply:
                backup = Path(__file__).resolve().parents[2] / '.codex/backups/grade12-term2-before-walk-reservations.json'
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists():
                    backup.write_text(json.dumps({'active_id': active, 'groups': [g.model_dump(mode='json') for g in groups]},
                                                 ensure_ascii=False, indent=2), encoding='utf-8')
                await save_rule_group(proposal, session, user, user.tenant_id)
                after, _ = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '2')
                saved = next(g for g in after if g.id == proposal.id)
                assert saved.model_dump() == proposal.model_dump()
                first_after, active_after = await _load_rule_catalog(session, user.tenant_id, '2026-2027', '1')
                assert first_dump == [g.model_dump(mode='json') for g in first_after]
                assert first_active == active_after
                print('Saved and read back: term 2 only; term 1 unchanged; no timetable generated.', flush=True)
        finally:
            await session.rollback()
            tenant_id_ctx.reset(token)
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phone')
    parser.add_argument('--apply', action='store_true')
    asyncio.run(main(parser.parse_args()))
