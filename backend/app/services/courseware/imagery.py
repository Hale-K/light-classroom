"""课件 AI 配图：图像生成策略层。

策略按「服务商管理」里的配置自动选择（provider_type → 策略类），
新增图像服务商时在 _STRATEGY_REGISTRY 注册一个策略类即可，业务层无感。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ai.model.store import AiProvider
from app.core.secret_store import decrypt_secret
from app.models.courseware import Courseware
from app.services.storage.minio_client import presigned_get_url, put_bytes

IMAGE_TIMEOUT = 120
PROMPT_STYLE_SUFFIX = "教学插画风格，画面干净、色彩明快、构图清晰，适合放进课件投影展示，画面中不要出现文字"


class ImageryError(Exception):
    """图像生成失败（message 面向用户）。"""


@dataclass(frozen=True)
class ImageProviderConfig:
    """从服务商管理解析出的生图配置。"""

    provider_type: str
    base_url: str
    api_key: str
    model: str
    timeout: int = IMAGE_TIMEOUT


class ImageGenerationStrategy(Protocol):
    """图像生成策略：提示词 → 图片 URL 列表。"""

    async def generate(self, prompt: str, size: str) -> list[str]: ...


class JimengArkStrategy:
    """即梦 / 火山方舟（Ark）Seedream 文生图，OpenAI images 兼容协议。"""

    def __init__(self, config: ImageProviderConfig):
        self.base_url = config.base_url.rstrip("/")
        self.api_key = config.api_key
        self.model = config.model
        self.timeout = config.timeout

    async def generate(self, prompt: str, size: str) -> list[str]:
        payload = {"model": self.model, "prompt": prompt, "size": size, "response_format": "url"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/images/generations",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ImageryError(f"即梦服务连接失败：{exc}") from exc
        if resp.status_code >= 300:
            raise ImageryError(f"即梦生图失败（HTTP {resp.status_code}）：{resp.text[:200]}")
        try:
            data = resp.json()["data"]
            urls = [item["url"] for item in data if isinstance(item, dict) and item.get("url")]
        except (KeyError, TypeError, ValueError) as exc:
            raise ImageryError("即梦返回格式无法解析") from exc
        if not urls:
            raise ImageryError("即梦没有返回图片，请调整提示词后重试")
        return urls


_STRATEGY_REGISTRY: dict[str, type] = {
    "JIMENG": JimengArkStrategy,
}


async def resolve_image_provider(session: AsyncSession, tenant_id: int) -> ImageProviderConfig:
    """按租户服务商配置解析生图策略：取第一个可用的图片模型服务商。"""
    rows = (
        await session.execute(
            select(AiProvider)
            .where(
                AiProvider.tenant_id == tenant_id,
                AiProvider.status == 1,
                AiProvider.image_model.is_not(None),
            )
            .order_by(AiProvider.is_default.desc(), AiProvider.sort, AiProvider.id)
        )
    ).scalars().all()
    for row in rows:
        provider_type = (row.provider_type or "").upper()
        if provider_type not in _STRATEGY_REGISTRY:
            continue
        if not (row.base_url or "").strip() or not (row.api_key or "").strip() or not (row.image_model or "").strip():
            continue
        return ImageProviderConfig(
            provider_type=provider_type,
            base_url=row.base_url.strip(),
            api_key=decrypt_secret(row.api_key),
            model=row.image_model.strip(),
            timeout=row.timeout_seconds if row.timeout_seconds and row.timeout_seconds > 0 else IMAGE_TIMEOUT,
        )
    raise ImageryError("还没有可用的图片模型：请在「服务商管理」添加即梦（火山方舟）服务商并填写图片模型")


async def generate_and_store_images(
    session: AsyncSession,
    tenant_id: int,
    user,
    *,
    prompt: str,
    size: str,
) -> list[dict]:
    """生成配图并自动存入课件库（落 MinIO，返回可展示的预签名地址）。"""
    config = await resolve_image_provider(session, tenant_id)
    generator = _STRATEGY_REGISTRY[config.provider_type](config)
    urls = await generator.generate(f"{prompt.strip()}，{PROMPT_STYLE_SUFFIX}", size)

    items: list[dict] = []
    for index, url in enumerate(urls, start=1):
        async with httpx.AsyncClient(timeout=IMAGE_TIMEOUT) as client:
            img_resp = await client.get(url)
        if img_resp.status_code >= 300:
            continue
        raw = img_resp.content
        content_type = img_resp.headers.get("content-type", "image/jpeg").split(";")[0]
        ext = "png" if "png" in content_type else "jpeg"
        object_key = f"courseware/{tenant_id}/ai-images/{uuid.uuid4().hex}.{ext}"
        put_bytes(object_key, raw, content_type)
        title = f"AI 配图 · {prompt.strip()[:60]}"
        item = Courseware(
            tenant_id=tenant_id,
            title=title,
            courseware_type="file",
            file_name=f"ai-image-{index}.{ext}",
            object_key=object_key,
            file_size=len(raw),
            content_type=content_type,
            origin="ai",
            tags=["AI 配图"],
            created_by=getattr(user, "id", None),
            created_by_name=getattr(user, "name", "") or "",
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        dumped = item.model_dump()
        dumped.pop("html_content", None)
        dumped["url"] = presigned_get_url(object_key, expires_seconds=3600)
        items.append(dumped)
    if not items:
        raise ImageryError("图片下载失败，请重试")
    return items
