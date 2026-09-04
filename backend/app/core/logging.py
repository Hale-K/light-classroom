"""loguru 日志接入

- 一条一行，时间在最前，按发生顺序写文件
- 按天切分，只保留 7 天
- 每条带 trace_id；异常附完整栈
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from loguru import logger

from app.core.config import settings

_configured = False

# 时间 | 级别 | trace | 位置 | 内容 —— 方便按时间轴 grep / 对栈
_LINE = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level:<7} | "
    "{extra[trace_id]} | "
    "{name}:{function}:{line} | "
    "{message}"
)


class _InterceptHandler(logging.Handler):
    """uvicorn / fastapi 标准 logging 转到 loguru，和业务日志同一时间轴。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    logger.remove()
    logger.configure(extra={"trace_id": "-"})

    logger.add(
        sys.stdout,
        level="DEBUG" if settings.app_debug else "INFO",
        format=_LINE,
        colorize=False,
        diagnose=True,
        backtrace=True,
        enqueue=False,
    )

    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / f"{settings.app_env}_{{time:YYYY-MM-DD}}.log",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        level="INFO",
        format=_LINE,
        colorize=False,
        diagnose=True,
        backtrace=True,
        enqueue=True,
    )

    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.INFO, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        intercept = logging.getLogger(name)
        intercept.handlers = [_InterceptHandler()]
        intercept.propagate = False

    logger.info(f"日志系统已初始化 env={settings.app_env} retention=7d")
