"""知识库管理 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.ai.knowledge.ingest import chunk_text, content_hash, parse_document
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.api.deps import get_current_tenant, get_current_user, require_management_user
from app.db.session import get_session

router = APIRouter(prefix="/knowledge", tags=["知识库"], dependencies=[Depends(require_management_user)])


class KnowledgeBaseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    embedding_model: str = Field(default="bge-base-zh-v1.5", max_length=100)


def _out(row: KnowledgeBase) -> dict:
    return {"id": row.id, "name": row.name, "description": row.description,
            "embedding_model": row.embedding_model, "enabled": row.enabled,
            "created_at": row.created_at.isoformat() if row.created_at else None}


@router.get("", summary="知识库列表")
async def list_knowledge_bases(
    session: AsyncSession = Depends(get_session), tenant_id: int = Depends(get_current_tenant),
):
    rows = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id).order_by(KnowledgeBase.id.desc()))).scalars().all()
    return {"code": 0, "message": "ok", "data": [_out(row) for row in rows]}


@router.post("", summary="新建知识库", status_code=201)
async def create_knowledge_base(
    body: KnowledgeBaseIn, session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    exists = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.name == body.name))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "知识库名称已存在")
    row = KnowledgeBase(tenant_id=tenant_id, created_by=user.id, **body.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"code": 0, "message": "ok", "data": _out(row)}


@router.patch("/{base_id}/status", summary="启用或停用知识库")
async def set_knowledge_base_status(
    base_id: int, enabled: bool, session: AsyncSession = Depends(get_session),
    tenant_id: int = Depends(get_current_tenant),
):
    row = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == base_id, KnowledgeBase.tenant_id == tenant_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "知识库不存在")
    row.enabled = enabled
    await session.commit()
    return {"code": 0, "message": "ok", "data": _out(row)}


@router.delete("/{base_id}", summary="删除知识库")
async def delete_knowledge_base(
    base_id: int, session: AsyncSession = Depends(get_session),
    tenant_id: int = Depends(get_current_tenant),
):
    row = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == base_id, KnowledgeBase.tenant_id == tenant_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "知识库不存在")
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == base_id, KnowledgeChunk.tenant_id == tenant_id))
    await session.execute(delete(KnowledgeDocument).where(KnowledgeDocument.knowledge_base_id == base_id, KnowledgeDocument.tenant_id == tenant_id))
    await session.delete(row)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"deleted": True}}


@router.get("/{base_id}/documents", summary="知识库文档列表")
async def list_documents(
    base_id: int, session: AsyncSession = Depends(get_session),
    tenant_id: int = Depends(get_current_tenant),
):
    rows = (await session.execute(select(KnowledgeDocument).where(
        KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.knowledge_base_id == base_id,
    ).order_by(KnowledgeDocument.id.desc()))).scalars().all()
    return {"code": 0, "message": "ok", "data": [{
        "id": row.id, "file_name": row.file_name, "status": row.status,
        "file_size": row.file_size, "chunk_count": row.chunk_count,
        "error_message": row.error_message,
    } for row in rows]}


@router.post("/{base_id}/documents", summary="上传知识库文档", status_code=201)
async def upload_document(
    base_id: int, file: UploadFile = File(...), session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user), tenant_id: int = Depends(get_current_tenant),
):
    base = (await session.execute(select(KnowledgeBase).where(
        KnowledgeBase.id == base_id, KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.enabled.is_(True),
    ))).scalar_one_or_none()
    if base is None:
        raise HTTPException(404, "知识库不存在或已停用")
    data = await file.read()
    if not data or len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "文件不能为空且不能超过 20 MB")
    digest = content_hash(data)
    duplicate = (await session.execute(select(KnowledgeDocument).where(
        KnowledgeDocument.knowledge_base_id == base_id, KnowledgeDocument.tenant_id == tenant_id,
        KnowledgeDocument.content_hash == digest,
    ))).scalar_one_or_none()
    if duplicate:
        raise HTTPException(409, "相同文件已存在")
    try:
        parsed = parse_document(file.filename or "document.txt", data, file.content_type)
        chunks = chunk_text(parsed.text)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not chunks:
        raise HTTPException(400, "文档没有可用文本")
    doc = KnowledgeDocument(
        tenant_id=tenant_id, knowledge_base_id=base_id, file_name=file.filename or "document",
        content_type=parsed.content_type, content_hash=digest, file_size=len(data),
        status="parsed", chunk_count=len(chunks), created_by=user.id,
    )
    session.add(doc)
    await session.flush()
    for index, (content, locator) in enumerate(chunks):
        session.add(KnowledgeChunk(
            tenant_id=tenant_id, knowledge_base_id=base_id, document_id=doc.id,
            chunk_index=index, content=content, source_locator=locator,
        ))
    await session.commit()
    await session.refresh(doc)
    return {"code": 0, "message": "ok", "data": {"id": doc.id, "status": doc.status, "chunk_count": doc.chunk_count}}


@router.delete("/{base_id}/documents/{document_id}", summary="删除知识库文档")
async def delete_document(
    base_id: int, document_id: int, session: AsyncSession = Depends(get_session),
    tenant_id: int = Depends(get_current_tenant),
):
    row = (await session.execute(select(KnowledgeDocument).where(
        KnowledgeDocument.id == document_id, KnowledgeDocument.knowledge_base_id == base_id,
        KnowledgeDocument.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "文档不存在")
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id, KnowledgeChunk.tenant_id == tenant_id))
    await session.delete(row)
    await session.commit()
    return {"code": 0, "message": "ok", "data": {"deleted": True}}
