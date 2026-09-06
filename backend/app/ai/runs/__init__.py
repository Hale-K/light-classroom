"""助手任务域：可恢复查看的运行记录、进度心跳、提交与取消。

service 按需加载（PEP 562）：建表注册等场景只 import 本包时会连带拉起
actions/scheduling 的服务链，造成循环导入；progress 只依赖标准库，可安全急切导出。
"""
from app.ai.runs.progress import TOOL_LABELS, Progress, drive_turn, report_progress

_SERVICE_EXPORTS = ("create_run", "execute_run", "get_run", "get_run_trace", "run_view", "spawn_run")

__all__ = ["Progress", "TOOL_LABELS", "drive_turn", "report_progress", *_SERVICE_EXPORTS]


def __getattr__(name: str):
    if name in _SERVICE_EXPORTS:
        from app.ai.runs import service

        return getattr(service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
