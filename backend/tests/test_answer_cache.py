"""助手回答缓存：键维度、静态/动态分类、TTL 过期、不缓存空回答。"""
from app.utils import answer_cache as cache
from app.utils.answer_cache import (
    answer_cache_key,
    classify_steps,
    get_cached_answer,
    put_cached_answer,
)

_TURNS = [{"role": "user", "content": "周六晚课必须班主任怎么配"}]


def _key(**overrides):
    kwargs = dict(
        tenant_id=1,
        model="glm-4",
        turns=_TURNS,
        page_path="/settings",
        can_manage_rules=True,
        page_context=None,
    )
    kwargs.update(overrides)
    return answer_cache_key(**kwargs)


def setup_function():
    cache._MEMORY.clear()


def test_key_is_stable_and_sensitive_to_context():
    base = _key()
    assert base == _key()
    assert base != _key(tenant_id=2)
    assert base != _key(model="deepseek")
    assert base != _key(page_path="/scheduling?tab=rules")
    assert base != _key(can_manage_rules=False)
    assert base != _key(page_context={"rule_group_id": "g1"})
    assert base != _key(harness_name="diagnosis")
    assert base != _key(turns=[{"role": "user", "content": "换个问题"}])


def test_classify_steps_static_needs_only_playbook():
    assert classify_steps(["lookup_playbook"]) == "static"
    assert classify_steps(["lookup_playbook", "lookup_playbook"]) == "static"
    assert classify_steps(["lookup_rules"]) == "dynamic"
    assert classify_steps(["lookup_playbook", "lookup_rules"]) == "dynamic"
    assert classify_steps([]) == "dynamic", "纯对话按动态短缓存"


def test_put_get_roundtrip():
    key = _key()
    kind = put_cached_answer(
        key, text="答案正文", think=["lookup_playbook：规则手册"], jumps=[], tools=["lookup_playbook"],
    )
    assert kind == "static"
    cached = get_cached_answer(key)
    assert cached == {
        "text": "答案正文",
        "think": ["lookup_playbook：规则手册"],
        "jumps": [],
        "kind": "static",
    }


def test_dynamic_entry_expires_and_static_lives_longer():
    key = _key()
    put_cached_answer(key, text="动态答案", think=[], jumps=[], tools=["lookup_rules"])
    assert get_cached_answer(key) is not None

    real_time = cache.time.time
    cache.time.time = lambda: real_time() + 200
    try:
        assert get_cached_answer(key) is None, "动态缓存 2 分钟后应过期"
    finally:
        cache.time.time = real_time

    put_cached_answer(key, text="静态答案", think=[], jumps=[], tools=["lookup_playbook"])
    cache.time.time = lambda: real_time() + 200
    try:
        assert get_cached_answer(key) is not None, "静态缓存不应在 200 秒后过期"
    finally:
        cache.time.time = real_time


def test_empty_answer_not_cached():
    key = _key()
    assert put_cached_answer(key, text="  ", think=[], jumps=[], tools=["lookup_playbook"]) is None
    assert get_cached_answer(key) is None
