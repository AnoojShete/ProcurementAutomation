"""MinIO object storage wrapper.

The `minio` SDK is synchronous, so every call is pushed onto a worker
thread with asyncio.to_thread rather than blocking the event loop —
same tradeoff FastAPI itself makes for sync route handlers.
"""
import io
import logging
from functools import lru_cache

from minio import Minio
from minio.error import S3Error

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def get_minio_client() -> Minio:
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return client


def _ensure_bucket_sync(client: Minio, bucket: str):
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


async def ensure_bucket():
    import asyncio
    client = get_minio_client()
    await asyncio.to_thread(_ensure_bucket_sync, client, settings.minio_bucket)


def _put_object_sync(client: Minio, bucket: str, object_name: str, data: bytes, content_type: str):
    _ensure_bucket_sync(client, bucket)
    client.put_object(
        bucket, object_name, io.BytesIO(data), length=len(data), content_type=content_type,
    )


async def upload_bytes(object_name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Uploads `data` to the configured bucket under `object_name`.
    Returns the minio_path published in document.ingested (bucket/key)."""
    import asyncio
    client = get_minio_client()
    await asyncio.to_thread(_put_object_sync, client, settings.minio_bucket, object_name, data, content_type)
    return f"{settings.minio_bucket}/{object_name}"


def _get_object_sync(client: Minio, bucket: str, object_name: str) -> bytes:
    response = client.get_object(bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


async def download_bytes(minio_path: str) -> bytes:
    """`minio_path` is the `bucket/key` string stored on the document row /
    published in document.ingested."""
    import asyncio
    bucket, _, object_name = minio_path.partition("/")
    client = get_minio_client()
    return await asyncio.to_thread(_get_object_sync, client, bucket, object_name)
