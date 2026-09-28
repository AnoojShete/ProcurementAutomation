"""POST /documents/upload orchestration: scan -> store -> record -> publish.

Governance control B (malware scanning): every uploaded file is streamed
through ClamAV BEFORE it's written to MinIO. A flagged file is rejected
and never stored; an unreachable ClamAV fails the upload closed (503)
rather than skipping the scan.
"""
import asyncio
import io
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.services import storage
from app.services.audit import write_audit_log
from app.services.clamav_client import scan_bytes, sha256_hex, ClamAVUnavailableError
from shared.eventing import staged


class MalwareDetectedError(Exception):
    def __init__(self, signature: str):
        self.signature = signature
        super().__init__(f"malware detected: {signature}")


class ScanUnavailableError(Exception):
    pass


class StorageUnavailableError(Exception):
    """File storage (MinIO) couldn't take the file; nothing was recorded."""


class InvalidUploadError(Exception):
    """The file isn't something the pipeline should parse. Message is safe
    to show to the uploader."""


MAX_PDF_PAGES = 200
MAX_IMAGE_PIXELS = 40_000_000  # ~ 8000 x 5000; bigger is a decompression bomb, not a scan
_MAGIC = (
    (b"%PDF-", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image"),
    (b"\xff\xd8\xff", "image"),
)
_EXTENSIONS = {"pdf": "pdf", "png": "image", "jpg": "image", "jpeg": "image"}
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._() -]+")


def safe_filename(filename: str | None) -> str:
    """Last path component only, printable safe characters, bounded length —
    it becomes part of the MinIO object key and is shown in the UI."""
    name = (filename or "").replace("\\", "/").split("/")[-1]
    name = _UNSAFE_CHARS.sub("_", name).strip(" .")
    if len(name) > 150:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:140] + dot + ext[:8]) if dot else name[:150]
    return name or "upload"


def sniff_file_type(data: bytes) -> str | None:
    for magic, kind in _MAGIC:
        if data.startswith(magic):
            return kind
    return None


def validate_upload(data: bytes, filename: str) -> str:
    """Returns the sniffed file type ("pdf" | "image") or raises
    InvalidUploadError. The declared extension/content-type isn't trusted:
    what the parser sees is decided by the bytes."""
    kind = sniff_file_type(data)
    if kind is None:
        raise InvalidUploadError("unsupported file type — upload a PDF, PNG or JPEG")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext and _EXTENSIONS.get(ext) not in (None, kind):
        raise InvalidUploadError(f"file content is {kind.upper()} but the name says .{ext}")
    if kind == "pdf":
        pages = len(re.findall(rb"/Type\s*/Page(?![s\w])", data))
        if pages > MAX_PDF_PAGES:
            raise InvalidUploadError(f"PDF has too many pages (max {MAX_PDF_PAGES})")
    else:
        from PIL import Image
        try:
            with Image.open(io.BytesIO(data)) as img:  # reads the header only
                width, height = img.size
        except Image.DecompressionBombError:
            raise InvalidUploadError("image dimensions are too large")
        except Exception:
            raise InvalidUploadError("image could not be read")
        if width * height > MAX_IMAGE_PIXELS:
            raise InvalidUploadError("image dimensions are too large")
    return kind


async def scan_upload(data: bytes, db: AsyncSession, filename: str, clamd_client=None) -> None:
    """Raises MalwareDetectedError or ScanUnavailableError; returns
    normally when the file is clean. Never writes to MinIO itself — the
    caller only proceeds to storage.upload_bytes after this returns."""
    file_hash = sha256_hex(data)
    try:
        # python-clamd is a blocking socket client; run it off the event
        # loop so a scan doesn't stall every other request on this worker.
        result = await asyncio.to_thread(scan_bytes, data, clamd_client)
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
    """Called only after scan_upload() has confirmed the file is clean.
    Raises InvalidUploadError before anything is stored."""
    filename = safe_filename(filename)
    file_type = validate_upload(data, filename)
    document_id = str(uuid.uuid4())
    object_name = f"{document_id}/{filename}"
    try:
        minio_path = await storage.upload_bytes(object_name, data, content_type or "application/octet-stream")
    except Exception as e:
        raise StorageUnavailableError(str(e)) from e

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
    await write_audit_log(
        db, entity_type="document", entity_id=document_id, action="uploaded",
        payload={"filename": filename, "file_type": file_type, "sha256": sha256_hex(data),
                 "uploaded_by": uploaded_by, "malware_scan": "clean"},
    )
    # Committed together with the document row (shared/eventing/outbox.py):
    # an upload can no longer be recorded without its processing event.
    await staged(kafka_producer, db).publish_document_ingested(
        document_id=document_id, uploaded_by=uploaded_by, file_type=file_type,
        minio_path=minio_path, uploaded_at=uploaded_at,
    )
    await db.commit()
    return doc
