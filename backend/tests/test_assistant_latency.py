import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.ai.agent.agent_loop import run_agent_loop
from app.ai.harness.router import QUERY_HARNESS, PLANNING_HARNESS
from app.ai.model.chat import ChatOutcome, _post_chat


@pytest.mark.asyncio
@pytest.mark.parametrize('harness, expected', [
    (QUERY_HARNESS, 'low'),
    (PLANNING_HARNESS, 'low'),
])
async def test_two_modes_use_bounded_glm_effort(harness, expected):
    complete = AsyncMock(return_value=ChatOutcome(text='回答'))
    await run_agent_loop([], '', base_url='https://open.bigmodel.cn/api/paas/v4', api_key='',
        model='glm-5.3-flash', timeout=60, on_progress=None, on_trace=None, on_step=None,
        model_gateway=SimpleNamespace(complete_tools=complete),
        tool_scope=SimpleNamespace(definitions=[], execute=AsyncMock(), plan=None), harness=harness,
        page_title=None, page_path=None, can=None, cannot=None, page_context=None, retrieved='')
    assert complete.await_args.kwargs.get('reasoning_effort') == expected


@pytest.mark.asyncio
async def test_reasoning_effort_reaches_http_without_lowering_output_budget():
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '回答'}}]})
    await _post_chat(base_url='http://test', api_key='', model='glm-5.3-flash', timeout=1,
        messages=[], temperature=.2, max_tokens=8192, reasoning_effort='low',
        transport=httpx.MockTransport(handler))
    assert payloads[0]['reasoning_effort'] == 'low'
    assert payloads[0]['max_tokens'] == 8192
    assert 'thinking' not in payloads[0]
