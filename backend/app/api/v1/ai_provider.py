"""大模型服务商管理。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.model.providers import ProbeError, load_model_ids, test_connection
from app.ai.model.store import AiProvider
from app.core.secret_store import decrypt_secret, encrypt_secret
from app.api.deps import get_current_tenant, get_current_user, require_management_user
from app.db.session import get_session

router = APIRouter(prefix="/ai-providers", tags=["服务商管理"], dependencies=[Depends(require_management_user)])


class ProviderIn(BaseModel):
    name: str
    provider_type: str = "OPENAI"
    base_url: str
    api_key: str | None = None
    chat_model: str | None = None
    vision_model: str | None = None
    image_model: str | None = None
    video_model: str | None = None
    audio_model: str | None = None
    timeout_seconds: int = 120
    is_default: bool = False
    status: int = 1
    sort: int = 0
    remark: str | None = None


class LoadModelsIn(BaseModel):
    provider_type: str | None = None
    base_url: str
    api_key: str | None = None


def _to_out(row: AiProvider) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "provider_type": row.provider_type,
        "base_url": row.base_url,
        "has_api_key": bool(row.api_key),
        "chat_model": row.chat_model,
        "vision_model": row.vision_model,
        "image_model": row.image_model,
        "video_model": row.video_model,
        "audio_model": row.audio_model,
        "timeout_seconds": row.timeout_seconds,
        "is_default": row.is_default,
        "status": row.status,
        "sort": row.sort,
        "remark": row.remark,
        "last_test_status": row.last_test_status,
        "last_test_at": row.last_test_at.isoformat() if row.last_test_at else None,
    }


async def _clear_default(session: AsyncSession, tenant_id: int, keep_id: int | None = None) -> None:
    rows = list(
        (await session.execute(select(AiProvider).where(AiProvider.tenant_id == tenant_id, AiProvider.is_default == True))).scalars().all()  # noqa: E712
    )
    for item in rows:
        if keep_id is not None and item.id == keep_id:
            continue
        item.is_default = False
        session.add(item)


@router.get("", summary="服务商列表")
async def list_providers(
    keyword: str | None = Query(default=None),
    status: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    stmt = select(AiProvider).where(AiProvider.tenant_id == tenant_id)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(AiProvider.name.ilike(like), AiProvider.base_url.ilike(like)))
    if status is not None:
        stmt = stmt.where(AiProvider.status == status)
    stmt = stmt.order_by(AiProvider.is_default.desc(), AiProvider.sort, AiProvider.id)
    rows = list((await session.execute(stmt)).scalars().all())
    return {"code": 0, "message": "ok", "data": [_to_out(r) for r in rows]}


@router.post("/load-models", summary="按表单探测可用模型")
async def load_models(body: LoadModelsIn, user=Depends(get_current_user)):
    try:
        ids = await load_model_ids(body.provider_type, body.base_url, body.api_key)
    except ProbeError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return {"code": 0, "message": "ok", "data": ids}


@router.post("", summary="新增服务商")
async def create_provider(
    body: ProviderIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    row = AiProvider(
        tenant_id=tenant_id,
        name=body.name.strip(),
        provider_type=body.provider_type.upper(),
        base_url=body.base_url.strip(),
        api_key=encrypt_secret(body.api_key),
        chat_model=body.chat_model,
        vision_model=body.vision_model,
        image_model=body.image_model,
        video_model=body.video_model,
        audio_model=body.audio_model,
        timeout_seconds=body.timeout_seconds,
        is_default=body.is_default,
        status=1 if body.status else 0,
        sort=body.sort,
        remark=body.remark,
    )
    if row.is_default:
        await _clear_default(session, tenant_id)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"code": 0, "message": "ok", "data": _to_out(row)}


@router.put("/{provider_id}", summary="更新服务商")
async def update_provider(
    provider_id: int,
    body: ProviderIn,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    row = await session.get(AiProvider, provider_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="服务商不存在")
    row.name = body.name.strip()
    row.provider_type = body.provider_type.upper()
    row.base_url = body.base_url.strip()
    if body.api_key is not None and body.api_key.strip():
        row.api_key = encrypt_secret(body.api_key)
    row.chat_model = body.chat_model
    row.vision_model = body.vision_model
    row.image_model = body.image_model
    row.video_model = body.video_model
    row.audio_model = body.audio_model
    row.timeout_seconds = body.timeout_seconds
    row.status = 1 if body.status else 0
    row.sort = body.sort
    row.remark = body.remark
    if body.is_default:
        await _clear_default(session, tenant_id, keep_id=row.id)
        row.is_default = True
    else:
        row.is_default = False
    session.add(row)
    await session.commit()
    return {"code": 0, "message": "ok", "data": True}


@router.put("/{provider_id}/status", summary="启用/停用")
async def update_status(
    provider_id: int,
    status: int = Query(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    row = await session.get(AiProvider, provider_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="服务商不存在")
    row.status = 1 if status else 0
    session.add(row)
    await session.commit()
    return {"code": 0, "message": "ok", "data": True}


@router.put("/{provider_id}/default", summary="设为默认")
async def set_default(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    row = await session.get(AiProvider, provider_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="服务商不存在")
    await _clear_default(session, tenant_id)
    row.is_default = True
    row.status = 1
    session.add(row)
    await session.commit()
    return {"code": 0, "message": "ok", "data": True}


@router.delete("/{provider_id}", summary="删除服务商")
async def delete_provider(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    row = await session.get(AiProvider, provider_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="服务商不存在")
    await session.delete(row)
    await session.commit()
    return {"code": 0, "message": "ok", "data": True}


@router.post("/{provider_id}/test", summary="测试连通")
async def test_provider(
    provider_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant),
):
    row = await session.get(AiProvider, provider_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="服务商不存在")
    try:
        ok = await test_connection(row.provider_type, row.base_url, decrypt_secret(row.api_key))
    except Exception:
        ok = False
    row.last_test_status = 1 if ok else 0
    row.last_test_at = datetime.utcnow()
    session.add(row)
    await session.commit()
    return {"code": 0, "message": "ok", "data": ok}
