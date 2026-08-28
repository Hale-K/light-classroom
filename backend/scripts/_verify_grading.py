"""A11 高效打分 冒烟验收
用法: .venv\\Scripts\\python.exe scripts\\_verify_grading.py
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
            "name": "A11测试", "phone": "13800001093", "password": "123456", "role": "director"})
        assert r.status_code in (200, 201, 409), r.text
        login = ok(c.post("/api/v1/auth/login", headers=H, json={
            "phone": "13800001093", "password": "123456"}))
        A = {**H, "Authorization": f"Bearer {login['access_token']}"}

        # 组织
        g = ok(c.post("/api/v1/org/grades", headers=A, json={"name": "高二年级", "level": 2}))
        cl = ok(c.post("/api/v1/org/classes", headers=A, json={"grade_id": g["id"], "name": "高二(1)班"}))
        stu = ok(c.post("/api/v1/org/students", headers=A, json={
            "class_id": cl["id"], "name": "打分学生", "gender": "female", "student_no": "A11-1"}))
        # 建卷 + 两题 + 定稿
        ex = ok(c.post("/api/v1/exams", headers=A, json={
            "name": "期末考", "exam_type": "final", "academic_year": "2026"}))
        p = ok(c.post(f"/api/v1/exams/{ex['id']}/papers", headers=A, json={
            "subject_id": 1, "grade_id": g["id"], "title": "打分卷", "total_score": "100"}))
        q1 = ok(c.post(f"/api/v1/papers/{p['id']}/questions", headers=A, json={"score": "40", "content": "大题1"}))
        q2 = ok(c.post(f"/api/v1/papers/{p['id']}/questions", headers=A, json={"score": "60", "content": "大题2"}))
        ok(c.patch(f"/api/v1/papers/{p['id']}/finalize", headers=A))
        # 进卷分配 → 生成作答
        b = ok(c.post("/api/v1/scans/batches", headers=A, json={"paper_id": p["id"], "page_count": 1}))
        assigned = ok(c.post(f"/api/v1/scans/batches/{b['id']}/assign", headers=A, json={"class_id": cl["id"]}))
        assert assigned["created"] == 1, assigned
        # 阅卷队列
        q = ok(c.get(f"/api/v1/grading/papers/{p['id']}/submissions", headers=A))
        assert len(q) == 1, q
        sid = q[0]["id"]
        # 详情：两题均未打分
        det = ok(c.get(f"/api/v1/grading/submissions/{sid}", headers=A))
        assert len(det["questions"]) == 2
        assert all(x["given_score"] is None for x in det["questions"])
        # 打分 Q1=32, Q2 满分=60
        ok(c.put(f"/api/v1/grading/submissions/{sid}/questions/{q1['id']}", headers=A, json={"score": "32"}))
        ok(c.put(f"/api/v1/grading/submissions/{sid}/questions/{q2['id']}", headers=A, json={"score": "60", "comment": "步骤完整"}))
        # upsert 覆盖 Q1=35
        ok(c.put(f"/api/v1/grading/submissions/{sid}/questions/{q1['id']}", headers=A, json={"score": "35"}))
        # 汇总提交 → 总分 95
        fin = ok(c.post(f"/api/v1/grading/submissions/{sid}/finalize", headers=A))
        assert fin["status"] == "graded"
        assert fin["total_score"] == 95, f"总分异常 {fin['total_score']}"
        # 队列计分题数
        q2_ = ok(c.get(f"/api/v1/grading/papers/{p['id']}/submissions", headers=A))
        assert q2_[0]["scored_questions"] == 2, q2_

        print("A11 高效打分 冒烟通过 ✅")


if __name__ == "__main__":
    main()