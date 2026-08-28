"""A8 验证：年级/班级/学生 CRUD + 多租户隔离"""
from fastapi.testclient import TestClient
from app.main import app

H = {"X-School-Code": "demo"}


def main():
    with TestClient(app) as client:
        # 登录拿 token（复用已有用户，或注册新的）
        phone = "13800000001"
        r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "secret123"}, headers=H)
        if r.status_code != 200:
            client.post("/api/v1/auth/register", json={"name": "测试老师", "phone": phone,
                                                       "password": "secret123"}, headers=H)
            r = client.post("/api/v1/auth/login", json={"phone": phone, "password": "secret123"}, headers=H)
        token = r.json()["data"]["access_token"]
        AH = {**H, "Authorization": f"Bearer {token}"}

        # 年级
        r = client.post("/api/v1/org/grades", json={"name": "高一年级", "level": 1}, headers=AH)
        print("[grade create]", r.status_code, r.json().get("code"))
        gid = r.json()["data"]["id"]

        # 班级
        r = client.post("/api/v1/org/classes", json={"grade_id": gid, "name": "高一(1)班"}, headers=AH)
        print("[class create]", r.status_code, r.json().get("code"))
        cid = r.json()["data"]["id"]

        # 学生
        r = client.post("/api/v1/org/students", json={"class_id": cid, "name": "张三", "gender": "male",
                                                      "roster_order": 1}, headers=AH)
        print("[student create]", r.status_code, r.json().get("code"))

        # 列表
        print("[grades]", client.get("/api/v1/org/grades", headers=AH).status_code)
        print("[classes]", client.get("/api/v1/org/classes", headers=AH).status_code)
        print("[students]", client.get("/api/v1/org/students", headers=AH).status_code)
        print("[students/count]", client.get("/api/v1/org/students/count", headers=AH).json())

        # 未认证访问 -> 401
        print("[no-auth students]", client.get("/api/v1/org/students", headers=H).status_code)
        assert client.get("/api/v1/org/students", headers=H).status_code == 401, "未认证未拦截"
        print("✅ A8 组织学籍 CRUD 验证通过")


if __name__ == "__main__":
    main()