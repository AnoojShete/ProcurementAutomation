"""POST /documents/upload orchestration: store -> record -> publish.

Uploads are stored directly in MinIO without malware scanning.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.services import storage
from app.services.ocr import classify_file_type


async def store_and_record_upload(
    db: AsyncSession, kafka_producer, data: bytes, filename: str, content_type: str, uploaded_by: str,
) -> Document:
    """Store the uploaded file in MinIO, create a DB record, and publish a Kafka event."""
    document_id = str(uuid.uuid4())
    file_type = classify_file_type(filename, content_type)
    object_name = f"{document_id}/{filename}"
    minio_path = await storage.upload_bytes(object_name, data, content_type or "application/octet-stream")

    uploaded_at = datetime.now(timezone.utc)
    doc = Document(
        id=document_id,
        status="pending",
        file_type=file_type,
        minio_path=minio_path,
        original_filename=filename,
        uploaded_by=uploaded_by,
        uploaded_at=uploaded_at,
        needs_review=False,
        created_at=uploaded_at,
        updated_at=uploaded_at,
    )
    db.add(doc)
    await db.commit()

    await kafka_producer.publish_document_ingested(
        document_id=document_id, uploaded_by=uploaded_by, file_type=file_type,
        minio_path=minio_path, uploaded_at=uploaded_at,
    )
    return doc
