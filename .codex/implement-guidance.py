from pathlib import Path
root=Path('.')
def edit(name, old, new):
 p=root/name
 s=p.read_text(encoding='utf-8')
 assert old in s, (name,old[:60])
 p.write_text(s.replace(old,new),encoding='utf-8')
edit('backend/app/ai/agent/models.py','    plan: dict | None = None','    clarification: dict | None = None\n    plan: dict | None = None')
edit('backend/app/ai/gateway/tool.py','from app.ai.tools.task_plan import','from app.ai.tools.clarification import CLARIFICATION_TOOL, Clarification\nfrom app.ai.tools.task_plan import')
edit('backend/app/ai/gateway/tool.py','    task_plan: dict | None = None','    task_plan: dict | None = None\n    clarification: dict | None = None')
edit('backend/app/ai/gateway/tool.py','[*SCHOOL_TOOLS, FORMAT_MARKDOWN_TOOL,','[*SCHOOL_TOOLS, CLARIFICATION_TOOL, FORMAT_MARKDOWN_TOOL,')
edit('backend/app/ai/gateway/tool.py','        if name == "format_markdown":','        if name == "request_clarification":\n            try:\n                self.clarification = Clarification.model_validate_json(arguments).model_dump()\n            except ValueError:\n                return _tool_response(name, ok=False, code="INVALID_ARGUMENT", message="引导问题格式无效，请提供1至4个问题、唯一编号和简短选项。")\n            return _tool_response(name, ok=True, code="OK", message="已展示引导问题，等待用户补充。")\n        if name == "format_markdown":')
edit('backend/app/ai/agent/agent_loop.py','stop_when=lambda: (tool_scope.plan is not None or (','stop_when=lambda: (getattr(tool_scope, "clarification", None) is not None or tool_scope.plan is not None or (')
edit('backend/app/ai/harness/router.py','        "format_markdown",','        "format_markdown", "request_clarification",')
edit('backend/app/ai/harness/router.py','        "问题目标、对象或关键约束不清楚时，','        "关键决策缺失时调用request_clarification展示引导卡并等待，不只输出笼统反问。保留用户明确的约束，只问会改变结果的缺项，最多四题；可查询的学校模式、学年和学期先自动核对。用户补充后沿用先前条件，不能当成新任务。"\n        "问题目标、对象或关键约束不清楚时，')
edit('backend/app/ai/agent/assistant_agent.py','from app.ai.agent.models import AssistantTurn','from app.ai.agent.models import AssistantTurn\nfrom app.ai.tools.clarification import local_clarification')
edit('backend/app/ai/agent/assistant_agent.py','        text="规则草稿已准备，请核对下方内容后确认。" if plan else outcome.text,','        text="请补充下方关键决策，我会保留已明确的条件继续处理。" if getattr(tool_scope, "clarification", None) else ("规则草稿已准备，请核对下方内容后确认。" if plan else outcome.text),\n        clarification=getattr(tool_scope, "clarification", None),')
edit('backend/app/ai/agent/assistant_agent.py','        return AssistantTurn(text=CLARIFY_REPLY)','        return AssistantTurn(text="我会保留你已说明的条件。先补充下面的关键决策，再继续核对和规划。",\n            clarification=local_clarification(query, page_path))')
