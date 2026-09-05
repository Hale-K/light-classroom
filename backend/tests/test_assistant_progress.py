import asyncio

import pytest

from app.ai.graph.loop import run_tool_loop
from app.ai.model.chat import ChatOutcome, ToolCallOut
from app.ai.progress import drive_turn


@pytest.mark.asyncio
async def test_progress_precedes_slow_model_and_tool():
    events = []
    replies = [ChatOutcome(tool_calls=[ToolCallOut(id="1", name="lookup_rules", arguments="{}")]), ChatOutcome(text="已查到")]
    async def report(phase, message):
        events.append((phase, message))
    async def caller(**kwargs):
        assert events[-1][0] == "model"
        return replies.pop(0)
    async def executor(*args):
        assert events[-1] == ("tool", "正在查询本校规则组")
        return "有一个规则组"
    await run_tool_loop(base_url="x", api_key="", model="x", timeout=1, messages=[], tools=[], executor=executor, caller=caller, on_progress=report)
    assert [phase for phase, _ in events] == ["model", "tool", "observed", "model"]


@pytest.mark.asyncio
async def test_heartbeat_continues_when_model_has_no_new_output():
    beats = []
    async def work():
        await asyncio.sleep(.04)
        return "finished"
    async def heartbeat():
        beats.append(True)
        return True
    assert await drive_turn(work(), heartbeat, interval=.005, timeout=.2) == "finished"
    assert len(beats) >= 2


@pytest.mark.asyncio
async def test_cancel_and_timeout_stop_underlying_work():
    for cancelled in (True, False):
        stopped = asyncio.Event()
        async def work():
            try:
                await asyncio.sleep(5)
            finally:
                stopped.set()
        async def heartbeat():
            return not cancelled
        with pytest.raises(asyncio.CancelledError if cancelled else TimeoutError):
            await drive_turn(work(), heartbeat, interval=.005, timeout=.02)
        assert stopped.is_set()
