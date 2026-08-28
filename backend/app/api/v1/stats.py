"""基础成绩统计 API（A12）

只读聚合，按卷/人/题/班/年级维度。
- 按卷：人数、平均/最高/最低、分数段分布
- 按班级：各班人数与均分（对某卷）
- 按题：每题满分、均分、得分率
- 按学生：历次作答成绩表
所有查询由多租户中间件自动注入 tenant_id。
"""
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.deps import get_current_user
from app.models.exam import Paper, Question, Exam
from app.models.scan import Submission, AnswerScore
from app.models.org import Class, Student
from app.models.enums import SubmissionStatus

router = APIRouter(prefix="/stats", tags=["成绩统计"])


def _round2(d: Decimal) -> float:
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


async def _get_graded(session: AsyncSession, paper_id: int) -> list[Submission]:
    return (await session.execute(
        select(Submission).where(Submission.paper_id == paper_id,
                                 Submission.status == SubmissionStatus.graded)
    )).scalars().all()


# 分数段（可扩展为配置）
_BUCKETS = [(0, 59), (60, 69), (70, 79), (80, 89), (90, 999)]


# ---------- 按卷：总分统计 + 分布 ----------
@router.get("/papers/{paper_id}/summary", summary="按卷成绩汇总")
async def paper_summary(
    paper_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    paper = await session.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="试卷不存在")
    subs = await _get_graded(session, paper_id)
    if not subs:
        return {"code": 0, "message": "ok",
                "data": {"paper_id": paper_id, "count": 0, "mean": 0, "max": 0, "min": 0,
                         "distribution": [{"label": f"{lo}-{hi if hi < 999 else '+'}", "count": 0}
                                          for lo, hi in _BUCKETS]}}
    scores = sorted(s.total_score for s in subs)
    distribution = []
    for lo, hi in _BUCKETS:
        distribution.append({
            "label": f"{lo}-{hi if hi < 999 else '+'}",
            "count": sum(1 for x in scores if lo <= x <= hi),
        })
    return {"code": 0, "message": "ok", "data": {
        "paper_id": paper_id, "count": len(scores),
        "mean": _round2(sum(scores) / len(scores)),
        "max": float(scores[-1]), "min": float(scores[0]),
        "distribution": distribution,
    }}


# ---------- 按班级：人数与均分 ----------
@router.get("/papers/{paper_id}/classes", summary="按班级聚合")
async def paper_by_class(
    paper_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    subs = await _get_graded(session, paper_id)
    # student_id → class
    student_ids = [s.student_id for s in subs]
    rows = []
    if student_ids:
        students = (await session.execute(
            select(Student, Class.name).join(Class, Class.id == Student.class_id)
            .where(Student.id.in_(student_ids))
        )).all()
        stu_cls = {st.id: cls for st, cls in students}
        agg: dict[int, dict] = {}
        for s in subs:
            cls_id = stu_cls.get(s.student_id)
            bucket = agg.setdefault(cls_id, {"class_id": cls_id, "class_name": None,
                                             "scores": [], "count": 0})
            bucket["scores"].append(s.total_score)
        for cls_id, b in agg.items():
            b["count"] = len(b["scores"])
            b["mean"] = _round2(sum(b["scores"]) / b["count"]) if b["count"] else 0
            b.pop("scores")
            rows.append(b)
    rows.sort(key=lambda x: x["class_id"] or 0)
    return {"code": 0, "message": "ok", "data": rows}


# ---------- 按题：均分/得分率 ----------
@router.get("/papers/{paper_id}/questions", summary="按题得分统计")
async def paper_by_question(
    paper_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    # 该卷已打分的作答 + 其每题得分
    subs = await _get_graded(session, paper_id)
    sub_ids = [s.id for s in subs]
    answers = []
    if sub_ids:
        answers = (await session.execute(
            select(AnswerScore).where(AnswerScore.submission_id.in_(sub_ids),
                                      AnswerScore.confirm_status == "confirmed")
        )).scalars().all()
    by_q: dict[int, list[Decimal]] = {}
    for a in answers:
        by_q.setdefault(a.question_id, []).append(a.score)

    questions = (await session.execute(
        select(Question).where(Question.paper_id == paper_id).order_by(Question.question_no)
    )).scalars().all()
    rows = []
    for q in questions:
        sc = by_q.get(q.id, [])
        cnt = len(sc)
        rate = _round2(sum(sc) / (q.score * cnt)) if cnt and q.score else 0
        rows.append({
            "question_id": q.id, "question_no": q.question_no,
            "full_score": float(q.score), "submitted": cnt,
            "mean": _round2(sum(sc) / cnt) if cnt else 0,
            "score_rate": rate,
        })
    return {"code": 0, "message": "ok", "data": rows}


# ---------- 按学生：历次成绩 ----------
@router.get("/students/{student_id}/papers", summary="学生历次成绩")
async def student_papers(
    student_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    subs = (await session.execute(
        select(Submission).where(Submission.student_id == student_id,
                                 Submission.status == SubmissionStatus.graded)
        .order_by(Submission.id.desc())
    )).scalars().all()
    rows = []
    for s in subs:
        paper = await session.get(Paper, s.paper_id)
        exam_name = None
        if paper is not None:
            exam = await session.get(Exam, paper.exam_id)
            exam_name = exam.name if exam else None
        rows.append({
            "submission_id": s.id, "paper_id": s.paper_id,
            "paper_title": paper.title if paper else None,
            "exam_name": exam_name,
            "total_score": float(s.total_score),
            "graded_at": s.graded_at,
        })
    return {"code": 0, "message": "ok", "data": rows}