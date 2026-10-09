from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO

from minio import Minio

from app.core.settings import settings


def get_minio_client() -> Minio:
    return Minio(
        endpoint=settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ROOT_USER,
        secret_key=settings.MINIO_ROOT_PASSWORD,
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


def stream_object(*, bucket_name: str, object_key: str, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    """
    The stored file's bytes, in chunks. MinIO stays private: files are only
    served through the API, which checks the user's access first. The object
    is opened here (so a missing file fails before any response is sent);
    the connection is released once the chunks are read.
    """
    client = get_minio_client()
    response = client.get_object(bucket_name=bucket_name, object_name=object_key)

    def chunks() -> Iterator[bytes]:
        try:
            yield from response.stream(chunk_size)
        finally:
            response.close()
            response.release_conn()

    return chunks()
