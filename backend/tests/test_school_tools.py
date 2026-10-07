"""教务只读工具：schema 完整性、说明书取回、派发兜底。数据库查询部分不在单测覆盖。"""

def test_subject_capacity_tool_registered_with_capacity_hint():
    names = [t["function"]["name"] for t in SCHOOL_TOOLS]
    assert "lookup_subject_capacity" in names
    tool = next(t for t in SCHOOL_TOOLS if t["function"]["name"] == "lookup_subject_capacity")
    desc = tool["function"]["description"]
    assert "容量验算" in desc and "教师数" in desc

import asyncio
import json
from unittest.mock import AsyncMock

from app.ai.tools.school import SCHOOL_TOOLS, _when, execute_school_tool, lookup_playbook


def test_school_tools_schema_complete_and_unique():
    names = [t["function"]["name"] for t in SCHOOL_TOOLS]
    assert len(names) == len(set(names))
    assert "lookup_teachers" in names and "lookup_playbook" in names
    for tool in SCHOOL_TOOLS:
        fn = tool["function"]
        assert fn["description"], f"{fn['name']} 缺描述"
        assert fn["parameters"]["type"] == "object"


def test_when_formats_weekdays_and_periods():
    assert _when([1, 5], [5]) == "周一、周五，第5节"
    assert _when([], [2, 6]) == "第2、6节"
    assert _when([], []) == ""


def test_playbook_returns_body_for_valid_keys():
    text = lookup_playbook('{"keys":["05-rules"]}')
    assert text.startswith("已取回的说明书")
    assert "建立规则" in text


def test_playbook_falls_back_to_regex_and_rejects_unknown():
    assert lookup_playbook('{"keys":["99-magic"]}')
    assert "编号没有对上" in lookup_playbook('{"keys":["99-magic"]}')
    assert "编号没有对上" in lookup_playbook("随便说点什么")


def test_execute_dispatches_and_never_raises():
    text = asyncio.run(
        execute_school_tool("lookup_playbook", '{"keys":["04-teachers"]}', session=None, tenant_id=1)
    )
    result = json.loads(text)
    assert result["ok"] is True
    assert result["data"]["text"].startswith("已取回的说明书")

    unknown = asyncio.run(execute_school_tool("no_such_tool", "{}", session=None, tenant_id=1))
    unknown_result = json.loads(unknown)
    assert unknown_result["ok"] is False
    assert "没有名为" in unknown_result["message"]

    bad = asyncio.run(execute_school_tool("lookup_playbook", "{{{", session=None, tenant_id=1))
    bad_result = json.loads(bad)
    assert bad_result["status"] == "empty"
    assert "编号没有对上" in bad_result["message"]


def test_read_only_tool_retries_transient_failure(monkeypatch):
    from app.ai.tools import school

    call = AsyncMock(side_effect=[TimeoutError(), "查询成功"])
    monkeypatch.setattr(school, "lookup_generation_status", call)
    monkeypatch.setattr(school.asyncio, "sleep", AsyncMock())

    text = asyncio.run(execute_school_tool("lookup_generation_status", '{"job_id":"a"}', session=None, tenant_id=1))

    result = json.loads(text)
    assert result["ok"] is True
    assert result["code"] == "OK"
    assert result["data"]["text"] == "查询成功"
    assert call.await_count == 2
