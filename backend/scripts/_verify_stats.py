"""A12 基础成绩统计 冒烟验收
用法: .venv\\Scripts\\python.exe scripts\\_verify_stats.py
"""
import sys, io, os, logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
settings.app_debug = False
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from fastapi.testclient import TestClient
from app.main import app

H = {"X-School-Code": "demo"}


def ok(r, expect=None):
    if expect is None:
        assert 200 <= r.status_code < 300, f"status={r.status_code} body={r.text}"
    else:
        assert r.status_code == expect, f"status={r.status_code} body={r.text}"
    body = r.json()
    assert body["code"] == 0, body
    return body["data"]


def main():
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/register", headers=H, json={
            "name": "A12测试", "phone": "13800001094", "password": "123456", "role": "director"})
        assert r.status_code in (200, 201, 409), r.text
        login = ok(c.post("/api/v1/auth/login", headers=H, json={
            "phone": "13800001094", "password": "123456"}))
        A = {**H, "Authorization": f"Bearer {login['access_token']}"}

        g = ok(c.post("/api/v1/org/grades", headers=A, json={"name": "高三", "level": 3}))
        cl = ok(c.post("/api/v1/org/classes", headers=A, json={"grade_id": g["id"], "name": "高三(1)班"}))
        # 3 名学生
        stus = [ok(c.post("/api/v1/org/students", headers=A, json={
            "class_id": cl["id"], "name": f"张三{i}", "gender": "male", "student_no": f"S{i}"}))
                for i in range(3)]
        ex = ok(c.post("/api/v1/exams", headers=A, json={
            "name": "一模", "exam_type": "mock", "academic_year": "2026"}))
        p = ok(c.post(f"/api/v1/exams/{ex['id']}/papers", headers=A, json={
            "subject_id": 1, "grade_id": g["id"], "title": "一模数学", "total_score": "100"}))
        q1 = ok(c.post(f"/api/v1/papers/{p['id']}/questions", headers=A, json={"score": "40", "content": "填空"}))
        q2 = ok(c.post(f"/api/v1/papers/{p['id']}/questions", headers=A, json={"score": "60", "content": "解答"}))
        ok(c.patch(f"/api/v1/papers/{p['id']}/finalize", headers=A))
        b = ok(c.post("/api/v1/scans/batches", headers=A, json={"paper_id": p["id"]}))
        ok(c.post(f"/api/v1/scans/batches/{b['id']}/assign", headers=A, json={"class_id": cl["id"]}))
        qlist = ok(c.get(f"/api/v1/grading/papers/{p['id']}/submissions", headers=A))
        assert len(qlist) == 3, qlist
        # 打分：张三0 90(30+60)、张三1 70(30+40)、张三2 50(20+30)
        for i, (sq1, sq2) in enumerate([(30, 60), (30, 40), (20, 30)]):
            sid = qlist[i]["id"]
            ok(c.put(f"/api/v1/grading/submissions/{sid}/questions/{q1['id']}", headers=A, json={"score": str(sq1)}))
            ok(c.put(f"/api/v1/grading/submissions/{sid}/questions/{q2['id']}", headers=A, json={"score": str(sq2)}))
            ok(c.post(f"/api/v1/grading/submissions/{sid}/finalize", headers=A))

        # 按卷汇总：mean=70 max=90 min=50 count=3
        s = ok(c.get(f"/api/v1/stats/papers/{p['id']}/summary", headers=A))
        assert s["count"] == 3 and s["mean"] == 70.0 and s["max"] == 90.0 and s["min"] == 50.0, s
        assert sum(x['count'] for x in s['distribution']) == 3, s
        # 按班级
        cl_agg = ok(c.get(f"/api/v1/stats/papers/{p['id']}/classes", headers=A))
        assert cl_agg and cl_agg[0]["mean"] == 70.0 and cl_agg[0]["count"] == 3, cl_agg
        # 按题：q1 平均 26.66..., 得分率 ~0.667；q2 平均 43.33
        qs = ok(c.get(f"/api/v1/stats/papers/{p['id']}/questions", headers=A))
        by_no = {x["question_no"]: x for x in qs}
        assert by_no[1]["submitted"] == 3 and abs(by_no[1]["mean"] - 80 / 3) < 0.01, qs
        # 按学生历次
        sp = ok(c.get(f"/api/v1/stats/students/{stus[0]['id']}/papers", headers=A))
        assert len(sp) == 1 and sp[0]["total_score"] == 90.0, sp

        print("A12 基础成绩统计 冒烟通过 ✅")


if __name__ == "__main__":
    main()