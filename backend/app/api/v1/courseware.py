"""课件管理路由（薄壳）：编排逻辑在 app.services.courseware 分层里。"""
from __future__ import annotations

import json
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.model.chat import ChatError, resolve_chat_endpoints
from app.api.deps import get_current_tenant, get_current_user
from app.db.session import get_session
from app.models.courseware import Courseware
from app.services.courseware.generation import (
    CoursewareGenerationRequest,
    is_valid_courseware_html,
    stream_courseware_html,
    strip_fences,
)
from app.services.courseware.imagery import ImageryError, generate_and_store_images
from app.services.storage.minio_client import presigned_get_url, put_bytes, remove_object

router = APIRouter(tags=["课件管理"])

MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def _dump(item: Courseware, *, with_content: bool = False) -> dict:
    data = item.model_dump()
    if not with_content:
        data.pop("html_content", None)
    return data


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _get_tenant_item(session: AsyncSession, courseware_id: int, tenant_id: int) -> Courseware:
    item = (
        await session.execute(
            select(Courseware).where(Courseware.id == courseware_id, Courseware.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="课件不存在或已被删除")
    return item


class CoursewareLinkIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    source_url: str = Field(min_length=1, max_length=600)
    stage: str = Field(default="", max_length=10)
    grade_name: str = Field(default="", max_length=20)
    subject_name: str = Field(default="", max_length=20)
    textbook_version: str = Field(default="", max_length=30)
    chapter: str = Field(default="", max_length=160)
    remark: str = Field(default="", max_length=300)


class CoursewareUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    stage: str | None = Field(default=None, max_length=10)
    grade_name: str | None = Field(default=None, max_length=20)
    subject_name: str | None = Field(default=None, max_length=20)
    textbook_version: str | None = Field(default=None, max_length=30)
    chapter: str | None = Field(default=None, max_length=160)
    remark: str | None = Field(default=None, max_length=300)
    source_url: str | None = Field(default=None, max_length=600)


class CoursewareGenerateIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    stage: str = Field(default="", max_length=10)
    grade_name: str = Field(default="", max_length=20)
    subject_name: str = Field(default="", max_length=20)
    textbook_version: str = Field(default="", max_length=30)
    chapter: str = Field(default="", max_length=160)
    requirement: str = Field(default="", max_length=500)


class CoursewareImageIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=600)
    size: str = Field(default="1024x1024", pattern=r"^\d{3,4}x\d{3,4}$")


@router.get("/courseware/catalog")
async def courseware_catalog():
    """小学到高三标准课程目录（学段/年级/学科/教材版本）。"""
    from app.services.courseware_catalog import COURSE_CATALOG

    return {"code": 0, "message": "ok", "data": COURSE_CATALOG}


@router.get("/courseware")
async def list_courseware(
    stage: str | None = None,
    grade: str | None = None,
    subject: str | None = None,
    keyword: str | None = None,
    courseware_type: str | None = None,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    conditions = [Courseware.tenant_id == tenant_id]
    if stage:
        conditions.append(Courseware.stage == stage)
    if grade:
        conditions.append(Courseware.grade_name == grade)
    if subject:
        conditions.append(Courseware.subject_name == subject)
    if courseware_type:
        conditions.append(Courseware.courseware_type == courseware_type)
    if keyword:
        like = f"%{keyword.strip()}%"
        conditions.append(
            Courseware.title.like(like) | Courseware.chapter.like(like) | Courseware.subject_name.like(like)
        )
    rows = (
        await session.execute(
            select(Courseware)
            .where(*conditions)
            .order_by(Courseware.id.desc())
            .limit(300)
        )
    ).scalars().all()
    return {"code": 0, "message": "ok", "data": [_dump(item) for item in rows]}


@router.post("/courseware/upload")
async def upload_courseware(
    file: UploadFile = File(...),
    title: str = Form(""),
    stage: str = Form(""),
    grade_name: str = Form(""),
    subject_name: str = Form(""),
    textbook_version: str = Form(""),
    chapter: str = Form(""),
    remark: str = Form(""),
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="文件内容为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail="单个课件不能超过 200MB")
    original = file.filename or "课件"
    safe_name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", original).strip("_") or "课件"
    stem = safe_name.rsplit(".", 1)[0] if "." in safe_name else safe_name
    courseware_uid = uuid.uuid4().hex
    object_key = f"courseware/{tenant_id}/{courseware_uid}/{safe_name}"
    content_type = file.content_type or "application/octet-stream"
    size = put_bytes(object_key, raw, content_type)
    item = Courseware(
        tenant_id=tenant_id,
        title=(title.strip() or stem)[:120],
        courseware_type="file",
        stage=stage, grade_name=grade_name, subject_name=subject_name,
        textbook_version=textbook_version, chapter=chapter,
        file_name=original, object_key=object_key, file_size=size, content_type=content_type,
        origin="upload", remark=remark,
        created_by=user.id, created_by_name=getattr(user, "name", "") or "",
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"code": 0, "message": "ok", "data": _dump(item)}


@router.post("/courseware")
async def create_courseware_link(
    body: CoursewareLinkIn,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    item = Courseware(
        tenant_id=tenant_id,
        title=body.title,
        courseware_type="link",
        stage=body.stage, grade_name=body.grade_name, subject_name=body.subject_name,
        textbook_version=body.textbook_version, chapter=body.chapter,
        source_url=body.source_url, origin="upload", remark=body.remark,
        created_by=user.id, created_by_name=getattr(user, "name", "") or "",
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"code": 0, "message": "ok", "data": _dump(item)}


@router.get("/courseware/{courseware_id}")
async def courseware_detail(
    courseware_id: int,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_tenant_item(session, courseware_id, tenant_id)
    return {"code": 0, "message": "ok", "data": _dump(item, with_content=True)}


@router.patch("/courseware/{courseware_id}")
async def update_courseware(
    courseware_id: int,
    body: CoursewareUpdateIn,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_tenant_item(session, courseware_id, tenant_id)
    for field_name in ("title", "stage", "grade_name", "subject_name", "textbook_version", "chapter", "remark", "source_url"):
        value = getattr(body, field_name)
        if value is not None:
            setattr(item, field_name, value)
    await session.commit()
    await session.refresh(item)
    return {"code": 0, "message": "ok", "data": _dump(item)}


@router.delete("/courseware/{courseware_id}")
async def delete_courseware(
    courseware_id: int,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_tenant_item(session, courseware_id, tenant_id)
    if item.object_key:
        try:
            remove_object(item.object_key)
        except Exception:  # 存储对象清理失败不阻塞记录删除
            pass
    await session.delete(item)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"id": courseware_id}}


@router.get("/courseware/{courseware_id}/download")
async def download_courseware(
    courseware_id: int,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_tenant_item(session, courseware_id, tenant_id)
    if item.courseware_type != "file" or not item.object_key:
        raise HTTPException(status_code=422, detail="该课件不是上传文件，请直接预览或打开链接")
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "url": presigned_get_url(item.object_key, expires_seconds=3600),
            "file_name": item.file_name or item.title,
            "file_size": item.file_size,
        },
    }


@router.post("/courseware/generate/stream")
async def generate_courseware_stream(
    body: CoursewareGenerateIn,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """SSE 流式生成课件：model（当前服务商）→ progress（字符数）→ done（入库）→ error。

    多服务商按顺序故障转移：未产出任何内容的失败自动切换下一家。
    """
    try:
        endpoints = await resolve_chat_endpoints(session, tenant_id)
    except ChatError as exc:
        raise HTTPException(status_code=400, detail=getattr(exc, "message", None) or str(exc))
    request = CoursewareGenerationRequest(
        title=body.title, stage=body.stage, grade_name=body.grade_name,
        subject_name=body.subject_name, textbook_version=body.textbook_version,
        chapter=body.chapter, requirement=body.requirement,
    )

    async def event_stream():
        chars = 0
        last_sent = 0
        pieces: list[str] = []
        last_error: ChatError | None = None
        completed = False
        yield _sse({"type": "start", "providers": len(endpoints)})
        for endpoint in endpoints:
            yield _sse({"type": "model", "name": endpoint.model})
            produced = 0
            try:
                async for piece in stream_courseware_html(endpoint, request):
                    pieces.append(piece)
                    chars += len(piece)
                    produced += len(piece)
                    if chars - last_sent >= 200:
                        last_sent = chars
                        yield _sse({"type": "progress", "chars": chars})
            except ChatError as exc:
                if produced:  # 已经输出一半，切换会导致内容断裂，直接报错
                    last_error = exc
                    break
                last_error = exc
                continue
            completed = True
            break
        if not completed:
            yield _sse({"type": "error", "message": (getattr(last_error, "message", None) or str(last_error)) if last_error else "没有可用的模型服务商"})
            return
        yield _sse({"type": "progress", "chars": chars})
        html = strip_fences("".join(pieces))
        if not is_valid_courseware_html(html):
            yield _sse({"type": "error", "message": "模型未返回有效的 HTML 课件，请重试或调整教学要求"})
            return
        item = Courseware(
            tenant_id=tenant_id,
            title=body.title,
            courseware_type="html",
            stage=body.stage, grade_name=body.grade_name, subject_name=body.subject_name,
            textbook_version=body.textbook_version, chapter=body.chapter,
            html_content=html, origin="ai",
            created_by=user.id, created_by_name=getattr(user, "name", "") or "",
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        yield _sse({"type": "done", "item": _dump(item, with_content=True)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/courseware/images/generate")
async def generate_courseware_images(
    body: CoursewareImageIn,
    tenant_id: int = Depends(get_current_tenant),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """AI 配图（即梦/方舟策略），图片自动存入课件库。"""
    try:
        items = await generate_and_store_images(session, tenant_id, user, prompt=body.prompt, size=body.size)
    except ImageryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "ok", "data": {"items": items}}
