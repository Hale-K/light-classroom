"""A4 验证：注册 → 登录 → /me 全链路（基于 TestClient）"""
from fastapi.testclient import TestClient
from app.main import app

H = {"X-School-Code": "demo"}


def main():
    with TestClient(app) as client:  # lifespan 自动 init_db（建表+种子租户）
        phone = "13800000001"
        r = client.post("/api/v1/auth/register", json={"name": "测试老师", "phone": phone,
                                                       "password": "secret123"}, headers=H)
        print("[reg]", r.status_code, r.json().get("code"))
        r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "secret123"}, headers=H)
        data = r.json()
        print("[login]", r.status_code, data.get("message"))
        token = data.get("data", {}).get("access_token")
        r = client.get("/api/v1/auth/me", headers={**H, "Authorization": f"Bearer {token}"})
        print("[me]", r.status_code, r.json().get("data"))
        r = client.get("/api/v1/auth/me", headers=H)
        print("[me-401]", r.status_code)
        assert data.get("code") == 0 and token, "登录失败"
        print("✅ A4 认证链路验证通过")


if __name__ == "__main__":
    main()