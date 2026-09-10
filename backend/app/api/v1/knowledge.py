"""知识库管理 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
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
