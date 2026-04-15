from __future__ import annotations

from datetime import timedelta
from io import BytesIO

from minio import Minio

from app.core.settings import settings


def get_minio_client() -> Minio:
    return Minio(
        endpoint=settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def ensure_bucket_exists() -> None:
    client = get_minio_client()

    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)


def upload_bytes(
    *,
    content: bytes,
    object_key: str,
    content_type: str | None = None,
) -> dict:
    client = get_minio_client()

    client.put_object(
        bucket_name=settings.MINIO_BUCKET,
        object_name=object_key,
        data=BytesIO(content),
        length=len(content),
        content_type=content_type or "application/octet-stream",
    )

    return {
        "storage_provider": "minio",
        "bucket_name": settings.MINIO_BUCKET,
        "object_key": object_key,
        "size_bytes": len(content),
        "content_type": content_type or "application/octet-stream",
    }


def get_presigned_download_url(
    *,
    bucket_name: str,
    object_key: str,
    expires_seconds: int = 3600,
) -> str:
    client = get_minio_client()

    return client.presigned_get_object(
        bucket_name=bucket_name,
        object_name=object_key,
        expires=timedelta(seconds=expires_seconds),
    )