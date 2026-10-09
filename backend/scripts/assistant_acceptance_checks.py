"""Repeatable real-PostgreSQL tool acceptance against the synthetic database only.

This does not call a model, change school settings, or access the source database.
Optional PostgreSQL transaction tests write only their own temporary schemas.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.ai.gateway.tool import ToolGateway  # noqa: E402
from app.ai.harness.router import PLANNING_HARNESS  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.models.gaokao import (  # noqa: E402
    GaokaoScheme, StudentSubjectChoice, TeachingClass, TeachingClassSchedule, TeachingClassStudent,
)
from app.models.org import (  # noqa: E402
    Class, CourseHourPlan, Grade, Schedule, Student, StudentClassMembership,
    StudentGradeMembership, Subject, TeachingAssignment, Tenant, TenantConfig,
)
from app.models.scheduling_grid import SchedulingGridDay, SchedulingGridPlan  # noqa: E402

MODELS = (Tenant, TenantConfig, Grade, Class, Subject, Student,
    StudentGradeMembership, StudentClassMembership, TeachingAssignment,
    CourseHourPlan, Schedule, StudentSubjectChoice, TeachingClass,
    TeachingClassStudent, TeachingClassSchedule, GaokaoScheme,
    SchedulingGridPlan, SchedulingGridDay)


class SelectOnly:
    def __init__(self, session):
        self.session, self.read_count = session, 0

    async def execute(self, statement, *args, **kwargs):
        if not statement.is_select:
            raise AssertionError('The tool attempted a non-SELECT statement')
        self.read_count += 1
        return await self.session.execute(statement, *args, **kwargs)


def require(condition, summary):
    if not condition:
        raise AssertionError(summary)


async def snapshot(session):
    result = {}
    for model in MODELS:
        rows = (await session.execute(select(*model.__table__.c))).mappings().all()
        encoded = sorted(json.dumps(dict(row), default=str, sort_keys=True, ensure_ascii=False) for row in rows)
        result[model.__tablename__] = {
            'count': len(rows),
            'sha256': hashlib.sha256('\n'.join(encoded).encode()).hexdigest(),
        }
    return result


async def main(postgres_tests=False):
    # Read only the database name from private state; never print the private file.
    database = json.loads((ROOT / '.codex/agent-acceptance/session.json').read_text(encoding='utf-8'))['database']
    require(bool(re.fullmatch(r'agent_acceptance_[0-9a-f]{8}', database)), 'Unsafe acceptance database name')
    source_url = make_url(settings.database_url)
    require(source_url.host in {'localhost', '127.0.0.1'} and source_url.get_backend_name() == 'postgresql',
        'Only local PostgreSQL synthetic acceptance is supported')
    target_url = source_url.set(database=database)
    engine = create_async_engine(target_url, connect_args={'server_settings': {'default_transaction_read_only': 'on'}})
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    report = {'evidence_level': 'real_database_tool_gateway', 'uses_live_model': False,
        'uses_browser': False, 'cases': []}

    async with sessions() as session:
        schools = (await session.execute(select(Tenant.id, Tenant.code).order_by(Tenant.id))).all()
        require(schools == [(1, 'accept_admin'), (2, 'accept_walk')], 'Database is not the known two-school synthetic fixture')
        before = await snapshot(session)
        readonly = SelectOnly(session)

        def scope(tenant, user=None):
            return ToolGateway().open_scope(session=readonly, tenant_id=tenant,
                user_id=user or tenant * 100 + 1, can_manage_rules=False,
                page_context={'academic_year': '2026-2027', 'term': '2', 'grade_id': tenant * 100 + 1,
                    'assistant_mode': 'plan'}, allowed_tools=PLANNING_HARNESS.allowed_tools)

        admin, walk, teacher = scope(1), scope(2), scope(2, 202)

        async def check(case_id, label, current, tool, arguments, assertions):
            record = {'id': case_id, 'summary': label, 'tool': tool}
            result = None
            try:
                result = json.loads(await current.execute(tool, json.dumps(arguments, ensure_ascii=False)))
                assertions(result)
                record['status'] = 'passed'
                data = result.get('data') or {}
                record['code'] = result.get('code')
                if isinstance(data, dict):
                    record['counts'] = {key: data[key] for key in ('total', 'missing_choice_count', 'class_count')
                        if isinstance(data.get(key), int)}
            except Exception as error:
                record['status'] = 'failed'
                record['error_class'] = type(error).__name__
                record['failure'] = str(error)[:300] if isinstance(error, AssertionError) else 'Execution failed; private connection details omitted'
            report['cases'].append(record)
            print(f"{case_id}: {record['status']} - {label}")
            return result

        for cid, current, mode in [('A01', admin, 'administrative'), ('W01', walk, 'walk_class')]:
            await check(cid, 'School mode, academic year and term come from server settings', current,
                'lookup_school_context', {}, lambda r: require(r['data']['timetable_mode'] == mode
                    and r['data']['academic_year'] == '2026-2027' and str(r['data']['term']) == '2', 'Unexpected school environment'))
        await check('A03', 'Three assignments; configured hours and odd/even plans stay distinct', admin,
            'lookup_teaching_assignments', {}, lambda r: require(r['data']['total'] == 3
                and any(i['assignment_weekly_periods'] == 9
                    and {p['week_parity']: p['weekly_periods'] for p in i['hour_plans']} == {'odd': 5, 'even': 4}
                    and i['scheduled_periods_by_week'] == {'odd': 2, 'even': 1}
                    and i['scheduled_teacher_mismatch_count'] == 1 for i in r['data']['items']), 'Assignment, parity or mismatch evidence differs'))
        await check('A05', 'Administrative mode ignores three retained walk lessons', admin,
            'lookup_timetable', {}, lambda r: require(r['data']['total'] == 5
                and all(i['kind'] == 'administrative' for i in r['data']['items']), 'Expected five administrative lessons'))
        for cid, current, student in [('A06', admin, 101), ('W06H', walk, 201)]:
            await check(cid, 'Historical personal timetable uses the old term membership', current,
                'lookup_timetable', {'student_id': student, 'term': '1'}, lambda r: require(r['data']['total'] == 1
                    and r['data']['items'][0]['period'] == 4 and not r['scope']['historical_mode_verified'], 'Expected one historical period-four lesson'))
        for cid, current in [('A08', admin), ('W02', walk)]:
            await check(cid, 'Six students; confirmed/draft/locked distinct and three missing choices', current,
                'lookup_student_choices', {}, lambda r: require(r['data']['total'] == 6
                    and r['data']['missing_choice_count'] == 3
                    and r['data']['choice_status_counts'] == {'confirmed': 1, 'draft': 1, 'locked': 1, 'missing': 3}, 'Choice counts or statuses differ'))
        await check('W02D', 'Duplicate physics enrollment and unassigned draft are visible', walk,
            'lookup_student_choices', {}, lambda r: require(any(i['student_id'] == 201
                and i['duplicate_subject_enrollments'] == [204] for i in r['data']['items'])
                and any(i['student_id'] == 202 and not i['teaching_class_ids'] for i in r['data']['items']), 'Missing duplicate/draft evidence'))
        for cid, args, total in [('W03', {'student_id': 201}, 6), ('W04A', {'lesson_type': 'administrative'}, 5),
                ('W04W', {'lesson_type': 'walk'}, 3), ('W04C', {'lesson_type': 'combined'}, 8)]:
            await check(cid, 'Timetable lesson-type and individual counts match saved fixture', walk,
                'lookup_timetable', args, lambda r, total=total: require(r['data']['total'] == total, f'Expected {total} saved lessons'))
        for cid, current, high_grade in [('A07', admin, 102), ('W05', walk, 202)]:
            await check(cid, 'Cross-grade competitors remain; parity and candidate-room boundaries hold', current,
                'lookup_schedule_conflicts', {}, lambda r, high_grade=high_grade: require(
                    any(i['resource_type'] == 'teacher' and any(s['grade_id'] == high_grade for s in i['lessons']) for i in r['data']['items'])
                    and not any(i['period'] == 2 for i in r['data']['items'])
                    and all(i['candidate_only'] for i in r['data']['items'] if i['resource_type'] == 'room')
                    and not r['data']['coverage']['full_rule_validation'], 'Conflict scope or parity boundary differs'))
        await check('A10', 'Administrative mode rejects explicit walk queries', admin,
            'lookup_timetable', {'lesson_type': 'walk'}, lambda r: require(r['code'] == 'MODE_MISMATCH', 'Expected MODE_MISMATCH'))
        for cid, args in [('G02G', {'grade_id': 201}), ('G02C', {'class_id': 210}),
                ('A09S', {'student': '同名学生'}), ('A09T', {'teacher': '同名老师'}), ('A09N', {'student': '不存在学生'})]:
            await check(cid, 'Cross-school or ambiguous/missing objects are not guessed', admin,
                'lookup_timetable', args, lambda r: require(r['code'] == 'MISSING_SCOPE', 'Expected scoped clarification, not guessed data'))
        for cid, tool in [('G01S', 'lookup_student_choices'), ('G01T', 'lookup_timetable'), ('G01P', 'lookup_planning_basis')]:
            await check(cid, 'Ordinary teacher cannot read school-wide sensitive evidence', teacher,
                tool, {}, lambda r: require(r['code'] == 'FORBIDDEN', 'Expected role-based denial'))
        first = await check('W06A', 'First page returns two of eight lessons with continuation offset', walk,
            'lookup_timetable', {'limit': 2}, lambda r: require(r['data']['total'] == 8 and len(r['data']['items']) == 2
                and r['data']['next_offset'] == 2, 'First page metadata differs'))
        await check('W06B', 'Next two lessons do not duplicate the first page', walk,
            'lookup_timetable', {'limit': 2, 'offset': 2}, lambda r: require(r['data']['total'] == 8
                and len(r['data']['items']) == 2 and not ({(i['kind'], i['schedule_id']) for i in r['data']['items']}
                    & {(i['kind'], i['schedule_id']) for i in first['data']['items']}), 'Pagination lost or duplicated lessons'))
        for cid, current in [('P01A', admin), ('P01W', walk)]:
            await check(cid, 'Real planning capacity is 40 and score weights remain unverified', current,
                'lookup_planning_basis', {}, lambda r: require(r['data']['grid']['configured']
                    and r['data']['grid']['daytime_capacity_by_week'] == {'odd': 40, 'even': 40}
                    and not r['data']['score_weights']['verified'], 'Capacity or score-weight provenance differs'))
        values = [('语文', 6), ('数学', 6), ('英语', 6), ('物理', 3), ('化学', 3),
            ('生物', 3), ('政治', 2), ('历史', 2), ('体育', 2), ('音乐', 1), ('心理', 1)]
        scenario = {'name': '35节临时方案', 'subjects': [{'subject': s, 'periods': float(h)} for s, h in values]}
        arguments = {'weekdays': [1, 2, 3, 4, 5], 'mandatory_periods': list(range(1, 8)),
            'optional_periods': [8, 9], 'scenarios': [scenario]}
        admin.configure_request('体育2节、音乐1节、心理1节；第一到第七节必须满课，给3个方案，只做建议')
        await check('P02', '35-period arithmetic and fixed hours pass; absent psychology blocks implementation', admin,
            'validate_hour_scenarios', arguments, lambda r: require(r['data']['all_numeric_constraints_valid']
                and not r['data']['all_valid'] and not r['data']['scenarios'][0]['subject_catalog_valid']
                and r['data']['scenarios'][0]['total_periods_by_week'] == {'odd': 35.0, 'even': 35.0}
                and any(e['code'] == 'UNKNOWN_SUBJECT' and e['subject'] == '心理' for e in r['data']['scenarios'][0]['errors'])
                and r['data']['fixed_subject_hours'] == {'体育': 2.0, '音乐': 1.0, '心理': 1.0}, 'Numeric/catalog/fixed-hour boundary differs'))
        over = json.loads(json.dumps(arguments))
        over['scenarios'][0]['subjects'][0]['periods'] = 16.0
        await check('P03', '45-period scenario fails current 40-period capacity', admin,
            'validate_hour_scenarios', over, lambda r: require(not r['data']['all_numeric_constraints_valid']
                and any(e['code'] == 'CAPACITY_EXCEEDED' for e in r['data']['scenarios'][0]['errors']), 'Over-capacity scenario was accepted'))
        after = await snapshot(session)
        report['business_snapshot_unchanged'] = before == after
        report['business_table_counts'] = {key: value['count'] for key, value in before.items()}
        report['select_only_statement_count'] = readonly.read_count
        report['cases'].append({'id': 'G03R', 'status': 'passed' if before == after else 'failed',
            'summary': 'All business-table counts and content hashes match before and after tool calls'})
    await engine.dispose()

    if postgres_tests:
        env = dict(os.environ, DATABASE_URL=target_url.render_as_string(hide_password=False),
            ASSISTANT_POSTGRES_TEST='1', PYTHONUTF8='1', SCHEMA_SYNC_DROP='false')
        completed = subprocess.run([sys.executable, '-m', 'pytest', 'tests/test_assistant_postgres.py',
            '-q', '--disable-warnings', '--tb=short'], cwd=BACKEND, env=env,
            capture_output=True, text=True, encoding='utf-8', timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        report['postgres_transaction_tests'] = {'status': 'passed' if completed.returncode == 0 else 'failed',
            'summary': 'Opt-in confirmation-race and durable-progress/cancellation tests in unique temporary schemas'}
        if completed.returncode == 0:
            match = re.search(r'(\d+) passed', completed.stdout)
            report['postgres_transaction_tests']['passed_count'] = int(match[1]) if match else 0
        else:
            (ROOT / '.codex/agent-acceptance/postgres-checks.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
        print('PostgreSQL transaction tests:', report['postgres_transaction_tests']['status'])
    report['passed_count'] = sum(case['status'] == 'passed' for case in report['cases'])
    report['failed_count'] = len(report['cases']) - report['passed_count']
    output = ROOT / 'docs/agent-acceptance-tool-results.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed_count'], 'failed': report['failed_count'],
        'business_snapshot_unchanged': report['business_snapshot_unchanged'], 'report': str(output)}, ensure_ascii=False))
    return 1 if report['failed_count'] or report.get('postgres_transaction_tests', {}).get('status') == 'failed' else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--postgres-tests', action='store_true')
    options = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(main(options.postgres_tests)))
    except (AssertionError, OSError, KeyError, ValueError):
        print('Acceptance setup failed; verify the private synthetic session and local database configuration.')
        raise SystemExit(1)
