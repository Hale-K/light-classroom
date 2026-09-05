from app.ai.advisor.intent import (
    clarify_reply,
    fallback_reply,
    is_ambiguous,
    parse_intent_payload,
    think_from_intent,
)


def test_parse_intent_keeps_catalog_pick():
    raw = """候选如下
{"candidates":[{"template":"教师课位禁排","why":"班主任不能排第5节"},{"template":"课位禁排","why":"也可能按学科"}],"pick":"教师课位禁排","family":"教师规则","target":"班主任","action":"禁止排课","weekday":"全周","periods":"第5节","avoid":"课位禁排"}
"""
    data = parse_intent_payload(raw)
    assert data is not None
    assert data["pick"] == "教师课位禁排"
    assert data["target"] == "班主任"
    assert data["periods"] == "第5节"
    think = think_from_intent(data)
    assert any("教师课位禁排" in line for line in think)


def test_homeroom_without_forbid_or_must_is_ambiguous():
    data = parse_intent_payload(
        '{"candidates":[{"template":"教师课位禁排","why":"禁排"},{"template":"课位教师角色","why":"必须上"}],"pick":"教师课位禁排","ask":true}'
    )
    assert data is not None
    assert is_ambiguous("班主任第五节", data) is True
    assert is_ambiguous("班主任第五节不能排", data) is False
    assert "点下面一个" in clarify_reply(data)


def test_parse_rejects_invented_component():
    assert parse_intent_payload('{"pick":"魔法禁排","candidates":[]}') is None


def test_fallback_reply_has_plus_and_component():
    data = {
        "pick": "教师课位禁排",
        "family": "教师规则",
        "target": "班主任",
        "action": "禁止排课",
        "weekday": "全周",
        "periods": "第5节",
        "avoid": "课位禁排",
        "candidates": [],
    }
    text = fallback_reply(data, True)
    assert "教师课位禁排" in text
    assert "规则明细" in text
    assert "已打开规则组" not in text
    assert "代保存" not in text
