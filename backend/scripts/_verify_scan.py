"""A10 扫描进卷 冒烟验收
用法: .venv\\Scripts\\python.exe scripts\\_verify_scan.py
"""
import sys, io, os, logging
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
settings.app_debug = False  # 关闭引擎 echo 日志
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
            "name": "A10测试", "phone": "13800001092", "password": "123456", "role": "director"})
        assert r.status_code in (200, 201, 409), r.text
        login = ok(c.post("/api/v1/auth/login", headers=H, json={
            "phone": "13800001092", "password": "123456"}))
        A = {**H, "Authorization": f"Bearer {login['access_token']}"}

        # 组织：年级/班/2 学生
        grade = ok(c.post("/api/v1/org/grades", headers=A, json={"name": "高一年级", "level": 1}))
        cls = ok(c.post("/api/v1/org/classes", headers=A, json={"grade_id": grade["id"], "name": "高一(1)班"}))
        for i, no in enumerate(["001", "002"]):
            ok(c.post("/api/v1/org/students", headers=A, json={
                "class_id": cls["id"], "name": f"学生{i+1}", "gender": "male", "student_no": no}))

        # 建考 + 建卷 + 定稿
        exam = ok(c.post("/api/v1/exams", headers=A, json={
            "name": "十二月月考", "exam_type": "monthly", "academic_year": "2026"}))
        paper = ok(c.post(f"/api/v1/exams/{exam['id']}/papers", headers=A, json={
            "subject_id": 1, "grade_id": grade["id"], "title": "数学卷", "total_score": "120"}))
        ok(c.post(f"/api/v1/papers/{paper['id']}/questions", headers=A, json={"score": "10", "content": "q1"}))
        ok(c.patch(f"/api/v1/papers/{paper['id']}/finalize", headers=A))

        # 上传批次（未定稿防护已由定稿满足）
        batch = ok(c.post("/api/v1/scans/batches", headers=A, json={
            "paper_id": paper["id"], "file_name": "scan_001.pdf", "page_count": 2}))
        bid = batch["id"]
        # 切分
        ok(c.patch(f"/api/v1/scans/batches/{bid}/split", headers=A))
        # 加页
        ok(c.post(f"/api/v1/scans/batches/{bid}/pages", headers=A, json={"page_index": 0, "cos_url": "cos://p0"}))
        ok(c.post(f"/api/v1/scans/batches/{bid}/pages", headers=A, json={"page_index": 1, "cos_url": "cos://p1"}))
        pages = ok(c.get(f"/api/v1/scans/batches/{bid}/pages", headers=A))
        assert len(pages) == 2, f"页数异常 {len(pages)}"
        # 分配：全年级学生
        res = ok(c.post(f"/api/v1/scans/batches/{bid}/assign", headers=A, json={"class_id": None}))
        assert res["created"] == 2, f"分配数量异常 {res}"
        # 幂等：再分配应 0 新增
        res2 = ok(c.post(f"/api/v1/scans/batches/{bid}/assign", headers=A, json={"class_id": None}))
        assert res2["created"] == 0, f"重复分配未拦截 {res2}"
        # 确认
        conf = ok(c.patch(f"/api/v1/scans/batches/{bid}/confirm", headers=A))
        assert conf["status"] == "confirmed"
        # 抗未定稿：定稿前建批次应 409
        exam2 = ok(c.post("/api/v1/exams", headers=A, json={
            "name": "未定稿卷", "exam_type": "monthly", "academic_year": "2026"}))
        paper2 = ok(c.post(f"/api/v1/exams/{exam2['id']}/papers", headers=A, json={
            "subject_id": 1, "grade_id": grade["id"], "title": "未定稿卷", "total_score": "100"}))
        rb = c.post("/api/v1/scans/batches", headers=A, json={"paper_id": paper2["id"]})
        assert rb.status_code == 409, f"未定稿建批次未拦截 {rb.status_code}"

        print("A10 扫描进卷 冒烟通过 ✅")


if __name__ == "__main__":
    main()