"""手册职责：按目录编号取回操作说明书正文。"""
from __future__ import annotations

from app.ai.skill.catalog import (
    OPTIONAL_BY_KEY,
    parse_picked_keys,
    retrieved_text,
    skills_for_keys,
)
from app.ai.tools.school.common import _args

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_playbook",
            "description": "取说明书正文（操作步骤细节）。编号必须来自 system 里的说明书目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 2,
                        "description": '来自 system 说明书目录的编号，如 ["05-rules"]；目录中不存在的编号不要猜。',
                    }
                },
                "required": ["keys"],
                "additionalProperties": False,
            },
        },
    },
]


def lookup_playbook(arguments: str) -> str:
    keys: list[str] = []
    raw = _args(arguments).get("keys")
    if isinstance(raw, list):
        keys = [str(k).strip() for k in raw if str(k).strip()]
    docs = skills_for_keys(keys) or skills_for_keys(parse_picked_keys(arguments or ""))
    if not docs:
        known = "、".join(sorted(OPTIONAL_BY_KEY)[:6]) + " 等"
        return f"编号没有对上说明书目录（有 {known}）。请从 system 目录里选 1~2 个编号再调一次。"
    return retrieved_text([d.key for d in docs])
