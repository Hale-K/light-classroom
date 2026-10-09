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
            "description": "只读查询本校已有排课生成长任务的真实状态；使用明确提供的 job_id，否则使用当前页面任务编号。不会发起、重试或取消生成。",
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
]


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
