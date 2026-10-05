"""学生端账号、批量账号开通和学生选科入口。"""
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_current_student, get_current_tenant, require_management_user
from app.api.v1.gaokao import _selected_subject_ids
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.session import AsyncSessionLocal, get_session
from app.models.gaokao import GaokaoScheme, StudentCredential, StudentSubjectChoice
from app.models.org import Grade, Student, Subject, Tenant, TenantConfig
from app.services.org.cohort import current_academic_year

router = APIRouter(prefix="/student-auth", tags=["学生端"])


async def _public_session():
    async with AsyncSessionLocal() as session:
        yield session
        await session.commit()


async def _ensure_default_scheme(session: AsyncSession, tenant_id: int) -> GaokaoScheme | None:
    """将学校设置中的默认高考模式转换为学生端可使用的方案记录。"""
    scheme = (await session.execute(select(GaokaoScheme).where(
        GaokaoScheme.tenant_id == tenant_id,
        GaokaoScheme.is_active == True,  # noqa: E712
    ).order_by(GaokaoScheme.entry_year.desc()))).scalars().first()
    if scheme is not None:
        return scheme

    tenant = await session.get(Tenant, tenant_id)
    if tenant is None or tenant.gaokao_mode != "3+1+2":
        return None
    academic_year = await current_academic_year(session, tenant_id)
    try:
        entry_year = int(academic_year[:4])
    except (TypeError, ValueError):
        entry_year = 2026
    subjects = list((await session.execute(select(Subject).where(
        (Subject.tenant_id.is_(None)) | (Subject.tenant_id == tenant_id),
        Subject.course_type == "subject",
    ).order_by(Subject.tenant_id.is_(None), Subject.id))).scalars().all())
    by_name: dict[str, int] = {}
    for subject in subjects:
        by_name.setdefault(subject.name, subject.id)
    required = [by_name.get("语文"), by_name.get("数学"), by_name.get("英语") or by_name.get("外语")]
    primary = [by_name.get("物理"), by_name.get("历史")]
    secondary = [by_name.get("化学"), by_name.get("生物"), by_name.get("政治"), by_name.get("地理")]
    if any(item is None for item in (*required, *primary, *secondary)):
        return None
    scheme = GaokaoScheme(
        tenant_id=tenant_id,
        name=f"{entry_year}届 3+1+2 选科方案",
        province=tenant.province,
        mode="3+1+2",
        entry_year=entry_year,
        required_subject_ids=[int(item) for item in required],
        primary_subject_ids=[int(item) for item in primary],
        secondary_subject_ids=[int(item) for item in secondary],
        strategy_config={},
        is_active=True,
    )
    session.add(scheme)
    await session.flush()
    return scheme


class StudentLoginIn(BaseModel):
    login_name: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1)


@router.get("/schools", summary="学生端可登录学校列表")
async def public_schools(session: AsyncSession = Depends(_public_session)):
    """给学生登录页提供可选学校，避免学生记忆学校代码。"""
    rows = (await session.execute(select(Tenant).order_by(Tenant.name, Tenant.id))).scalars().all()
    return {"code": 0, "message": "ok", "data": [
        {"code": school.code, "name": school.name, "province": school.province}
        for school in rows
    ]}


class ProvisionStudentAccountsIn(BaseModel):
    grade_id: int
    initial_password: str = Field(min_length=6, max_length=64)


class StudentChoiceIn(BaseModel):
    scheme_id: int
    academic_year: str = Field(min_length=4, max_length=20)
    effective_term: str = Field(default="1", pattern=r"^(1|2)$")
    primary_subject_id: int | None = None
    secondary_subject_ids: list[int] = Field(default_factory=list, max_length=3)
    selected_subject_ids: list[int] = Field(default_factory=list, max_length=7)
    stream: str | None = Field(default=None, max_length=20)
    status: str = Field(default="confirmed", pattern=r"^(draft|confirmed)$")


@router.post("/login", summary="学生登录")
async def login(
    body: StudentLoginIn,
    school_code: str | None = Header(default=None, alias="X-School-Code"),
    session: AsyncSession = Depends(_public_session),
):
    if not school_code:
        raise HTTPException(status_code=400, detail="学生登录需要学校代码")
    tenant = (await session.execute(select(Tenant).where(Tenant.code == school_code))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=401, detail="学校代码不存在")
    credential = (await session.execute(select(StudentCredential).where(
        StudentCredential.tenant_id == tenant.id,
        StudentCredential.login_name == body.login_name,
        StudentCredential.status == "active",
    ))).scalar_one_or_none()
    student = await session.get(Student, credential.student_id) if credential else None
    if credential is None or student is None or not verify_password(body.password, credential.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="学生账号或密码错误")
    credential.last_login_at = datetime.utcnow()
    return {"code": 0, "message": "ok", "data": {
        "access_token": create_access_token(student.id, {"tid": tenant.id, "sid": student.id, "scope": "student"}),
        "token_type": "bearer",
        "student": {"id": student.id, "name": student.name, "student_no": student.student_no,
                     "grade_id": student.grade_id, "class_id": student.class_id},
        "school": {"code": tenant.code, "name": tenant.name, "province": tenant.province},
    }}


@router.post("/accounts/provision", summary="批量开通学生账号")
async def provision_accounts(
    body: ProvisionStudentAccountsIn,
    session: AsyncSession = Depends(get_session),
    tenant_id: int = Depends(get_current_tenant),
    _manager=Depends(require_management_user),
):
    grade = await session.get(Grade, body.grade_id)
    if grade is None or grade.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="年级不存在")
    students = list((await session.execute(select(Student).where(
        Student.tenant_id == tenant_id, Student.grade_id == body.grade_id,
    ).order_by(Student.id))).scalars().all())
    student_ids = [item.id for item in students]
    existing = {item.student_id: item for item in (await session.execute(select(StudentCredential).where(
        StudentCredential.tenant_id == tenant_id,
        StudentCredential.student_id.in_(student_ids) if student_ids else False,
    ))).scalars().all()}
    # 同一批次使用同一个初始密码；只生成一次 bcrypt 哈希，避免 474 名学生逐个重复计算导致请求超时。
    password_hash = get_password_hash(body.initial_password)
    created = 0
    reset = 0
    for student in students:
        if not student.student_no:
            continue
        credential = existing.get(student.id)
        if credential is None:
            session.add(StudentCredential(
                tenant_id=tenant_id, student_id=student.id,
                login_name=student.student_no, password_hash=password_hash,
            ))
            created += 1
        else:
            credential.status = "active"
            credential.password_hash = password_hash
            reset += 1
    await session.commit()
    return {"code": 0, "message": "ok", "data": {
        "created": created, "reset": reset,
        "skipped": len(students) - created - reset,
        "total": len(students),
        "login_prefix": "学号",
    }}


@router.get("/me", summary="当前学生信息")
async def me(student: Student = Depends(get_current_student)):
    return {"code": 0, "message": "ok", "data": {
        "id": student.id, "name": student.name, "student_no": student.student_no,
        "grade_id": student.grade_id, "class_id": student.class_id,
    }}


@router.get("/context", summary="查询学生端当前学年")
async def context(
    student: Student = Depends(get_current_student),
    session: AsyncSession = Depends(get_session),
):
    config = (await session.execute(select(TenantConfig).where(
        TenantConfig.tenant_id == student.tenant_id,
        TenantConfig.config_key == "academic_years",
    ))).scalars().first()
    config_value = config.config_value if config and isinstance(config.config_value, dict) else {}
    return {"code": 0, "message": "ok", "data": {
        "academic_year": await current_academic_year(session, student.tenant_id),
        "term": str(config_value.get("current_term", "1")),
        "student": {"id": student.id, "name": student.name, "student_no": student.student_no,
                    "grade_id": student.grade_id, "class_id": student.class_id},
    }}


@router.get("/choice", summary="查询当前学生选科")
async def get_choice(
    academic_year: str,
    term: str = "1",
    student: Student = Depends(get_current_student),
    session: AsyncSession = Depends(get_session),
):
    item = (await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == student.tenant_id,
        StudentSubjectChoice.student_id == student.id,
        StudentSubjectChoice.academic_year == academic_year,
        StudentSubjectChoice.effective_term == term,
    ))).scalar_one_or_none()
    return {"code": 0, "message": "ok", "data": item.model_dump() if item else None}


@router.get("/choice/options", summary="查询学生选科选项")
async def choice_options(
    academic_year: str,
    term: str = "1",
    student: Student = Depends(get_current_student),
    session: AsyncSession = Depends(get_session),
):
    scheme = await _ensure_default_scheme(session, student.tenant_id)
    subjects = list((await session.execute(select(Subject).where(
        (Subject.tenant_id.is_(None)) | (Subject.tenant_id == student.tenant_id),
    ).order_by(Subject.id))).scalars().all())
    choice = (await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == student.tenant_id,
        StudentSubjectChoice.student_id == student.id,
        StudentSubjectChoice.academic_year == academic_year,
        StudentSubjectChoice.effective_term == term,
    ))).scalar_one_or_none()
    return {"code": 0, "message": "ok", "data": {
        "scheme": scheme.model_dump() if scheme else None,
        "subjects": [{"id": item.id, "name": item.name} for item in subjects],
        "choice": choice.model_dump() if choice else None,
    }}


@router.put("/choice", summary="提交当前学生选科")
async def save_choice(
    body: StudentChoiceIn,
    student: Student = Depends(get_current_student),
    session: AsyncSession = Depends(get_session),
):
    scheme = await session.get(GaokaoScheme, body.scheme_id)
    if scheme is None or scheme.tenant_id != student.tenant_id:
        raise HTTPException(status_code=404, detail="高考方案不存在")
    try:
        selected = _selected_subject_ids(body, scheme)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    item = (await session.execute(select(StudentSubjectChoice).where(
        StudentSubjectChoice.tenant_id == student.tenant_id,
        StudentSubjectChoice.student_id == student.id,
        StudentSubjectChoice.academic_year == body.academic_year,
        StudentSubjectChoice.effective_term == body.effective_term,
    ))).scalar_one_or_none()
    if item and item.status == "locked":
        raise HTTPException(status_code=409, detail="选科已锁定，不能修改")
    values = body.model_dump()
    values["selected_subject_ids"] = list(selected)
    if item is None:
        item = StudentSubjectChoice(tenant_id=student.tenant_id, student_id=student.id, **values)
        session.add(item)
    else:
        for key, value in values.items():
            setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return {"code": 0, "message": "选科已保存" if body.status == "draft" else "选科已提交", "data": item.model_dump()}
