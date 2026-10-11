"""Resolve exam scope against its semester, never against an unrelated current term."""
from sqlalchemy import select
from app.models.org import TenantConfig


async def exam_environment(session, tenant_id, exam):
    rows = (await session.execute(select(TenantConfig).where(TenantConfig.tenant_id == tenant_id,
        TenantConfig.config_key.in_(['academic_years', 'timetable_mode'])))).scalars().all()
    values = {r.config_key: r.config_value for r in rows if isinstance(r.config_value, dict)}
    calendar = values.get('academic_years', {})
    config = values.get('timetable_mode', {})
    scope = f'{exam.academic_year}:{exam.term}'
    mode = config.get('scopes', {}).get(scope) if isinstance(config.get('scopes'), dict) else None
    source = 'school_term_setting'
    if mode not in ('administrative', 'walk_class'):
        current_year = calendar.get('current_academic_year')
        entry = calendar.get('current_entry_year')
        if not current_year and entry:
            current_year = f'{entry}-{int(entry) + 1}'
        if current_year == exam.academic_year and str(calendar.get('current_term', '1')) == str(exam.term):
            mode = config.get('mode', 'administrative')
            source = 'school_current_setting'
        else:
            mode, source = None, 'unverified_historical'
    if mode not in ('administrative', 'walk_class'):
        mode = None
    return {'academic_year': exam.academic_year, 'term': exam.term,
            'timetable_mode': mode, 'source': source,
            'recommended_candidate_mode': 'choices' if mode == 'walk_class' else 'grade',
            'message': '行政班课表：全年级统一考试，无需确认选科。' if mode == 'administrative'
                else '选科走班课表：默认按学生已确认选科安排；统考可在特殊考试设置中调整。' if mode == 'walk_class'
                else '该学期未记录课表模式，默认全年级统一考试；不会套用其他学期的走班配置。'}
