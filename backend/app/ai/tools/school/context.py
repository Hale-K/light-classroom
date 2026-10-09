"""从服务端设置读取课表模式；页面选择不能覆盖学校配置。"""
import json

from sqlalchemy import select

from app.models.org import Tenant, TenantConfig
from app.ai.tools.school.common import _tool_response

TOOL = {'type': 'function', 'function': {
    'name': 'lookup_school_context',
    'description': '只读查询学校当前课表模式与默认高考模式，区分行政班课表和选科走班。走班模式内仍包含行政课与走班课两类；3+1+2等高考模式是独立配置。返回学校当前设置，不代表历史学期模式或已建届别的选科方案快照。问模式或选择查询类型时先查，不按年级或截图推断。',
    'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False},
}}


async def timetable_mode(session, tenant_id):
    config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == tenant_id, TenantConfig.config_key == 'timetable_mode'
    ))).scalars().first()
    # 与 auth._timetable_mode、scheduling._timetable_mode_of 的缺省规则一致。
    value = config.config_value if config and isinstance(config.config_value, dict) else {}
    mode = value.get('mode')
    return mode if mode in ('administrative', 'walk_class') else 'administrative'


async def lookup_school_context(session, tenant_id, arguments):
    try:
        args = json.loads(arguments or '{}')
        if args != {}:
            raise ValueError('无查询参数')
    except ValueError:
        return _tool_response('lookup_school_context', ok=False, code='INVALID_ARGUMENT',
            message='学校模式查询无需参数，请传空对象。')
    school = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalars().first()
    if school is None:
        return _tool_response('lookup_school_context', code='EMPTY_RESULT', message='未找到学校设置。')
    mode = await timetable_mode(session, tenant_id)
    from app.api.v1.teacher_profiles import _defaults
    defaults = await _defaults(session, tenant_id)
    return _tool_response('lookup_school_context', message='已查询学校当前设置；课表模式与高考选科模式分别配置，历史学期和已建届别方案须另外核对。',
        data={'timetable_mode': mode,
            'timetable_mode_label': '行政班课表' if mode == 'administrative' else '选科走班课表',
            'gaokao_mode': school.gaokao_mode,
            'academic_year': defaults.get('academic_year'), 'term': defaults.get('term'),
            'entry_year': defaults.get('entry_year'),
            'available_lesson_types': ['administrative'] if mode == 'administrative'
                else ['administrative', 'walk', 'combined'],
            'mode_source': 'school_current_setting', 'historical_mode_verified': False})
