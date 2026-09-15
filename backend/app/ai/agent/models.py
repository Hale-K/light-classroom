"""教务 Agent 的数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AssistantTurn:
    """一次助手处理结果。"""

    text: str
    think: list[str] = field(default_factory=list)
    choices: list[dict] = field(default_factory=list)
    plan: dict | None = None
    jumps: list[dict] = field(default_factory=list)
    model_visible: bool = True
