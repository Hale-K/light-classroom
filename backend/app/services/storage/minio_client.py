"""对象存储封装（文件中心）：MinIO 与本地磁盘双模式。

服务器部署走 MinIO；桌面端/离线环境设置 `STORAGE_LOCAL_DIR` 后所有对象
直接落本地磁盘，导出下载通过带 HMAC 签名的后端流式端点完成，
不需要安装任何第三方服务。两个模式对上层 API 完全一致。
"""
from __future__ import annotations

import hashlib
import hmac
import shutil
from datetime import timedelta
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from loguru import logger

from app.core.config import settings


def local_mode() -> bool:
    """本地磁盘模式：配置了 storage_local_dir 即启用（桌面端一键安装模式）。"""
    return bool(settings.storage_local_dir)


def _local_path(object_key: str) -> Path:
    root = Path(settings.storage_local_dir).resolve()
    target = (root / object_key).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("非法的对象 Key")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _signature(object_key: str, expires: int) -> str:
    secret = settings.jwt_secret_key.encode()
    return hmac.new(secret, f"{object_key}:{expires}".encode(), hashlib.sha256).hexdigest()


def verify_signature(object_key: str, expires: int, signature: str) -> bool:
    import time

    try:
        if int(expires) < int(time.time()):
            return False
    except (TypeError, ValueError):
        return False
    expected = _signature(object_key, int(expires))
    return hmac.compare_digest(expected, signature)


def local_file_path(object_key: str) -> Path:
    """本地模式下对象的磁盘路径（仅 local_mode 使用）。"""
    return _local_path(object_key)


@lru_cache
def _client():
    from minio import Minio

    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=bool(settings.minio_secure),
    )


def ensure_bucket() -> None:
    if local_mode():
        return
    client = _client()
    bucket = settings.minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info(f"MinIO bucket created: {bucket}")


def put_bytes(object_key: str, data: bytes, content_type: str = "application/octet-stream") -> int:
    if local_mode():
        _local_path(object_key).write_bytes(data)
        return len(data)
    ensure_bucket()
    client = _client()
    size = len(data)
    client.put_object(
        settings.minio_bucket,
        object_key,
        BytesIO(data),
        length=size,
        content_type=content_type,
    )
    return size


def put_file(object_key: str, file_path: str, content_type: str = "application/octet-stream") -> int:
    if local_mode():
        target = _local_path(object_key)
        size = Path(file_path).stat().st_size
        shutil.copyfile(file_path, target)
        return size
    ensure_bucket()
    client = _client()
    result = client.fput_object(settings.minio_bucket, object_key, file_path, content_type=content_type)
    return int(getattr(result, "size", 0) or 0)


def get_bytes(object_key: str) -> bytes:
    if local_mode():
        return _local_path(object_key).read_bytes()
    client = _client()
    response = client.get_object(settings.minio_bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def remove_object(object_key: str) -> None:
    if local_mode():
        target = _local_path(object_key)
        if target.exists():
            target.unlink()
        return
    client = _client()
    client.remove_object(settings.minio_bucket, object_key)


def presigned_get_url(object_key: str, expires_seconds: int = 3600) -> str:
    """本地模式返回带 HMAC 签名的后端流式下载地址（相对路径，前端补 origin）。"""
    if local_mode():
        import time

        expires = int(time.time()) + expires_seconds
        return f"/api/v1/file-center/storage/{quote(object_key)}?expires={expires}&signature={_signature(object_key, expires)}"
    client = _client()
    return client.presigned_get_object(
        settings.minio_bucket,
        object_key,
        expires=timedelta(seconds=expires_seconds),
    )
