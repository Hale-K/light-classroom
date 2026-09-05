from app.ai.advisor.clarify import Q_LOW, Q_SCOPE, Q_STUCK, clarify
from app.ai.agent.teacher import local_reply


def test_vague_low_stays_in_jiaowu():
    hit = clarify("查询快用完的")
    assert hit is not None
    assert hit.ask is True
    assert hit.text == Q_LOW
    assert "商品" not in hit.text and "库存" not in hit.text


def test_other_domain_not_enumerated():
    hit = clarify("这份合同违约怎么起诉")
    assert hit is not None
    assert hit.code == "out_of_scope"
    assert hit.text == Q_SCOPE
    assert "法律" not in hit.text
    assert "旅游" not in hit.text
    assert "商品" not in hit.text


def test_low_with_teacher_not_ambiguous():
    hit = clarify("老师课时快满了")
    assert hit is not None
    assert hit.ask is False
    assert hit.code == "teacher_load"


def test_low_with_grid_not_ambiguous():
    hit = clarify("课位格子不够排")
    assert hit is not None
    assert hit.ask is False
    assert hit.code == "grid_cap"


def test_stuck_asks_generate_or_red():
    hit = clarify("卡住了出不来")
    assert hit is not None
    assert hit.ask is True
    assert hit.text == Q_STUCK


def test_hours_plan_not_swallowed_by_clarify():
    assert clarify("每周36个课时有多少学科怎么安排") is None


def test_clear_questions_pass_through():
    assert clarify("有多少语文老师") is None
    assert clarify("系统怎么用") is None
    assert clarify("生成课表要等多久") is None
    assert clarify("物理要连堂") is None
    assert clarify("导入学生名单") is None
    assert clarify("语文备课时段") is None


def test_ambiguous_low_asks_three_way():
    hit = clarify("快用完了")
    assert hit is not None
    assert hit.text == Q_LOW


def test_local_reply_greet_and_scope():
    assert "教务助手" in (local_reply("你好") or "")
    assert local_reply("这份合同违约怎么起诉") == Q_SCOPE
    assert local_reply("有多少语文老师") is None


def test_page_next_step_uses_page_context_instead_of_scope_rejection():
    assert local_reply("我下一步该干什么", "/campus-buildings?tab=resources") is None
