"""CP-SAT 求解看门狗：max_time 之后仍不返回则 StopSearch。

OR-Tools 的搜索线程是原生代码，Python 无法强制 kill。
StopSearch 是官方允许的跨线程中止；若连这也不回，只能杀进程（独立 worker）。
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

# 求解器声明时限之外再给建模收尾 / 回调一点余量
DEFAULT_GRACE_SECONDS = 20.0


def solve_with_stop_deadline(
    solver,
    solve: Callable[[], T],
    *,
    max_time_seconds: float,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
) -> T:
    delay = max(1.0, float(max_time_seconds) + float(grace_seconds))

    def _stop() -> None:
        try:
            solver.StopSearch()
        except Exception:
            pass

    timer = threading.Timer(delay, _stop)
    timer.daemon = True
    timer.start()
    try:
        return solve()
    finally:
        timer.cancel()
