"""部署迁移完成后补齐内置角色与菜单（幂等）。"""
from __future__ import annotations

import asyncio

from app.db.session import AsyncSessionLocal
from app.services.rbac import ensure_builtin_roles, ensure_menu_permissions


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await ensure_builtin_roles(session)
        await ensure_menu_permissions(session)
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
