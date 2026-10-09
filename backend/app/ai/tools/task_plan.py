"""Ephemeral task planning. These tools never mutate school business data."""
from __future__ import annotations

import json
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Literal


class PlanStep(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=100)


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    goal: str = Field(min_length=1, max_length=300)
    steps: list[PlanStep] = Field(min_length=1, max_length=12)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_id: str = Field(min_length=1, max_length=40)
    status: Literal['pending', 'running', 'completed', 'failed', 'blocked']
    summary: str = Field(default='', max_length=500)


TASK_PLAN_TOOLS = [
    {'type': 'function', 'function': {'name': 'plan_task',
        'description': '为本轮复杂任务列出可跟踪的取证、方案、校验、汇总步骤；仅更新执行计划，不修改业务。只创建一次。',
        'parameters': TaskPlan.model_json_schema()}},
    {'type': 'function', 'function': {'name': 'update_plan_task',
        'description': '更新本轮计划中一个步骤的实际状态及证据摘要。无证据不得标完成，缺数据标blocked。',
        'parameters': TaskUpdate.model_json_schema()}},
]


def execute_task_plan(name: str, arguments: str, plan: dict | None) -> tuple[str, dict | None]:
    try:
        if name == 'plan_task':
            if plan is not None:
                raise ValueError('已有计划，请逐步更新，不能覆盖已完成证据。')
            request = TaskPlan.model_validate_json(arguments)
            ids = [step.id for step in request.steps]
            if len(ids) != len(set(ids)):
                raise ValueError('步骤ID不能重复。')
            plan = {'goal': request.goal, 'steps': [dict(**step.model_dump(), status='pending', summary='') for step in request.steps]}
        else:
            request = TaskUpdate.model_validate_json(arguments)
            if plan is None:
                raise ValueError('先创建本轮任务计划。')
            found = next((step for step in plan['steps'] if step['id'] == request.task_id), None)
            if found is None:
                raise ValueError('计划中没有这个步骤。')
            if request.status in {'completed', 'failed', 'blocked'} and not request.summary.strip():
                raise ValueError('完成、失败或阻塞时必须提供证据或原因摘要。')
            found.update(status=request.status, summary=request.summary)
        return json.dumps({'ok': True, 'code': 'OK', 'data': {'plan': plan}}, ensure_ascii=False), plan
    except (ValidationError, ValueError) as exc:
        return json.dumps({'ok': False, 'code': 'INVALID_PLAN', 'message': str(exc)[:800]}, ensure_ascii=False), plan
