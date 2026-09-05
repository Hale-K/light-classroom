from unittest.mock import patch

from app.ai.skill.catalog import OPTIONAL_BY_KEY, parse_picked_keys, retrieved_text, skills_for_keys
from app.ai.tools.retrieve import retrieve_skill


def test_parse_json_keys_keeps_order_and_cap():
    raw = '选这些：["05-rules", "11-pack", "02-hours", "05-rules"]'
    assert parse_picked_keys(raw) == ["05-rules", "11-pack"]


def test_parse_plain_keys_and_drops_core():
    assert parse_picked_keys("请看 00-role 和 05-rules") == ["05-rules"]


def test_parse_unrelated_is_empty():
    assert parse_picked_keys("[]") == []
    assert parse_picked_keys("没有相关说明书") == []


def test_bodies_only_for_picked_keys():
    text = retrieved_text(["05-rules"])
    assert "已取回的说明书" in text
    assert "规则组" in text
    assert "开课核对" not in text


def test_empty_pick_injects_nothing():
    assert retrieved_text([]) == ""
    assert skills_for_keys(["nope"]) == []


def test_pack_skill_has_no_school_names():
    pack = OPTIONAL_BY_KEY["11-pack"]
    blob = pack.when + pack.body
    for name in ("毛宇莹", "黄淑梅", "黄丽娟", "王淑华", "王璐", "张卓", "屈金", "杨元元"):
        assert name not in blob


async def test_retrieve_injects_model_picked_body():
    async def fake_complete(**kwargs):
        return '["05-rules"]'

    with patch("app.ai.tools.retrieve.complete_chat", side_effect=fake_complete):
        text = await retrieve_skill("物理要连堂", base_url="x", api_key="k", model="m", timeout=10)
    assert "连堂" in text
    assert "开课核对" not in text
