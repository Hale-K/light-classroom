"""创建独立 PostgreSQL 验收库并启动同一应用；绝不写入源业务库。

只从源库读取启用的默认模型配置，凭据不输出、不写入验收报告。
临时登录信息与进程号放入被忽略的 .codex 目录。
"""
import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
from app.core.config import settings
import app.models  # noqa: F401
from app.ai.model.store import AiProvider
from app.db.session import _sync_schema
from app.core.security import get_password_hash
from app.models.org import (Tenant, TenantConfig, User, Grade, Class, Subject,
    Student, OrganizationUnit, StudentGradeMembership, StudentClassMembership,
    TeachingAssignment, CourseHourPlan, Schedule)
from app.models.gaokao import (GaokaoScheme, StudentSubjectChoice, TeachingClass,
    TeachingClassStudent, TeachingClassSchedule)
from app.models.scheduling_grid import SchedulingGridPlan, SchedulingGridDay


async def main():
    source_url = make_url(settings.database_url)
    if source_url.get_backend_name() != 'postgresql':
        raise RuntimeError('本脚本仅为 PostgreSQL 开发环境创建独立验收库')
    database = 'agent_acceptance_' + secrets.token_hex(4)
    source = create_async_engine(source_url)
    async with async_sessionmaker(source)() as session:
        provider = (await session.execute(select(AiProvider).where(
            AiProvider.status == 1).order_by(AiProvider.is_default.desc(), AiProvider.id))).scalars().first()
        if provider is None:
            raise RuntimeError('没有已启用的模型配置')
        provider_values = provider.model_dump(exclude={'id', 'tenant_id', 'created_at', 'updated_at'})
    await source.dispose()
    admin_engine = create_async_engine(source_url.set(database='postgres'), isolation_level='AUTOCOMMIT')
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{database}"'))
    await admin_engine.dispose()
    target_url = source_url.set(database=database)
    target = create_async_engine(target_url)
    async with target.begin() as conn:
        await conn.run_sync(_sync_schema)
    password = secrets.token_urlsafe(18)
    async with async_sessionmaker(target, expire_on_commit=False)() as session:
        # 两校相同名字、不同ID：同时验证租户与模式隔离。
        for tid, mode, code in [(1, 'administrative', 'accept_admin'), (2, 'walk_class', 'accept_walk')]:
            n = tid * 100
            session.add(Tenant(id=tid, code=code, name='合成验收学校-' + mode, province='吉林'))
            session.add_all([
                TenantConfig(tenant_id=tid, config_key='timetable_mode', config_value={'mode': mode}),
                TenantConfig(tenant_id=tid, config_key='academic_years', config_value={
                    'current_entry_year': 2026, 'current_academic_year': '2026-2027', 'current_term': '2'}),
                AiProvider(tenant_id=tid, **provider_values),
                User(id=n+1, tenant_id=tid, name='验收主任', phone=f'1990000000{tid}',
                     password_hash=get_password_hash(password), role='director'),
                User(id=n+2, tenant_id=tid, name='甲老师', phone=f'1990000001{tid}',
                     password_hash=get_password_hash(password), role='teacher'),
                User(id=n+3, tenant_id=tid, name='乙老师', phone=f'1990000002{tid}',
                     password_hash=get_password_hash(password), role='teacher'),
                User(id=n+4, tenant_id=tid, name='同名老师', phone=f'1990000003{tid}',
                     password_hash=get_password_hash(password), role='teacher'),
                User(id=n+5, tenant_id=tid, name='同名老师', phone=f'1990000004{tid}',
                     password_hash=get_password_hash(password), role='teacher'),
                Grade(id=n+1, tenant_id=tid, name='高一', level=1),
                Grade(id=n+2, tenant_id=tid, name='高二', level=2),
            ])
            await session.flush()
            for i, name in enumerate(['语文','数学','英语','物理','化学','生物','政治','历史','地理','美术','音乐','体育'], 1):
                session.add(Subject(id=n+i, tenant_id=tid, name=name))
            for g in (1, 2):
                session.add(OrganizationUnit(id=n+g, tenant_id=tid, name=f'2026届高{g}',
                    unit_type='grade_group', grade_id=n+g, academic_year='2026-2027', cohort_label='2026'))
                session.add(SchedulingGridPlan(id=n+g, tenant_id=tid, grade_id=n+g,
                    academic_year='2026-2027', term='2'))
            await session.flush()
            for g in (1, 2):
                session.add_all([SchedulingGridDay(plan_id=n+g, weekday=d,
                    daytime_periods=8 if d <= 5 else 0) for d in range(1,8)])
            for cid, grade, name, term in [(10,1,'高一1班','2'),(11,1,'高一2班','2'),
                    (20,2,'高二1班','2'),(12,1,'高一旧班','1')]:
                session.add(Class(id=n+cid, tenant_id=tid, grade_id=n+grade, name=name,
                    academic_year='2026-2027', term=term, cohort_label='2026'))
            await session.flush()
            for sid, name, cid in [(1,'学生甲',10),(2,'学生乙',10),(3,'学生丙',11),
                    (4,'待分班学生',None),(5,'同名学生',11),(6,'同名学生',11)]:
                session.add(Student(id=n+sid, tenant_id=tid, name=name, gender='male',
                    student_no=f'T{tid}-{sid}', grade_id=n+1, class_id=n+12))
            await session.flush()
            for sid, cid in [(1,10),(2,10),(3,11),(4,None),(5,11),(6,11)]:
                session.add(StudentGradeMembership(tenant_id=tid, student_id=n+sid,
                    grade_id=n+1, grade_unit_id=n+1, academic_year='2026-2027', cohort_label='2026'))
                if cid:
                    session.add(StudentClassMembership(tenant_id=tid, student_id=n+sid,
                        class_id=n+cid, grade_id=n+1, academic_year='2026-2027', term='2', cohort_label='2026'))
            session.add(StudentClassMembership(tenant_id=tid, student_id=n+1,
                class_id=n+12, grade_id=n+1, academic_year='2026-2027', term='1', cohort_label='2026'))
            session.add(GaokaoScheme(id=tid, tenant_id=tid, name='2026届合成方案', entry_year=2026,
                required_subject_ids=[n+1,n+2,n+3], primary_subject_ids=[n+4,n+8],
                secondary_subject_ids=[n+5,n+6,n+7,n+9]))
            for sid, subjects, status in [(1,[4,5,6],'confirmed'),(2,[4,5,9],'draft'),(3,[8,7,9],'locked')]:
                session.add(StudentSubjectChoice(tenant_id=tid, student_id=n+sid, scheme_id=tid,
                    academic_year='2026-2027', effective_term='2',
                    selected_subject_ids=[n+s for s in subjects], status=status))
            for cid, subj, teacher, hours, parity in [(10,2,2,5,'odd'),(10,2,2,4,'even'),
                    (10,1,3,6,'all'),(11,2,2,4,'all'),(20,2,2,4,'all')]:
                session.add(CourseHourPlan(tenant_id=tid, class_id=n+cid, subject_id=n+subj,
                    academic_year='2026-2027', term='2', weekday_periods=hours,
                    weekly_periods=hours, week_parity=parity))
            for cid, subj, teacher, hours in [(10,2,2,9),(10,1,3,6),(11,2,2,4),(20,2,2,4)]:
                session.add(TeachingAssignment(tenant_id=tid, class_id=n+cid, subject_id=n+subj,
                    teacher_id=n+teacher, academic_year='2026-2027', term='2', weekly_periods=hours))
            for wid, subj, teacher in [(30,4,2),(31,4,3),(32,8,3)]:
                session.add(TeachingClass(id=n+wid, tenant_id=tid, grade_id=n+1, subject_id=n+subj,
                    name=f'{"物理" if subj==4 else "历史"}{wid-29}班', academic_year='2026-2027',
                    term='2', sequence=wid-29, teacher_id=n+teacher, weekly_periods=3, capacity=40))
            await session.flush()
            # 甲物理重复入两个班，乙草稿未入班，丙历史已入班。
            for wid, sid in [(30,1),(31,1),(32,3)]:
                session.add(TeachingClassStudent(tenant_id=tid, teaching_class_id=n+wid, student_id=n+sid))
            for cid, subj, teacher, period, parity, term in [
                    (10,2,2,1,'odd','2'),(10,2,3,2,'odd','2'),(10,2,2,2,'even','2'),
                    (10,1,3,3,'all','2'),(11,2,2,1,'all','2'),(20,2,2,1,'all','2'),
                    (12,2,2,4,'all','1')]:
                session.add(Schedule(tenant_id=tid, class_id=n+cid, teacher_id=n+teacher,
                    subject_id=n+subj, weekday=1, period=period, room='A' if cid==10 else 'B',
                    academic_year='2026-2027', term=term, week_parity=parity))
            for wid, subj, teacher, period in [(30,4,2,1),(31,4,3,4),(32,8,3,5)]:
                session.add(TeachingClassSchedule(tenant_id=tid, teaching_class_id=n+wid,
                    teacher_id=n+teacher, subject_id=n+subj, weekday=1, period=period,
                    room='A', academic_year='2026-2027', term='2'))
        await session.commit()
    await target.dispose()
    private = ROOT / '.codex' / 'agent-acceptance'
    private.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, DATABASE_URL=target_url.render_as_string(hide_password=False),
               DEFAULT_SCHOOL_CODE='accept_admin', SCHEMA_SYNC_DROP='false', APP_NAME='轻课堂 · 合成验收',
               PYTHONUTF8='1')
    backend_log = open(private/'backend.log', 'w', encoding='utf-8')
    backend = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host',
        '127.0.0.1', '--port', '8002'], cwd=BACKEND, env=env, stdout=backend_log,
        stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    node = r'C:\Program Files\AutoClaw\resources\node\node.exe'
    frontend_log = open(private/'frontend.log', 'w', encoding='utf-8')
    frontend = subprocess.Popen([node, 'node_modules/vite/bin/vite.js', '--host',
        '127.0.0.1', '--port', '5177', '--strictPort'], cwd=ROOT/'frontend-react',
        env=dict(os.environ, VITE_DEV_PROXY='http://127.0.0.1:8002'), stdout=frontend_log,
        stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    (private/'session.json').write_text(json.dumps({'database': database, 'password': password,
        'backend_pid': backend.pid, 'frontend_pid': frontend.pid}, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'database': database, 'backend_port': 8002, 'frontend_port': 5177,
        'admin_phone': '19900000001', 'walk_phone': '19900000002', 'teacher_phone': '19900000012'}))


if __name__ == '__main__':
    asyncio.run(main())
