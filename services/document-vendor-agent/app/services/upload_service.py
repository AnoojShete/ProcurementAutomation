"""POST /documents/upload orchestration: scan -> store -> record -> publish.

Governance control B (malware scanning): every uploaded file is streamed
through ClamAV BEFORE it's written to MinIO. A flagged file is rejected
and never stored; an unreachable ClamAV fails the upload closed (503)
rather than skipping the scan.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.services import storage
from app.services.audit import write_audit_log
from app.services.clamav_client import scan_bytes, sha256_hex, ClamAVUnavailableError
from app.services.ocr import classify_file_type


class MalwareDetectedError(Exception):
    def __init__(self, signature: str):
        self.signature = signature
        super().__init__(f"malware detected: {signature}")


class ScanUnavailableError(Exception):
    pass


async def scan_upload(data: bytes, db: AsyncSession, filename: str, clamd_client=None) -> None:
    """Raises MalwareDetectedError or ScanUnavailableError; returns
    normally when the file is clean. Never writes to MinIO itself — the
    caller only proceeds to storage.upload_bytes after this returns."""
    file_hash = sha256_hex(data)
    try:
        result = scan_bytes(data, client=clamd_client)
    except ClamAVUnavailableError as e:
        await write_audit_log(
            db, entity_type="document", entity_id=None, action="upload_scan_unavailable",
            payload={"filename_hash": file_hash, "error": str(e)},
        )
        raise ScanUnavailableError(str(e)) from e

    if not result.clean:
        await write_audit_log(
            db, entity_type="document", entity_id=None, action="upload_rejected_malware",
            payload={"filename_hash": file_hash, "signature": result.signature},
        )
        raise MalwareDetectedError(result.signature or "unknown")


async def store_and_record_upload(
    db: AsyncSession, kafka_producer, data: bytes, filename: str, content_type: str, uploaded_by: str,
) -> Document:
    """Called only after scan_upload() has confirmed the file is clean."""
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
