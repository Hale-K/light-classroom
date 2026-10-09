import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError

from app.ai.model.chat import _post_chat, ChatOutcome
from app.api.v1.ai_provider import ProviderIn, _to_out, update_provider
from app.ai.agent.agent_loop import run_agent_loop
from app.ai.harness.router import GUIDE_HARNESS


@pytest.mark.asyncio
async def test_default_output_is_not_silently_capped_at_2048(monkeypatch):
    from app.ai.model import chat
    monkeypatch.setattr(chat.settings, "llm_max_tokens", 8192)
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "好"}}]})
    await _post_chat(base_url="http://test", api_key="", model="test", timeout=10,
        messages=[], temperature=0, max_tokens=None, transport=httpx.MockTransport(handler))
    assert captured[0]["max_tokens"] == 8192


@pytest.mark.parametrize("value", [0, -1, 1.5, 262145])
def test_provider_rejects_invalid_token_budget(value):
    with pytest.raises(ValidationError):
        ProviderIn(name="模型", base_url="http://test", max_output_tokens=value)


@pytest.mark.asyncio
async def test_edit_saves_output_budget_and_old_client_preserves_it():
    row = SimpleNamespace(id=1, tenant_id=7, max_output_tokens=16384)
    session = SimpleNamespace(get=AsyncMock(return_value=row), add=Mock(), commit=AsyncMock())
    await update_provider(1, ProviderIn(name="模型", base_url="http://test"), session, None, 7)
    assert row.max_output_tokens == 16384
    await update_provider(1, ProviderIn(name="模型", base_url="http://test", max_output_tokens=8192), session, None, 7)
    assert row.max_output_tokens == 8192


@pytest.mark.asyncio
async def test_agent_loop_passes_configured_tokens_to_model_gateway():
    complete = AsyncMock(return_value=ChatOutcome(text="你好"))
    gateway = SimpleNamespace(complete_tools=complete)
    scope = SimpleNamespace(definitions=[], execute=AsyncMock(), plan=None)
    await run_agent_loop([], "", base_url="http://test", api_key="", model="test", timeout=10,
        on_progress=None, on_trace=None, on_step=None, model_gateway=gateway,
        tool_scope=scope, harness=GUIDE_HARNESS, page_title=None, page_path=None,
        can=None, cannot=None, page_context=None, retrieved="", max_tokens=16384)
    assert complete.await_args.kwargs["max_tokens"] == 16384
