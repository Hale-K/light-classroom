from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import admin as admin_api
from app.api.v1 import auth as auth_api
from app.db.session import get_session
from app.models.admin import PlatformAdmin
from app.models.org import Tenant, User


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, account, tenant=None, admin_account=None):
        self.account = account
        self.tenant = tenant
        self.admin_account = admin_account

    async def execute(self, _statement):
        return _Result(self.account)

    async def get(self, model, _id):
        if model is Tenant:
            return self.tenant
        if model is PlatformAdmin:
            return self.admin_account or self.account
        if model is User:
            return self.account
        return None

    async def flush(self):
        pass


@pytest.mark.asyncio
async def test_school_and_admin_login_use_bearer_without_cookie(monkeypatch):
    user = SimpleNamespace(
        id=11, tenant_id=7, name="教师", phone="15000000000",
        role=SimpleNamespace(value="teacher"), status="active", frozen=False,
        password_hash="hashed", last_login_at=None,
    )
    tenant = SimpleNamespace(code="school", name="学校", province="江西", gaokao_mode="3+1+2")
    admin = SimpleNamespace(
        id=11, username="admin", name="管理员", status="active",
        password_hash="hashed", last_login_at=None,
    )
    user_session = _Session(user, tenant, admin)
    admin_session = _Session(admin)
    monkeypatch.setattr(auth_api, "verify_password", lambda *_: True)
    monkeypatch.setattr(admin_api, "verify_password", lambda *_: True)

    async def role_codes(*_):
        return ["teacher"]

    monkeypatch.setattr(auth_api, "get_staff_role_codes", role_codes)
    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(admin_api.router)
    app.dependency_overrides[auth_api._public_session] = lambda: user_session
    app.dependency_overrides[admin_api.get_admin_session] = lambda: admin_session
    app.dependency_overrides[get_session] = lambda: user_session

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        school_login = await client.post("/auth/login", json={"phone": user.phone, "password": "password"})
        assert school_login.status_code == 200
        assert "set-cookie" not in school_login.headers
        school_token = school_login.json()["data"]["access_token"]
        assert school_login.json()["data"]["token_type"] == "bearer"

        client.cookies.set("lc_access", school_token)
        assert (await client.get("/auth/me")).status_code == 401
        client.cookies.clear()
        school_me = await client.get("/auth/me", headers={"Authorization": f"Bearer {school_token}"})
        assert school_me.status_code == 200
        assert school_me.json()["data"]["id"] == user.id

        admin_login = await client.post("/admin/login", json={"username": admin.username, "password": "password"})
        assert admin_login.status_code == 200
        assert "set-cookie" not in admin_login.headers
        admin_token = admin_login.json()["data"]["access_token"]
        assert admin_login.json()["data"]["token_type"] == "bearer"

        client.cookies.set("lc_admin_access", admin_token)
        assert (await client.get("/admin/me")).status_code == 401
        client.cookies.clear()
        assert (await client.get("/admin/me", headers={"Authorization": f"Bearer {admin_token}"})).status_code == 200
        assert (await client.get("/auth/me", headers={"Authorization": f"Bearer {admin_token}"})).status_code == 403
        assert (await client.get("/admin/me", headers={"Authorization": f"Bearer {school_token}"})).status_code == 403
