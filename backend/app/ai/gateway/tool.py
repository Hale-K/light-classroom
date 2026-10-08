"""Tool Gateway: per-turn authorization, dispatch, proposal state, and audit."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.actions import PROPOSE_RULES_TOOL, RulesProposal, action_view, propose_rules
from app.ai.runs.events import TraceCallback
from app.ai.tools.school import SCHOOL_TOOLS, _term, execute_school_tool
from app.ai.harness.router import GUIDE_HARNESS


@dataclass
class ToolScope:
    """A single Turn's immutable authority plus mutable proposal result."""

    session: AsyncSession
    tenant_id: int
    user_id: int | None
    can_manage_rules: bool
    page_context: dict | None
    allowed_tools: frozenset[str] | None = None
    on_trace: TraceCallback | None = None
    plan: dict | None = None
    _plan_mode: bool = field(init=False, default=False)

    def __post_init__(self):
        # Snapshot request mode once: neither later page metadata nor model output can unlock it.
        self._plan_mode = (self.page_context or {}).get('assistant_mode') == 'plan'

    @property
    def definitions(self) -> list[dict]:
        tools = [*SCHOOL_TOOLS, *([PROPOSE_RULES_TOOL] if self.can_manage_rules else [])]
        if self._plan_mode:
            tools = [item for item in tools if item['function']['name'] in GUIDE_HARNESS.allowed_tools]
        if self.allowed_tools is None:
            return tools
        return [item for item in tools if item["function"]["name"] in self.allowed_tools]

    async def execute(self, name: str, arguments: str) -> str:
        allowed = {item["function"]["name"] for item in self.definitions}
        if name not in allowed:
            if self.on_trace:
                await self.on_trace("tool.denied", {"tool": name, "reason": "not_allowed"})
            return "工具未被授权，已拒绝执行。"
        if name != "propose_rules":
            return await execute_school_tool(
                name,
                arguments,
                session=self.session,
                tenant_id=self.tenant_id,
                page_context=self.page_context,
            )
        return await self._propose_rules(arguments)

    async def _propose_rules(self, arguments: str) -> str:
        if self._plan_mode:
            return '计划模式仅提供方案，已拒绝生成规则草稿。'
        if not self.can_manage_rules or self.user_id is None:
            return "当前账号没有排课配置权限，请由教务管理员确认配置。"
        if self.plan is not None:
            return "本轮已经生成草稿，请先让老师核对，下一轮再修改。"
        try:
            year, term = await _term(self.session, self.tenant_id) if self.page_context else (None, None)
            context = self.page_context or {}
            if (
                (context.get("academic_year") and context["academic_year"] != year)
                or (context.get("term") and context["term"] != term)
            ):
                return (
                    "当前页面与学校当前学期不同。规则草稿暂只支持学校当前学期，"
                    "请先切换页面或到规则工作台手动配置，不能改到另一个学期。"
                )
            proposal = RulesProposal.model_validate_json(arguments)
            action = await propose_rules(self.session, self.tenant_id, self.user_id, proposal)
            self.plan = action_view(action)
            return "草稿已准备，尚未保存规则：\n" + self.plan["summary"]
        except ValueError as exc:
            return "草稿未生成，请澄清：" + str(exc)[:700]


class ToolGateway:
    """Creates a fresh, tenant-scoped tool boundary for each Agent Turn."""

    def open_scope(
        self,
        *,
        session: AsyncSession,
        tenant_id: int,
        user_id: int | None,
        can_manage_rules: bool,
        page_context: dict | None,
        allowed_tools: frozenset[str] | None = None,
        on_trace: TraceCallback | None = None,
    ) -> ToolScope:
        return ToolScope(
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            can_manage_rules=can_manage_rules,
            page_context=page_context,
            allowed_tools=allowed_tools,
            on_trace=on_trace,
        )
