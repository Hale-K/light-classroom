"""人员职责：在职教师与班主任查询。"""
from __future__ import annotations

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.enums import BaseUserRole, UserStatus
from app.models.org import Class, Subject, TeachingAssignment, User
from app.ai.tools.school.common import _LIST_CAP, _term

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_teachers",
            "description": "只读查询本校当前学年学期的在职教师。可按科目或姓名关键词筛选，返回任教学科和班主任班级；不返回排课结果，也不执行修改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "本校科目名，如“数学”；不筛选时省略"},
                    "keyword": {"type": "string", "description": "教师姓名关键词；不筛选时省略"},
                },
                "additionalProperties": False,
            },
        },
    },
]


async def lookup_teachers(
    session: AsyncSession,
    tenant_id: int,
    *,
    subject: str = "",
    keyword: str = "",
    academic_year=None, term=None,
) -> str:
    current_year, current_term = await _term(session, tenant_id)
    year, term = academic_year or current_year, term or current_term
    stmt = select(User).where(
        User.tenant_id == tenant_id,
        User.role == BaseUserRole.teacher,
        User.status == UserStatus.active,
    )
    keyword = (keyword or "").strip()
    if keyword:
        stmt = stmt.where(User.name.contains(keyword))
    teachers = (await session.execute(stmt)).scalars().all()
    if not teachers:
        return f"{year or '当前学年'}第{term}学期没有匹配「{keyword}」的在职教师。"
    ids = [t.id for t in teachers if t.id is not None]

    subject_rows = (await session.execute(select(Subject.__table__).where(
        (Subject.tenant_id == tenant_id) | (Subject.tenant_id.is_(None)),
    ))).all()
    subject_names = {s.id: s.name for s in subject_rows}

    want = (subject or "").strip()
    subject_ids: set[int] | None = None
    if want:
        subject_ids = {s.id for s in subject_rows if want in s.name or s.name in want}
        if not subject_ids:
            return f"科目库里没有「{want}」。请先在科目管理建好，或换一个本校在用的科目名。"

    where = [
        TeachingAssignment.tenant_id == tenant_id,
        TeachingAssignment.teacher_id.in_(ids),
    ]
    if year:
        where.append(TeachingAssignment.academic_year == year)
    where.append(TeachingAssignment.term == term)
    asg_rows = (await session.execute(select(TeachingAssignment).where(*where))).scalars().all()

    head_rows = (await session.execute(select(Class).where(
        Class.tenant_id == tenant_id,
        Class.head_teacher_id.in_(ids),
    ))).scalars().all()
    head_classes: dict[int, list[str]] = {}
    for c in head_rows:
        if c.head_teacher_id is not None:
            head_classes.setdefault(c.head_teacher_id, []).append(c.name)

    # 班主任一览：完整列出、不受明细行数上限影响——「班主任有哪些」一类问题的答案在这里
    head_ids = sorted({c.head_teacher_id for c in head_rows if c.head_teacher_id is not None})
    head_names: dict[int, str] = {}
    if head_ids:
        head_names = dict((await session.execute(
            select(User.id, User.name).where(User.id.in_(head_ids))
        )).all())
    head_pairs = [
        f"{c.name} {head_names[c.head_teacher_id]}"
        for c in sorted(head_rows, key=lambda c: c.name)
        if c.head_teacher_id is not None and head_names.get(c.head_teacher_id)
    ]

    taught: dict[int, set[str]] = {}
    for a in asg_rows:
        if a.teacher_id is None:
            continue
        if subject_ids is not None and a.subject_id not in subject_ids:
            continue
        name = subject_names.get(a.subject_id)
        if name:
            taught.setdefault(a.teacher_id, set()).add(name)

    lines: list[str] = []
    for t in teachers:
        if t.id is None:
            continue
        if subject_ids is not None and t.id not in taught:
            continue
        bits = ["、".join(sorted(taught.get(t.id) or [])) or "暂无任教"]
        if head := head_classes.get(t.id):
            bits.append("、".join(head[:4]) + "班主任")
        lines.append(f"- {t.name}：{'；'.join(bits)}")
    scope = f"任教「{want}」的" if want else "在职教师"
    total = len(lines)
    more = max(0, total - _LIST_CAP)
    tail = f"（其余 {more} 人略）" if more > 0 else ""
    head_line = f"{year or '当前学年'}第{term}学期，{scope}共 {total} 人{tail}："
    overview = (
        f"班主任一览（{len(head_pairs)} 个班）：{'；'.join(head_pairs)}"
        if head_pairs
        else "班主任一览：还没有班级设置班主任。"
    )
    return head_line + "\n" + overview + "\n" + "\n".join(lines[:_LIST_CAP])
