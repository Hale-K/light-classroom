"""Build the model-visible projection of an assistant conversation.

The durable conversation remains the UI/audit record. The projection excludes
transport failures, task recovery notices, and degraded-mode boilerplate so a
later model call cannot learn those messages as if they were assistant answers.
"""
from __future__ import annotations

from collections.abc import Iterable


_NON_DIALOGUE_PREFIXES = (
    "network error",
    "暂时无法连接后台",
    "后台暂时无法连接",
    "模型服务暂时不可用，助手已进入本地说明模式",
    "当前模型工具调用不可用，本轮仅提供说明",
    "所有模型通道暂不可用",
    "处理失败，请重试",
    "本轮等待超过",
    "任务仍在后台运行，暂未收到结束状态",
    "已停止。",
)


def is_model_visible(message: dict) -> bool:
    """Return whether a durable/UI message may be replayed to the model."""
    # A client must not be able to hide its latest instruction and make the
    # assistant accidentally continue an older user request.
    if message.get("role") == "user":
        return True
    if message.get("model_visible") is False:
        return False
    if message.get("role") != "assistant":
        return True
    text = " ".join(str(message.get("content") or "").split()).lower()
    return bool(text) and not text.startswith(_NON_DIALOGUE_PREFIXES)


def project_messages(messages: Iterable[dict], *, limit: int | None = None) -> list[dict]:
    """Return role/content messages that are safe to place in an LLM prompt."""
    projected: list[dict] = []
    for item in messages:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role not in ("user", "assistant", "system") or not content:
            continue
        candidate = {**item, "role": role, "content": content}
        if is_model_visible(candidate):
            projected.append({"role": role, "content": content})
    return projected[-limit:] if limit is not None else projected


def project_summary(summary: str) -> str:
    """Remove legacy non-dialogue assistant lines from an existing summary."""
    kept: list[str] = []
    for raw in (summary or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("助手："):
            item = {"role": "assistant", "content": line.removeprefix("助手：")}
            if not is_model_visible(item):
                continue
        elif not is_model_visible({"role": "assistant", "content": line}):
            # MAX_SUMMARY_CHARS may have cut the speaker prefix from the first
            # legacy line; known operational boilerplate is still removable.
            continue
        kept.append(line)
    return "\n".join(kept)
