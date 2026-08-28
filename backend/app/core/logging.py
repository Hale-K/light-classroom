"""loguru 日志接入（B9）

- 统一格式化，带时间 / 级别 / 模块
- 控制台 + 按天滚动文件（logs/{app_env}_%Y%m%d.log）
- 可被 import 多次，幂等（全局标志）
"""
import sys
from pathlib import Path
from loguru import logger
from app.core.config import settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # 控制台
    logger.remove()
    logger.add(sys.stdout, level="DEBUG" if settings.app_debug else "INFO", format=fmt)

    # 滚动文件日志（logs/ 目录自动创建）
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / f"{settings.app_env}_%Y%m%d.log",
        rotation="00:00",
        retention="14 days",
        encoding="utf-8",
        level="INFO",
        format=fmt,
        enqueue=True,
    )
    logger.bind(run=settings.app_env).info(f"日志系统已初始化 env={settings.app_env}")