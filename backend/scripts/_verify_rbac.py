"""A6 验证：RBAC 权限点校验 require_permission"""
from fastapi.testclient import TestClient
from app.main import app

H = {"X-School-Code": "demo"}
PHONE = "13900000002"


def main():
    with TestClient(app) as client:
        # 1. 注册两个用户：teacher（默认无权限点）、director
        client.post("/api/v1/auth/register", json={"name": "普通老师", "phone": PHONE,
                                                   "password": "secret123"}, headers=H)
        client.post("/api/v1/auth/register", json={"name": "主任", "phone": "13900000003",
                                                   "password": "secret123", "role": "director"}, headers=H)

        # 2. 直接写 RBAC：给 director 绑定 role + permission(paper:create)（同步 psycopg2，避免跨 loop）
        import os, psycopg2
        from urllib.parse import urlparse
        u = urlparse(os.environ["DATABASE_URL"])
        conn = psycopg2.connect(host=u.hostname, port=u.port, user=u.username,
                                password=u.password, dbname=u.path.lstrip("/"))
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM \"user\" WHERE phone='13900000003'")
            uid = cur.fetchone()[0]
            cur.execute("SELECT id FROM role WHERE code='director'")
            row = cur.fetchone()
            rid = row[0] if row else None
            if rid is None:
                cur.execute("INSERT INTO role(code,name) VALUES('director','教导主任') RETURNING id")
                rid = cur.fetchone()[0]
            cur.execute("SELECT id FROM permission WHERE code='paper:create'")
            row = cur.fetchone()
            pid = row[0] if row else None
            if pid is None:
                cur.execute("INSERT INTO permission(code,name,module) VALUES('paper:create','建卷','exam') RETURNING id")
                pid = cur.fetchone()[0]
            cur.execute("DELETE FROM userrole WHERE user_id=%s AND role_id=%s", (uid, rid))
            cur.execute("INSERT INTO userrole(user_id,role_id) VALUES(%s,%s)", (uid, rid))
            cur.execute("DELETE FROM rolepermission WHERE role_id=%s AND permission_id=%s", (rid, pid))
            cur.execute("INSERT INTO rolepermission(role_id,permission_id) VALUES(%s,%s)", (rid, pid))
        conn.close()

        # 3. 普通老师（无 paper:create）登录
        tok_t = client.post("/api/v1/auth/login", json={"phone": PHONE, "password": "secret123"},
                            headers=H).json()["data"]["access_token"]
        # 主任（有 paper:create）登录
        tok_d = client.post("/api/v1/auth/login", json={"phone": "13900000003", "password": "secret123"},
                            headers=H).json()["data"]["access_token"]

        # 4. 复用主 app（同一 loop）挂一个受保护路由验证 require_permission
        from fastapi import Depends
        from app.api.deps import require_permission
        @app.get("/__need_paper", dependencies=[Depends(require_permission("paper:create"))])
        async def need():
            return {"ok": True}
        r_ok = client.get("/__need_paper", headers={**H, "Authorization": f"Bearer {tok_d}"})
        r_deny = client.get("/__need_paper", headers={**H, "Authorization": f"Bearer {tok_t}"})
        print("[director paper]", r_ok.status_code, r_ok.json())
        print("[teacher  paper]", r_deny.status_code, r_deny.json())
        assert r_ok.status_code == 200, "有权限却被拒"
        assert r_deny.status_code == 403, "无权限未拦截"
        print("✅ A6 RBAC 权限点校验验证通过")


if __name__ == "__main__":
    main()