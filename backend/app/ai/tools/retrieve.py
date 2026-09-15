"""Tool：对应 Spring AI FunctionCallback / @Tool。

可执行的取回在本包；查档案、网格、写课时目前由浏览器 JWT 调教务 API
（frontend `assistant/run.ts`），后端不代调、不走 MCP。
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.ai.model.chat import ChatError, complete_chat
from app.ai.skill.catalog import catalog_text, parse_picked_keys, retrieved_text

logger = logging.getLogger(__name__)

_ROUTER = """你只做一件事：根据用户这一句，从目录里选出最多 2 本说明书。
只输出 JSON 数组，例如 ["05-rules"] 或 ["05-rules","11-pack"]。
都不相关就输出 []。不要解释，不要编目录里没有的编号。
说明书是跨校模板，不要按某校教师姓名选题。"""


async def retrieve_skill(
    query: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    complete: Callable[..., Awaitable[str]] = complete_chat,
) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    try:
        raw = await complete(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=min(timeout, 30),
            temperature=0,
            max_tokens=80,
            messages=[
                {"role": "system", "content": _ROUTER + "\n\n" + catalog_text()},
                {"role": "user", "content": q},
            ],
        )
    except ChatError as exc:
        logger.warning("assistant.retrieve fail err=%s", exc.message)
        return ""
    keys = parse_picked_keys(raw)
    logger.info("assistant.retrieve keys=%s", ",".join(keys) or "-")
    return retrieved_text(keys)
