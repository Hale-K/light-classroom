"""生成任务职责：排课长任务的状态与求解日志查询（只读，不发起/重试/取消）。"""
from __future__ import annotations

import json

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_generation_log",
            "description": "只读读取本校排课生成长任务的求解事件日志（最近 40 条：阶段/进度/消息原文）。用于分析生成过程与失败过程。不会发起、重试或取消生成。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{32}$",
                        "description": "已知任务编号；不得编造。当前页面已有任务时可省略。",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_generation_status",
            "description": "只读查询本校当前学年学期的已有课表和生成任务状态；没有 job_id 时查询持久化的最近任务。任务日志缺失或过期不代表课表未生成；有课表不代表已排完整或无冲突。不会发起、重试或取消生成。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{32}$",
                        "description": "已知任务编号；不得编造。省略时仍可查询当前学期已有课表和最近生成任务。",
                    },
                    "academic_year": {"type": "string", "description": "用户明确指定的学年"},
                    "term": {"type": "string", "enum": ["1", "2"]},
                    "grade_id": {"type": "integer", "minimum": 1},
                    "class_id": {"type": "integer", "minimum": 1, "description": "行政班ID，不能使用教学班ID"},
                },
                "additionalProperties": False,
            },
        },
    },
]


async def lookup_saved_generation_status(session, tenant_id: int, job_id: str, *,
                                         academic_year=None, term=None,
                                         class_id=None, grade_id=None) -> str:
    """课表是持久业务结果；实时任务缓存不能作为课表是否存在的依据。"""
    from sqlalchemy import func, select
    from app.models.org import Class, Schedule, StudentClassMembership
    from app.models.gaokao import TeachingClass, TeachingClassSchedule, TeachingClassStudent
    from app.models.scheduling import SchedulingGenerateJob
    from app.ai.tools.school.common import _term
    from app.ai.tools.school.context import timetable_mode

    current_year, current_term = await _term(session, tenant_id)
    year, semester = academic_year or current_year, term or current_term
    if semester not in ('1', '2'):
        return '学期参数无效，请明确第1或第2学期；不能据此判断没有课表。'
    if class_id is not None:
        admin_class = (await session.execute(select(Class).where(
            Class.id == class_id, Class.tenant_id == tenant_id,
            Class.academic_year == year, Class.term == semester))).scalars().first()
        if admin_class is None or (grade_id is not None and admin_class.grade_id != grade_id):
            return '未匹配本校指定学期和年级的行政班，请确认班级范围；不能据此判断没有课表。'
    if not year:
        return "缺少查询学年，无法核对已有课表；不能据此判断尚未生成。请明确学年和学期。"
    mode = await timetable_mode(session, tenant_id)
    models = [(Schedule, Class, Schedule.class_id, "行政班")]
    if mode == "walk_class":
        models.append((TeachingClassSchedule, TeachingClass, TeachingClassSchedule.teaching_class_id, "教学班"))
    counts = []
    for model, group, class_column, label in models:
        statement = select(func.count(model.id)).where(
            model.tenant_id == tenant_id, model.academic_year == year, model.term == semester)
        if grade_id is not None:
            statement = statement.join(group, class_column == group.id).where(
                group.tenant_id == tenant_id, group.grade_id == grade_id)
        if class_id is not None:
            if model is Schedule:
                statement = statement.where(class_column == class_id)
            else:
                student_ids = select(StudentClassMembership.student_id).where(
                    StudentClassMembership.tenant_id == tenant_id,
                    StudentClassMembership.class_id == class_id,
                    StudentClassMembership.academic_year == year,
                    StudentClassMembership.term == semester,
                    StudentClassMembership.status == 'active')
                teaching_ids = select(TeachingClassStudent.teaching_class_id).where(
                    TeachingClassStudent.tenant_id == tenant_id,
                    TeachingClassStudent.student_id.in_(student_ids))
                statement = statement.where(class_column.in_(teaching_ids))
        count = (await session.execute(statement)).scalar_one()
        counts.append((label, count))
    total = sum(count for _, count in counts)
    scope = f"{year} 学年，第 {semester} 学期"
    if grade_id is not None:
        scope += f"，年级编号 {grade_id}"
    if class_id is not None:
        scope += f"，班级编号 {class_id}"
    lines = [f"已有课表（{scope}）：" + "、".join(f"{label} {count} 条课节记录" for label, count in counts) + "。"]
    async def live_status(identifier: str) -> str:
        try:
            return await lookup_generation_status(identifier, tenant_id)
        except (TimeoutError, ConnectionError):
            return "实时任务状态暂时无法查询；以上已保存课表和任务记录仍有效，不能据此判断没有课表。"
    if total:
        lines.append("当前范围已有保存的课表，可以继续查看和导出，无需为了查进度重新生成。是否全部排完、课时是否齐全和是否冲突需另行核对。")
    else:
        lines.append("当前范围未查到保存的课节，其他学期或范围可能有课表。")
    statement = select(SchedulingGenerateJob).where(SchedulingGenerateJob.tenant_id == tenant_id)
    if job_id:
        statement = statement.where(SchedulingGenerateJob.id == job_id)
    else:
        statement = statement.where(SchedulingGenerateJob.academic_year == year,
                                    SchedulingGenerateJob.term == semester)
    job = (await session.execute(statement.order_by(SchedulingGenerateJob.created_at.desc()).limit(1))).scalars().first()
    if job is None:
        lines.append("未查到对应的生成任务记录，无法确认实时进度；这不会影响已保存的课表。")
        if job_id:
            lines.append(await live_status(job_id))
    else:
        labels = {"queued": "等待处理", "running": "正在生成（持久化记录）", "done": "生成已完成", "error": "生成失败", "cancelled": "已取消"}
        lines.append(f"{'指定' if job_id else '本校该学期最近'}生成任务：{job.id}，{labels.get(job.status, job.status)}；任务学年学期：{job.academic_year} / {job.term}。")
        lines.append("上述为生成任务的历史记录；与当前保存的课表分别展示。")
        if job.message:
            lines.append(f"任务记录：{job.message}")
        if job.status in {"queued", "running"}:
            lines.append(await live_status(job.id))
        elif job.result:
            if job.result.get("created") is not None:
                lines.append(f"该任务生成了 {job.result['created']} 节课。")
            if job.result.get("unplaced") is not None:
                unplaced = job.result['unplaced']
                count = len(unplaced) if isinstance(unplaced, list) else unplaced
                lines.append(f"该任务未排入课节：{count} 节。")
    return "\n".join(lines)


async def lookup_generation_log(job_id: str, tenant_id: int) -> str:
    """读取生成长任务的求解事件日志（最近 40 条，含阶段/进度/消息），只读。"""
    import asyncio
    import time as _time
    from app.services.scheduling.generate_jobs import _redis, _job_key, get_job

    if not job_id:
        return "请先提供任务编号，或到排课页发起生成后再查询日志。"
    def snapshot():
        client = _redis()
        if client is not None:
            raw = client.get(_job_key(job_id))
            return json.loads(raw) if raw else None
        job = get_job(job_id)
        return job._snapshot() if job else None
    job = await asyncio.wait_for(asyncio.to_thread(snapshot), timeout=5)
    if not job or job.get("tenant_id") != tenant_id:
        return "本校未找到该生成任务的日志，任务可能已过期。请到排课页核对任务编号。"
    history = job.get("history") or []
    if not history:
        return "该任务还没有事件日志。"
    recent = history[-40:]
    lines = [f"生成任务日志（最近 {len(recent)} / 共 {len(history)} 条，状态：{job.get('status')}）："]
    for event in recent:
        ts = _time.strftime("%H:%M:%S", _time.localtime(event.get("ts") or _time.time()))
        stage = event.get("phase") or event.get("stage") or "-"
        percent = event.get("percent")
        pct = f" {percent}%" if isinstance(percent, (int, float)) and percent else ""
        message = (event.get("message") or "").strip()
        lines.append(f"[{ts}] {stage}{pct}：{message}" if message else f"[{ts}] {stage}{pct}")
    result = job.get("result")
    if result:
        lines.append(f"结果：已生成 {result.get('created', '?')} 节" + (f"，另有 {result.get('unplaced')} 节未排入" if result.get('unplaced') else ""))
    lines.append("以上为求解器事件原文；分析时结合 13-diagnose 的容量验算与 14-algorithm 的流程口径。")
    return "\n".join(lines)


async def lookup_generation_status(job_id: str, tenant_id: int) -> str:
    import asyncio
    import re
    import time
    from app.services.scheduling.generate_jobs import _redis, _job_key, get_job
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        return "请先到排课页选择或发起生成任务，再查询进度；当前没有可核对的任务编号。"
    def snapshot():
        client = _redis()
        if client is not None:
            raw = client.get(_job_key(job_id))
            return json.loads(raw) if raw else None
        job = get_job(job_id)
        return job._snapshot() if job else None
    job = await asyncio.wait_for(asyncio.to_thread(snapshot), timeout=5)
    if not job or job.get("tenant_id") != tenant_id:
        return "本校未找到该生成任务，任务可能已过期。请到排课页核对，不要据此重复生成。"
    latest = (job.get("history") or [{}])[-1]
    age = max(0, int(time.time() - latest.get("ts", job.get("created_at", time.time()))))
    labels = {"queued": "等待后台处理", "running": "正在生成", "done": "生成已完成", "error": "生成失败"}
    result = job.get("result") or {}
    return "\n".join([f"生成任务：{labels.get(job['status'], '状态待核对')}。", f"最近一次进展在 {age} 秒前：{latest.get('message') or '尚未收到求解进度'}。", "超过30秒没有进展时，只能说暂未收到更新，不能断言后台仍正常运行。" if age > 30 and job['status'] in ('queued', 'running') else "", f"已生成课节数：{result.get('created', '尚未返回')}。生成完成仍须检查未排课量和硬约束。", "取消助手查询不会取消排课生成任务。"])
