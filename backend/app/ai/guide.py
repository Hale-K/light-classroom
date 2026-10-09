"""助手页面引导：只提供说明和跳转建议，不直接改变教师所在页面。"""
from __future__ import annotations

from app.ai.prompt.messages import GREET_REPLY
import operator
import re

_GREET = {"你好", "您好", "hi", "hello", "在吗", "在么", "嗨"}
_ARITHMETIC = re.compile(r"^\s*(\d{1,9})\s*([+\-*/×÷])\s*(\d{1,9})\s*(?:=\s*)?[?？]?\s*$")
_ARITHMETIC_OPS = {"+": operator.add, "-": operator.sub, "*": operator.mul, "×": operator.mul, "/": operator.truediv, "÷": operator.truediv}
_RULE_JUMP_PATH = "/scheduling?tab=rules"


class AssistantUiGuide:
    """把页面语境转成可展示的引导和需用户确认的跳转建议。"""

    @staticmethod
    def rule_jumps(query: str, text: str, page_path: str | None) -> list[dict]:
        if page_path and "tab=rules" in page_path:
            return []
        joined = f"{query or ''}\n{text or ''}"
        if "规则" not in joined:
            return []
        if not any(word in text for word in ("规则组", "组件", "禁排", "连堂", "课位", "班主任")):
            return []
        # 前端须将此建议呈现为“是否跳转”确认，而不能收到后直接导航。
        return [{"label": "去规则组", "path": _RULE_JUMP_PATH, "requires_confirmation": True}]

    @staticmethod
    def local_reply(text: str, page_path: str | None = None) -> str | None:
        q = (text or "").strip().rstrip("！!。.~～")
        if q.lower() in _GREET:
            return GREET_REPLY
        if page_path and any(word in q for word in ("下一步", "接下来", "该干什么", "该做什么", "先做什么")):
            return None
        return None

    @staticmethod
    def fast_reply(text: str) -> str | None:
        """处理无需模型、工具或向量检索的确定性小问题。"""
        match = _ARITHMETIC.fullmatch((text or "").strip())
        if not match:
            return None
        left, symbol, right = int(match.group(1)), match.group(2), int(match.group(3))
        if symbol in {"/", "÷"} and right == 0:
            return None
        result = _ARITHMETIC_OPS[symbol](left, right)
        rendered = str(int(result)) if isinstance(result, float) and result.is_integer() else str(result)
        return f"答案是 {rendered}。"

    @staticmethod
    def degraded_reply(query: str, page_path: str | None) -> str:
        """没有有效模型结果时，报告失败，不把业务说明冒充回答。"""
        return "模型服务暂时不可用，本次请求未完成。请稍后重试，或请管理员检查服务商状态。"


rule_jumps = AssistantUiGuide.rule_jumps
local_reply = AssistantUiGuide.local_reply
fast_reply = AssistantUiGuide.fast_reply
degraded_reply = AssistantUiGuide.degraded_reply
