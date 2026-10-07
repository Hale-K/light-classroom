"""Remove retired joint-generated rules in one explicit tenant/grade/term scope."""
import argparse
import asyncio
import json
from sqlalchemy import select, func
from app.db.session import AsyncSessionLocal, engine
from app.models.org import Grade, TenantConfig, Schedule
from app.models.gaokao import TeachingClass, TeachingClassSchedule
from app.services.scheduling.walk_regroup_save import clean_generated_rule_catalog


async def run(args):
    async with AsyncSessionLocal() as session:
        grade = await session.get(Grade, args.grade)
        if not grade or grade.tenant_id != args.tenant:
            raise ValueError('年级不属于指定学校')
        row = (await session.execute(select(TenantConfig).where(
            TenantConfig.tenant_id == args.tenant,
            TenantConfig.config_key == 'scheduling_rule_group').with_for_update())).scalar_one()
        cleaned, removed = clean_generated_rule_catalog(
            row.config_value, args.year, args.term, args.grade)
        async def counts():
            return [await session.scalar(select(func.count()).select_from(model).where(
                model.tenant_id == args.tenant, model.academic_year == args.year,
                model.term == args.term)) for model in (Schedule, TeachingClass, TeachingClassSchedule)]
        before = await counts()
        if args.apply and cleaned != row.config_value:
            row.config_value = cleaned
            await session.flush()
            assert await counts() == before, '课表记录不应变化'
            await session.commit()
            await session.refresh(row)
            assert row.config_value == cleaned
        print(json.dumps({'applied': args.apply, 'removed_rules': removed,
            'grade': grade.name, 'year': args.year, 'term': args.term,
            'timetable_counts_unchanged': before}, ensure_ascii=False))
    await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tenant', type=int, required=True)
    parser.add_argument('--grade', type=int, required=True)
    parser.add_argument('--year', required=True)
    parser.add_argument('--term', required=True)
    parser.add_argument('--apply', action='store_true')
    asyncio.run(run(parser.parse_args()))
