"""限流中间件（A5） - 内存滑动窗口实现

- 按 `客户端IP:路径` 维度计数，超过窗口上限返回 429。
- 开发期用进程内存（restart 即清零）；B4 接入 Redis 后替换为分布式计数，
  对外接口（is_allowed / remaining）保持不变。
"""
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.config import settings


class MemorySlidingWindowLimiter:
    """进程内滑动窗口限流器（每 key 一个 FIFO 时间戳队列）。"""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, window_seconds: float, limit: int) -> bool:
        """记录一次访问；窗口内超过 limit 返回 False（拒）。"""
        now = time.monotonic()
        q = self._hits[key]
        # 清理过期时间戳
        while q and now - q[0] >= window_seconds:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    async def is_allowed(self, request: Request) -> tuple[bool, int]:
        """返回 (是否放行, 窗口内剩余额度)。"""
        client = request.client.host if request.client else "unknown"
        key = f"{client}:{request.url.path}"
        allowed = self.hit(
            key, settings.rate_limit_window_seconds, settings.rate_limit_max_requests
        )
        return allowed, self._remaining(key)

    def _remaining(self, key: str) -> int:
        now = time.monotonic()
        q = self._hits.get(key)
        if not q:
            return settings.rate_limit_max_requests
        window = settings.rate_limit_window_seconds
        while q and now - q[0] >= window:
            q.popleft()
        return max(0, settings.rate_limit_max_requests - len(q))

    def clear(self) -> None:
        self._hits.clear()


limiter = MemorySlidingWindowLimiter()


async def rate_limit_middleware(request: Request, call_next):
    """统一限流：所有请求先过限流，超限返回 429。"""
    if not settings.rate_limit_enabled:
        return await call_next(request)

    allowed, remaining = await limiter.is_allowed(request)
    if not allowed:
        logger.warning(f"[rate-limit] 触发限流: {request.client.host if request.client else '?'} {request.method} {request.url.path}")
        return JSONResponse(
            status_code=429,
            content={
                "code": 429,
                "message": "请求过于频繁，请稍后再试",
                "data": {"retry_after": settings.rate_limit_window_seconds},
            },
            headers={"X-RateLimit-Remaining": str(remaining)},
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response