"""排课 Agent 的草稿与确认边界。模型只可提案，执行只接受服务端草稿 ID。

`proposal.py` 草稿的数据结构、构建校验与生成（模型经 propose_rules 工具提交）；
`confirm.py` 老师点确认后的服务端执行与审计。
公共 API 从这里出，外部按 `from app.ai.actions import ...` 使用。
"""
from app.ai.actions.confirm import check_action, decide_action
from app.ai.actions.proposal import (
    PROPOSE_RULES_TOOL,
    RuleRequest,
    RulesProposal,
    action_view,
    build_rule,
    fingerprint,
    propose_rules,
    resolve_targets,
)

__all__ = [
    "PROPOSE_RULES_TOOL",
    "RuleRequest",
    "RulesProposal",
    "action_view",
    "build_rule",
    "check_action",
    "decide_action",
    "fingerprint",
    "propose_rules",
    "resolve_targets",
]
