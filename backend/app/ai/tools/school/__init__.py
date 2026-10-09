"""教务只读 Tool：模型在工具循环里自主调用，按职责分包。

数字、人名、班级、规则一律以这里的查询结果为准，模型不得编造。
只读、按租户隔离、同进程直查库（不走 HTTP、不代写教务数据）。
写操作不在此层，等确认卡片机制落地后再加。
对应 Spring AI 的 Tool / FunctionCallback（后端可执行部分）。

职责分包（本包对外接口保持 `app.ai.tools.school` 不变）：
- people     人员：在职教师与班主任
- setup      准备度：网格/班级/课时/任教/规则组概况
- rules      规则：规则组与已启用规则
- capacity   容量验算：科目容量、课位角色规则、剩余课位
- generation 生成任务：状态与求解日志
- walk       走班：已保存教学班核对
- evidence   业务证据：学生选科、固定任课、合并课表、资源碰撞
- playbook   手册：操作说明书取回
- common     共享助手：参数解析、统一响应、范围与学期口径
"""
from __future__ import annotations

import asyncio
import logging

from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.tools.school import (
    capacity,
    evidence,
    planning,
    context as school_context,
    generation,
    people,
    playbook,
    rules,
    setup,
    walk,
)
from app.ai.tools.school.capacity import (
    lookup_remaining_capacity,
    lookup_slot_role_capacity,
    lookup_subject_capacity,
)
from app.ai.tools.school.common import (
    _LIST_CAP,
    _WEEK,
    _args,
    _term,
    _tool_response,
    _tool_scope,
    _when,
)
from app.ai.tools.school.generation import lookup_generation_log, lookup_generation_status
from app.ai.tools.school.people import lookup_teachers
from app.ai.tools.school.playbook import lookup_playbook
from app.ai.tools.school.rules import lookup_rules
from app.ai.tools.school.setup import lookup_schedule_setup
from app.ai.tools.school.walk import lookup_walk_classes

logger = logging.getLogger(__name__)

# 聚合顺序即对外呈现顺序；按职责分包后在此处集中声明，避免各模块隐式耦合顺序。
_TOOLS_BY_NAME: dict[str, dict] = {
    "lookup_teachers": people.TOOLS[0],
    "lookup_schedule_setup": setup.TOOLS[0],
    "lookup_rules": rules.TOOLS[0],
    "lookup_subject_capacity": capacity.TOOLS[0],
    "lookup_slot_role_capacity": capacity.TOOLS[1],
    "lookup_remaining_capacity": capacity.TOOLS[2],
    "lookup_generation_log": generation.TOOLS[0],
    "lookup_playbook": playbook.TOOLS[0],
    "lookup_generation_status": generation.TOOLS[1],
    "lookup_walk_classes": walk.TOOLS[0],
    'lookup_school_context': school_context.TOOL,
    **{tool['function']['name']: tool for tool in evidence.TOOLS},
    **{tool['function']['name']: tool for tool in planning.TOOLS},
}

SCHOOL_TOOLS: list[dict] = [_TOOLS_BY_NAME[name] for name in (
    "lookup_teachers",
    "lookup_schedule_setup",
    "lookup_rules",
    "lookup_subject_capacity",
    "lookup_slot_role_capacity",
    "lookup_remaining_capacity",
    "lookup_generation_log",
    "lookup_playbook",
    "lookup_generation_status",
    "lookup_walk_classes",
    'lookup_school_context',
    *evidence.DESCRIPTIONS,
    *planning.DESCRIPTIONS,
)]


async def execute_school_tool(
    name: str,
    arguments: str,
    *,
    session: AsyncSession,
    tenant_id: int,
    page_context: dict | None = None,
) -> str:
    """执行一个教务只读工具，返回给模型看的文本。

    这里的工具全部只读，因此仅对连接和超时做一次短退避重试；参数和业务错误
    不重试，直接交给模型澄清。规则草稿与确认写入不经过本函数。
    """
    async def dispatch() -> str:
        if name == 'lookup_school_context':
            return await school_context.lookup_school_context(session, tenant_id, arguments)
        if name in evidence.DESCRIPTIONS:
            return await evidence.execute(name, arguments, session=session,
                tenant_id=tenant_id, page_context=page_context)
        if name in planning.DESCRIPTIONS:
            return await planning.execute(name, arguments, session=session,
                tenant_id=tenant_id, page_context=page_context)
        context = page_context or {}
        args = _args(arguments)
        scope = {"academic_year": args.get("academic_year") or context.get("academic_year"), "term": args.get("term") or context.get("term")}
        if name == "lookup_walk_classes":
            if await school_context.timetable_mode(session, tenant_id) != 'walk_class':
                return _tool_response(name, ok=False, code='MODE_MISMATCH',
                    message='学校当前为行政班课表模式；请使用行政班任课或课表查询，不能把历史教学班当作当前走班结果。',
                    scope={'timetable_mode': 'administrative', 'mode_source': 'school_current_setting'})
            return await lookup_walk_classes(session, tenant_id, **scope,
                grade_id=args.get('grade_id') or (None if args.get('grade') else context.get('grade_id')),
                grade=args.get('grade'), subject=args.get('subject'))
        if name == "lookup_generation_status":
            result = await lookup_generation_status(str(args.get("job_id") or context.get("job_id") or ""), tenant_id)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "未找到" in result or "没有可核对" in result else "OK", scope=_tool_scope(args, page_context))
        if name == "lookup_teachers":
            result = await lookup_teachers(session, tenant_id, subject=str(args.get("subject") or ""), keyword=str(args.get("keyword") or ""), **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "没有匹配" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_schedule_setup":
            extra = {key: args[key] for key in ('grade_id', 'grade') if key in args}
            if not extra and context.get('grade_id') is not None:
                extra['grade_id'] = context['grade_id']
            result = await lookup_schedule_setup(session, tenant_id,
                class_id=args.get('class_id') or (None if extra else context.get('class_id')), **extra, **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "还没设置" in result or "未找到指定班级" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_rules":
            result = await lookup_rules(session, tenant_id, rule_group_id=args.get("rule_group_id") or context.get("rule_group_id"), **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "还没有规则组" in result or "未找到所选规则组" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_subject_capacity":
            result = await lookup_subject_capacity(session, tenant_id, grade=str(args.get("grade") or ""),
                grade_id=args.get('grade_id') or (None if args.get('grade') else context.get('grade_id')), **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "还没有班级" in result or "没有找到名称含" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_remaining_capacity":
            result = await lookup_remaining_capacity(session, tenant_id, grade=str(args.get("grade") or ""),
                grade_id=args.get('grade_id') or (None if args.get('grade') else context.get('grade_id')), **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "还没有班级" in result or "没有找到名称含" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_generation_log":
            result = await lookup_generation_log(str(args.get("job_id") or context.get("job_id") or ""), tenant_id)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "未找到" in result or "请先提供" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_slot_role_capacity":
            result = await lookup_slot_role_capacity(session, tenant_id,
                grade_id=args.get('grade_id') or context.get('grade_id'), **scope)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "没有启用" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        if name == "lookup_playbook":
            result = lookup_playbook(arguments)
            return _tool_response(name, message=result, code="EMPTY_RESULT" if "没有对上" in result else "OK", scope=_tool_scope(args, page_context), data={"text": result})
        names = ", ".join(t["function"]["name"] for t in SCHOOL_TOOLS)
        return _tool_response(name, ok=False, code="INVALID_ARGUMENT", message=f"没有名为「{name}」的工具。可用工具：{names}")

    try:
        return await dispatch()
    except (TimeoutError, ConnectionError) as exc:
        logger.warning("assistant.tool transient_retry name=%s error=%s", name, type(exc).__name__)
        try:
            await asyncio.sleep(0.2)
            return await dispatch()
        except Exception:
            logger.exception("assistant.tool retry_fail name=%s", name)
            return _tool_response(name, ok=False, code="TOOL_UNAVAILABLE", message=f"工具 {name} 暂时无法连接。请稍后重试，或让老师自己到对应页面核对。", retryable=True)
    except Exception:
        logger.exception("assistant.tool fail name=%s args=%s", name, (arguments or "")[:120])
        return _tool_response(name, ok=False, code="INTERNAL_ERROR", message=f"工具 {name} 查询失败。请换个问法，或让老师自己到对应页面核对。")
