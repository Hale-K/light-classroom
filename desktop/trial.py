"""Local desktop trial. This is a convenience gate, not tamper-proof licensing."""
from __future__ import annotations

import html
import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def bundled_trial_days() -> int:
    # Generated into the Python archive by the spec, not read from editable JSON.
    try:
        from _trial_policy import TRIAL_DAYS
    except ImportError:
        if getattr(sys, "frozen", False):
            raise ValueError("试用配置缺失，请重新安装完整客户端")
        return 0
    if type(TRIAL_DAYS) is not int or not 0 <= TRIAL_DAYS <= 3650:
        raise ValueError("试用配置无效，请重新安装完整客户端")
    return TRIAL_DAYS


class TrialGuard:
    def __init__(self, path: Path, days: int, *, clock=time.time, monotonic=time.monotonic):
        if type(days) is not int or not 1 <= days <= 3650:
            raise ValueError("试用天数必须为 1 至 3650")
        self.path, self.days = path, days
        self.clock, self.monotonic = clock, monotonic
        self.lock = threading.Lock()
        self.origin = clock()
        self.tick = monotonic()
        self.saved_at = self.tick
        self.error = ""
        self.state = {}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                state = dict(started=self.origin, last_seen=self.origin,
                             expires=self.origin + days * 86400, expired=False)
                try:
                    with path.open("x", encoding="utf-8") as stream:
                        json.dump(state, stream)
                except FileExistsError:
                    pass
            self.state = json.loads(path.read_text(encoding="utf-8"))
            values = [self.state[key] for key in ("started", "last_seen", "expires")]
            if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0 for value in values):
                raise ValueError("invalid timestamps")
            if type(self.state["expired"]) is not bool or not values[0] <= values[1] or not values[0] < values[2]:
                raise ValueError("invalid trial record")
            # Repackaging must not restart or lengthen an existing trial.
            self.state["expires"] = min(self.state["expires"], self.state["started"] + days * 86400)
            self._save()
        except (OSError, ValueError, KeyError, TypeError):
            self.error = "无法读取或保存试用记录，请联系软件提供方。已有业务数据已保留。"

    def _save(self):
        staging = self.path.with_suffix(f".{os.getpid()}.tmp")
        try:
            staging.write_text(json.dumps(self.state), encoding="utf-8")
            os.replace(staging, self.path)
        finally:
            staging.unlink(missing_ok=True)

    def check(self) -> str:
        with self.lock:
            if self.error:
                return self.error
            wall = self.clock()
            now = max(wall, self.origin + self.monotonic() - self.tick, self.state["last_seen"])
            if not self.path.is_file():
                self.error = "试用记录缺失，请联系软件提供方。已有业务数据已保留。"
                return self.error
            expired = self.state["expired"] or now >= self.state["expires"]
            if expired or self.monotonic() - self.saved_at >= 60:
                self.state.update(last_seen=now, expired=expired)
                try:
                    self._save()
                    self.saved_at = self.monotonic()
                except OSError:
                    self.error = "无法保存试用记录，请检查磁盘权限或联系软件提供方。"
                    return self.error
            if expired:
                self.error = "试用期已结束，请联系软件提供方获取正式版。已有业务数据已保留。"
                return self.error
            if wall < self.state["last_seen"] - 300:
                return "检测到系统时间回拨，请校准电脑日期和时间后重新启动。"
            return ""

    def title(self) -> str:
        if not self.state:
            return "轻课堂 · 试用版"
        deadline = datetime.fromtimestamp(self.state["expires"], timezone.utc).astimezone()
        return f"轻课堂 · 试用版（至 {deadline:%Y-%m-%d %H:%M}）"


def blocked_html(message: str) -> str:
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<title>轻课堂 · 试用提示</title><body style="margin:0;background:#f5f8fc;'
            'font:18px Microsoft YaHei,sans-serif;color:#16334d;display:grid;'
            'place-items:center;min-height:100vh"><main style="max-width:600px;padding:48px">'
            '<h1>轻课堂 · 试用提示</h1><p style="line-height:1.8">'
            + html.escape(message) + '</p><p>您可以关闭此窗口。</p></main></body></html>')


class TrialMiddleware:
    """Enforce expiry for local APIs as well as browser/WebView navigation."""
    def __init__(self, app, guard):
        self.app, self.guard = app, guard

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            message = self.guard.check()
            if message:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4403})
                else:
                    from starlette.responses import HTMLResponse, JSONResponse
                    if scope.get("path", "").startswith("/api/"):
                        response = JSONResponse({"detail": message, "code": "TRIAL_BLOCKED"}, status_code=403)
                    else:
                        response = HTMLResponse(blocked_html(message), status_code=403)
                    response.headers["Cache-Control"] = "no-store"
                    await response(scope, receive, send)
                return
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return
        # Existing WebSocket sessions must not keep working after the deadline.
        import asyncio

        task = asyncio.create_task(self.app(scope, receive, send))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=1)
                if not task.done() and self.guard.check():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await send({"type": "websocket.close", "code": 4403})
                    return
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
