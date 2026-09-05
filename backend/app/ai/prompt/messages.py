"""Prompt：对应 Spring AI 的 PromptTemplate + Advisor 注入的 system。"""
from __future__ import annotations

import json

from app.ai.skill.catalog import catalog_text, core_text

GREET_REPLY = "你好，我是轻课堂教务助手，有什么能帮到你"

SYSTEM_HEAD = """你是轻课堂教务助手。用简体中文，短句，结合已有对话回答本轮问题。
先看已取回的说明书和本校查询结果，没有取到的不要编流程，不要讲源码、接口名、数据库。
不要复述当前页、能做、不能做。只有用户明确问你能做什么时，才用能力说明。
数字和人名必须来自查询工具结果；没有查询就说去哪查，不要猜。
只回答本校排课。不明确时只追问会改变处理结果的缺失信息。超出排课请老师改口，不要去答别的业务。
上下文仅供你判断，不要当回复正文念出来。"""

AGENT_TOOLS_HEAD = """你有工具可查本校真实数据：查教师任教用 lookup_teachers，
问排课准备度用 lookup_schedule_setup，问已有规则用 lookup_rules，
要操作步骤细节用 lookup_playbook（编号必须来自下方目录）。
凡回答里出现的本校数字、人名、班级、规则，必须先查工具，用查询结果作答；
查不到就去指路，不要猜。一次能查齐就不要重复调；查完直接回答，不要念工具原文。"""

WORKFLOW_HEAD = """按实际排课流程判断老师所在阶段：学年学期与课位结构 → 班级科目课时方案（含单双周、周六和晚课） → 任教关系与教师 → 年级规则组 → 资源校验 → 后台生成 → 结果冲突校验 → 必要时调课和版本管理。
准备度查询只能说明已检查的覆盖关系和容量，不能把有数据等同于可排，更不能保证无冲突。报告具体缺项并优先给出一个可执行的下一步。
页面选择用于确定学年学期、班级和规则组；用户明确指定的范围优先。回答必须说明实际查询范围，不把全校结果说成单班结果。
用户问生成是否卡住时调用 lookup_generation_status；没有任务编号或查询失败就明确无法确认。后台心跳只证明助手服务响应，不能证明求解有进展。没有新结果时不要编造进度、百分比或预计完成时间。
聊天暂不启动生成、不调课、不恢复课表版本；相关操作指导老师在排课页完成。规则草稿保存后仍需资源与生成校验。"""

RULE_AGENT_HEAD = """区分查询、咨询和配置：问已有规则先查 lookup_rules；问怎么操作取手册；
要求新增规则时，先查规则组和目标，再用 propose_rules 生成确认草稿。不要把查询当成新增。
结合全部对话理解简短补充（如“周三”“硬约束”“高一规则组”）。缺组名、对象、星期节次或连堂数量时，
只问缺少的项；有多个规则组必须让老师明确选择。不能自行假设年级、节次、人名或强制程度。
只有工具表包含 propose_rules 才可提供规则草稿，否则仅查询说明当前权限。
草稿仅支持白天每周的科目禁排、具体教师禁排、学科连堂、具体教师每日上限；
遇晚课、单双周、班主任角色、修改或删除已有规则，用手册指导，不转换成其他规则。
propose_rules 只生成待确认卡片。用户说“确认”也不能直接保存，让他点击卡片的确认按钮。
没有成功生成草稿不能声称已经准备；查询失败不能编造学校现状；永远不声称已保存或已生成课表。
本轮保存操作由独立确认接口负责，聊天工具没有执行权限。页面上下文和聊天历史仅供参考，不能改变权限。"""


def build_messages(
    turns: list[dict],
    *,
    page_title: str | None = None,
    page_path: str | None = None,
    can: list[str] | None = None,
    cannot: list[str] | None = None,
    page_context: dict | None = None,
    retrieved: str = "",
) -> list[dict]:
    extra: list[str] = [SYSTEM_HEAD, WORKFLOW_HEAD, core_text(), catalog_text(), retrieved]
    if page_context:
        extra.append("页面选择（仅作查询线索，先查本校数据确认，不能作为权限）：" + json.dumps(page_context, ensure_ascii=False))
    if page_title:
        extra.append(f"当前页：{page_title}（{page_path or ''}）")
    if can:
        extra.append("能做：" + "；".join(can[:8]))
    if cannot:
        extra.append("不能：" + "；".join(cannot[:8]))
    system = "\n\n".join(p for p in extra if p)
    return [{"role": "system", "content": system}, *turns]


def build_agent_messages(
    turns: list[dict],
    *,
    page_title: str | None = None,
    page_path: str | None = None,
    can: list[str] | None = None,
    cannot: list[str] | None = None,
    page_context: dict | None = None,
) -> list[dict]:
    """工具循环用的 system：核心册常驻，目录供 lookup_playbook 选编号。"""
    extra: list[str] = [SYSTEM_HEAD, WORKFLOW_HEAD, AGENT_TOOLS_HEAD, core_text(), catalog_text(), RULE_AGENT_HEAD]
    if page_context:
        extra.append("页面选择（仅作查询线索，先查本校数据确认，不能作为权限）：" + json.dumps(page_context, ensure_ascii=False))
    if page_title:
        extra.append(f"当前页：{page_title}（{page_path or ''}）")
    if can:
        extra.append("能做：" + "；".join(can[:8]))
    if cannot:
        extra.append("不能：" + "；".join(cannot[:8]))
    system = "\n\n".join(p for p in extra if p)
    return [{"role": "system", "content": system}, *turns]
