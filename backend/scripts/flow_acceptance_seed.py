"""Seed the disposable SQLite configuration-flow browser environment."""
from pathlib import Path
import sys

from sqlalchemy import create_engine, select
from sqlmodel import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401, E402
from app.models.enums import BaseUserRole, Gender  # noqa: E402
from app.models.org import Grade, OrganizationUnit, Student, Tenant, TenantConfig, User  # noqa: E402


DB_PATH = Path(__file__).resolve().parents[2] / ".codex" / "flow-acceptance.db"


def main() -> None:
    engine = create_engine(f"sqlite:///{DB_PATH.as_posix()}")
    with Session(engine) as session:
        tenant = session.get(Tenant, 1)
        if tenant is None:
            tenant = Tenant(id=1, code="accept_admin", name="配置流程验收学校", province="吉林")
        else:
            tenant.code = "accept_admin"
            tenant.name = "配置流程验收学校"
        session.add(tenant)
        if session.get(User, 101) is None:
            session.add(User(id=101, tenant_id=1, name="验收主任", phone="19900000001", password_hash="not-used", role=BaseUserRole.director))
        for grade_id, name, level in ((101, "高一", 1), (102, "高二", 2)):
            if session.get(Grade, grade_id) is None:
                session.add(Grade(id=grade_id, tenant_id=1, name=name, level=level))
        for unit_id, name, grade_id in ((101, "2026届高1", 101), (102, "2026届高2", 102)):
            if session.get(OrganizationUnit, unit_id) is None:
                session.add(OrganizationUnit(id=unit_id, tenant_id=1, name=name, unit_type="grade_group", grade_id=grade_id, academic_year="2026-2027", cohort_label="2026"))
        if session.get(Student, 101) is None:
            session.add(Student(id=101, tenant_id=1, name="验收学生", gender=Gender.male, student_no="FLOW-001", grade_id=101))
        config = session.exec(select(TenantConfig).where(TenantConfig.tenant_id == 1, TenantConfig.config_key == "academic_years")).first()
        value = {"current_entry_year": 2026, "current_academic_year": "2026-2027", "current_term": "2"}
        if config is None:
            session.add(TenantConfig(tenant_id=1, config_key="academic_years", config_value=value))
        else:
            config.config_value = value
        session.commit()
    engine.dispose()


if __name__ == "__main__":
    main()
