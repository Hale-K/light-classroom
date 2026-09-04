"""MinIO 对象存储封装（文件中心）。"""
from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from io import BytesIO

from loguru import logger

from app.core.config import settings


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
    client = _client()
    bucket = settings.minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info(f"MinIO bucket created: {bucket}")


def put_bytes(object_key: str, data: bytes, content_type: str = "application/octet-stream") -> int:
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
    ensure_bucket()
    client = _client()
    result = client.fput_object(settings.minio_bucket, object_key, file_path, content_type=content_type)
    return int(getattr(result, "size", 0) or 0)


def get_bytes(object_key: str) -> bytes:
    client = _client()
    response = client.get_object(settings.minio_bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def presigned_get_url(object_key: str, expires_seconds: int = 3600) -> str:
    client = _client()
    return client.presigned_get_object(
        settings.minio_bucket,
        object_key,
        expires=timedelta(seconds=expires_seconds),
    )
