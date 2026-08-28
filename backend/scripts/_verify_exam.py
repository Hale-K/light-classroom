"""A9 考试+建卷 冒烟验收（同步脚本，复用 TestClient 的事件循环）
用法: .venv\\Scripts\\python.exe scripts\\_verify_exam.py
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # backend 根

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
        # 1) 注册（已存在则跳过）+ 登录 —— 幂等
        r = c.post("/api/v1/auth/register", headers=H, json={
            "name": "A9测试", "phone": "13800001091", "password": "123456", "role": "director"})
        assert r.status_code in (200, 201, 409), r.text
        login = ok(c.post("/api/v1/auth/login", headers=H, json={
            "phone": "13800001091", "password": "123456"}))
        A = {**H, "Authorization": f"Bearer {login['access_token']}"}

        # 2) 建考试
        exam = ok(c.post("/api/v1/exams", headers=A, json={
            "name": "十一月月考", "exam_type": "monthly", "academic_year": "2026"}))
        exam_id = exam["id"]
        # 3) 考试列表
        exams = ok(c.get("/api/v1/exams", headers=A))
        assert any(e["id"] == exam_id for e in exams), "考试不在列表"
        # 4) 建卷
        paper = ok(c.post(f"/api/v1/exams/{exam_id}/papers", headers=A, json={
            "subject_id": 1, "grade_id": 1, "title": "数学月考卷", "total_score": "120"}))
        pid = paper["id"]
        # 5) 加题：自动续号
        q1 = ok(c.post(f"/api/v1/papers/{pid}/questions", headers=A, json={
            "question_no": None, "score": "10", "difficulty": "basic", "question_type": "single",
            "content": "1+1=?"}))
        q2 = ok(c.post(f"/api/v1/papers/{pid}/questions", headers=A, json={
            "score": "15", "difficulty": "mid", "content": "证明题"}))
        assert q1["question_no"] == 1 and q2["question_no"] == 2, "自动续号异常"
        # 6) 试卷详情，校验题分累计
        detail = ok(c.get(f"/api/v1/papers/{pid}", headers=A))
        assert detail["actual_score"] == 25, f"actual_score={detail['actual_score']}"
        # 7) 定稿
        fin = ok(c.patch(f"/api/v1/papers/{pid}/finalize", headers=A))
        assert fin["status"] == "finalized"
        # 8) 定稿后加题应 409
        r = c.post(f"/api/v1/papers/{pid}/questions", headers=A, json={"score": "5", "content": "x"})
        assert r.status_code == 409, f"定稿后加题未拦截 {r.status_code}"
        # 9) 改考试状态
        st = ok(c.patch(f"/api/v1/exams/{exam_id}/status", headers=A, json={"status": "ongoing"}))
        assert st["status"] == "ongoing"

        print("A9 考试+建卷 冒烟通过 ✅")

if __name__ == "__main__":
    main()