"""Create idempotent principal accounts for each registered gaokao mode."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal, engine
from app.models.enums import BaseUserRole, TenantType
from app.models.org import Tenant, User


PASSWORD = "Principal@2026"
SCHOOLS = (
    ("gaokao312", "广东新高考实验中学", "广东", "3+1+2", "周校长", "18820261001"),
    ("gaokao33", "浙江新高考实验中学", "浙江", "3+3", "吴校长", "18820261002"),
    ("gaokao-traditional", "西藏传统高考实验中学", "西藏", "traditional", "郑校长", "18820261003"),
)


async def seed() -> None:
    engine.echo = False
    async with AsyncSessionLocal() as session:
        results = []
        for code, school_name, province, mode, principal_name, phone in SCHOOLS:
            tenant = (await session.execute(select(Tenant).where(Tenant.code == code))).scalar_one_or_none()
            if tenant is None:
                tenant = Tenant(
                    code=code,
                    name=school_name,
                    type=TenantType.org,
                    province=province,
                    gaokao_mode=mode,
                )
                session.add(tenant)
                await session.flush()
            else:
                tenant.name = school_name
                tenant.province = province
                tenant.gaokao_mode = mode

            principal = (await session.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
            if principal is None:
                principal = User(
                    tenant_id=tenant.id,
                    name=principal_name,
                    phone=phone,
                    password_hash=get_password_hash(PASSWORD),
                    role=BaseUserRole.director,
                )
                session.add(principal)
            elif principal.tenant_id != tenant.id:
                raise RuntimeError(f"手机号已属于其他学校: {phone}")
            else:
                principal.name = principal_name
                principal.role = BaseUserRole.director
                principal.password_hash = get_password_hash(PASSWORD)
                principal.status = "active"
            results.append((code, province, mode, phone))

        await session.commit()
        for code, province, mode, phone in results:
            print(f"{code}\t{province}\t{mode}\t{phone}")


if __name__ == "__main__":
    asyncio.run(seed())
