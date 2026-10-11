"""空间资源汇总：配置和分配，独立于课表使用情况。"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from sqlalchemy import func, select

from app.models.facility import Room, ResourceAllocationRule, RoomCohortAllocation
from app.ai.tools.school.common import _term, _tool_response


class ResourceQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    metric: Literal['overview', 'inventory', 'allocation'] = 'overview'
    academic_year: str | None = Field(default=None, min_length=4, max_length=20)
    term: Literal['1', '2'] | None = None
    cohort_label: str | None = Field(default=None, min_length=1, max_length=30)
    room_type: str | None = Field(default=None, min_length=1, max_length=30,
        description='按资源类型筛选；不传则返回所有类型并分别汇总，不能把所有空间都称为普通教室。')


TOOL = {'type': 'function', 'function': {
    'name': 'lookup_room_resources',
    'description': '查询空间资源已配置数量和已分配给届别的数量。只读取教室档案与资源分配，不查询课表，不继承页面班级。inventory是已配置资源，allocation是指定学期有效分配，overview返回两者并区分普通教室等类型。实际课表使用教室数量是另一指标，不能用单班课表代替资源分配。分配按room_id去重，共享教室不重复累计。',
    'parameters': ResourceQuery.model_json_schema(),
}}


async def execute(arguments, *, session, tenant_id, page_context):
    try:
        q = ResourceQuery.model_validate_json(arguments or '{}')
    except ValueError:
        return _tool_response('lookup_room_resources', ok=False, code='INVALID_ARGUMENT',
            message='请明确统计已配置资源还是学期资源分配；学期需为1或2。')
    base = [Room.tenant_id == tenant_id]
    if q.room_type:
        base.append(Room.room_type == q.room_type)
    types = (await session.execute(select(Room.room_type, func.count(Room.id)).where(*base)
        .group_by(Room.room_type))).all()
    data = {'inventory': {'total': sum(count for _, count in types),
        'by_room_type': {kind: count for kind, count in types},
        'source': 'room_inventory', 'unit': '间'}}
    scope = {'range': 'school', 'room_type': q.room_type, 'metric': q.metric}
    if q.metric != 'inventory':
        context = page_context or {}
        year = q.academic_year or context.get('academic_year')
        term = q.term or context.get('term')
        if not year or not term:
            current_year, current_term = await _term(session, tenant_id)
            year, term = year or current_year, term or current_term
        if not year or term not in ('1', '2'):
            return _tool_response('lookup_room_resources', ok=False, code='MISSING_SCOPE',
                message='资源配置数量已可查询；资源分配需要明确学年学期。', data=data, scope=scope)
        filters = [*base, RoomCohortAllocation.tenant_id == tenant_id,
            RoomCohortAllocation.academic_year == year, RoomCohortAllocation.term == term,
            RoomCohortAllocation.status == 'active', ResourceAllocationRule.tenant_id == tenant_id,
            ResourceAllocationRule.status == 'active']
        if q.cohort_label:
            filters.append(RoomCohortAllocation.cohort_label == q.cohort_label)
        allocation = select(RoomCohortAllocation.cohort_label, Room.id).select_from(RoomCohortAllocation).join(
            Room, Room.id == RoomCohortAllocation.room_id).join(
            ResourceAllocationRule, ResourceAllocationRule.id == RoomCohortAllocation.rule_id).where(*filters)
        allocated = (await session.execute(allocation)).all()
        cohorts = {}
        for cohort, room_id in allocated:
            cohorts.setdefault(cohort, set()).add(room_id)
        data['allocation'] = {'distinct_rooms': len({room_id for _, room_id in allocated}),
            'by_cohort': {cohort: len(ids) for cohort, ids in cohorts.items()},
            'source': 'active_room_cohort_allocations', 'unit': '间',
            'note': '共享教室按全校room_id去重，分届别数量不能直接相加；分配不等于课表实际使用。'}
        scope.update({'academic_year': year, 'term': term, 'cohort_label': q.cohort_label})
    return _tool_response('lookup_room_resources', message='已查询空间配置与资源分配；未读取课表。',
                          data=data, scope=scope)
