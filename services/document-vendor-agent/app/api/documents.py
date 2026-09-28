from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Document
from app.schemas import DataResponse, ReviewCorrectionRequest
from app.services import document_service
from app.services.upload_service import (
    InvalidUploadError, MalwareDetectedError, ScanUnavailableError, StorageUnavailableError, scan_upload,
    store_and_record_upload,
)
from shared.auth import CurrentUser, get_current_user
from shared.idempotency import get_cached_response, store_response

router = APIRouter()


# Roles that work across everyone's documents; requesters only see their own.
STAFF_ROLES = frozenset({"approver", "finance", "admin"})
# Roles allowed to see vendor bank details in full.
PAYMENT_ROLES = frozenset({"finance", "admin"})
_PAYMENT_FIELDS = ("bank_account_number", "routing_code")


def _mask(value) -> str | None:
    if not value:
        return value
    text = str(value)
    return "••••" + text[-4:] if len(text) > 4 else "••••"


def _visible_extracted(extracted: dict, user: CurrentUser | None) -> dict:
    if user is not None and user.role in PAYMENT_ROLES:
        return extracted
    out = dict(extracted)
    for key in _PAYMENT_FIELDS:
        if out.get(key):
            out[key] = _mask(out[key])
    return out


def _can_access(doc: Document, user: CurrentUser) -> bool:
    return user.role in STAFF_ROLES or (doc.uploaded_by or "").lower() == user.email.lower()


def _serialize_document(doc: Document, user: CurrentUser | None = None) -> dict:
    return {
        "id": doc.id,
        "status": doc.status,
        "document_type": doc.document_type,
        "vendor_id": doc.vendor_id,
        "vendor_name_raw": doc.vendor_name_raw,
        "extracted_fields": _visible_extracted(doc.extracted or {}, user),
        "confidence_scores": doc.confidence or {},
        "overall_confidence": float(doc.overall_confidence) if doc.overall_confidence is not None else None,
        "needs_review": doc.needs_review,
        "is_likely_duplicate": doc.is_likely_duplicate,
        "duplicate_of_document_id": doc.duplicate_of_document_id,
        "file_type": doc.file_type,
        "original_filename": doc.original_filename,
        "uploaded_by": doc.uploaded_by,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "reviewed_by": doc.reviewed_by,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
        "error_message": doc.error_message,
    }


@router.post("/upload", response_model=DataResponse, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # The uploader is the signed-in user, never a form field: it becomes the
    # submitter of any bank-detail change the document carries, and dual
    # control relies on submitter != verifier.
    uploaded_by = user.email
    if idempotency_key:
        cached = await get_cached_response(request.app.state.redis, "document-vendor-agent", idempotency_key, scope=user.id)
        if cached is not None:
            return cached
    # Read at most one byte past the cap so an oversized upload is caught
    # without buffering all of it.
    data = await file.read(settings.max_upload_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file too large (max {settings.max_upload_bytes // (1024 * 1024)} MB)",
        )

    try:
        await scan_upload(data, db, file.filename or "upload")
    except MalwareDetectedError as e:
        await db.commit()
        raise HTTPException(status_code=422, detail=f"upload rejected: malware detected ({e.signature})")
    except ScanUnavailableError:
        await db.commit()
        raise HTTPException(status_code=503, detail="scanning unavailable, try again")

    try:
        doc = await store_and_record_upload(
            db, request.app.state.kafka_producer, data, file.filename or "upload",
            file.content_type or "application/octet-stream", uploaded_by,
        )
    except InvalidUploadError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except StorageUnavailableError:
        raise HTTPException(status_code=503, detail="file storage is temporarily unavailable — please try again in a minute")
    result = DataResponse(data={"document_id": doc.id, "status": doc.status})
    if idempotency_key:
        await store_response(request.app.state.redis, "document-vendor-agent", idempotency_key, result.model_dump(mode="json"), scope=user.id)
    return result


@router.post("/upload/batch", response_model=DataResponse, status_code=201)
async def upload_documents_batch(
    request: Request,
    response: Response,
    files: list[UploadFile] = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload several documents in one request. Each file is scanned,
    stored and queued on its own, so one bad file doesn't sink the rest:
    the response lists a result per file, in upload order. Every accepted
    file gets its own document.ingested event and the worker processes
    them in parallel."""
    if len(files) > settings.max_batch_files:
        raise HTTPException(status_code=413, detail=f"too many files (max {settings.max_batch_files} per batch)")

    results: list[dict] = []
    total_bytes = 0
    for upload in files:
        filename = upload.filename or "upload"
        data = await upload.read(settings.max_upload_bytes + 1)
        total_bytes += len(data)
        if not data:
            results.append({"filename": filename, "error": "file is empty"})
            continue
        if len(data) > settings.max_upload_bytes:
            results.append({
                "filename": filename,
                "error": f"file too large (max {settings.max_upload_bytes // (1024 * 1024)} MB)",
            })
            continue
        if total_bytes > settings.max_batch_bytes:
            results.append({
                "filename": filename,
                "error": f"batch size limit reached (max {settings.max_batch_bytes // (1024 * 1024)} MB)",
            })
            continue

        try:
            await scan_upload(data, db, filename)
        except MalwareDetectedError as e:
            await db.commit()
            results.append({"filename": filename, "error": f"rejected: malware detected ({e.signature})"})
            continue
        except ScanUnavailableError:
            await db.commit()
            results.append({"filename": filename, "error": "scanning unavailable, try again"})
            continue

        try:
            doc = await store_and_record_upload(
                db, request.app.state.kafka_producer, data, filename,
                upload.content_type or "application/octet-stream", user.email,
            )
        except InvalidUploadError as e:
            results.append({"filename": filename, "error": str(e)})
            continue
        except StorageUnavailableError:
            results.append({"filename": filename, "error": "file storage is temporarily unavailable — try again in a minute"})
            continue
        results.append({"filename": filename, "document_id": doc.id, "status": doc.status})

    accepted = sum(1 for r in results if "document_id" in r)
    if accepted == 0:
        response.status_code = 422
    return DataResponse(data=results, meta={"accepted": accepted, "rejected": len(results) - accepted})


@router.get("/", response_model=DataResponse)
async def list_documents(limit: int = 100, db: AsyncSession = Depends(get_db),
                         user: CurrentUser = Depends(get_current_user)):
    """Documents regardless of status, most recent first — backs the
    tracking dashboard. Requesters see only what they uploaded."""
    owner = None if user.role in STAFF_ROLES else user.email
    docs = await document_service.list_all_documents(db, limit=limit, uploaded_by=owner)
    return DataResponse(data=[_serialize_document(d, user) for d in docs], meta={"count": len(docs)})


@router.get("/learning/stats", response_model=DataResponse)
async def learning_stats(db: AsyncSession = Depends(get_db)):
    """What the system has learned from reviewer corrections, per vendor."""
    from app.services.learning import learning_stats as stats
    return DataResponse(data=await stats(db))


@router.get("/review-queue", response_model=DataResponse)
async def get_review_queue(limit: int = 50, db: AsyncSession = Depends(get_db),
                           user: CurrentUser = Depends(get_current_user)):
    owner = None if user.role in STAFF_ROLES else user.email
    docs = await document_service.list_review_queue(db, limit=limit, uploaded_by=owner)
    return DataResponse(data=[_serialize_document(d, user) for d in docs])


@router.get("/{document_id}", response_model=DataResponse)
async def get_document_endpoint(document_id: str, db: AsyncSession = Depends(get_db),
                                user: CurrentUser = Depends(get_current_user)):
    doc = await document_service.get_document(db, document_id)
    # 404 rather than 403 for someone else's document: don't confirm it exists.
    if doc is None or not _can_access(doc, user):
        raise HTTPException(status_code=404, detail="document not found")
    return DataResponse(data=_serialize_document(doc, user))


@router.post("/{document_id}/review", response_model=DataResponse)
async def review_document(
    document_id: str, correction: ReviewCorrectionRequest, request: Request, db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    # The reviewer is whoever is signed in — corrections train the
    # extraction (app/services/learning.py), so they must be attributable.
    correction = correction.model_copy(update={"reviewed_by": user.email})
    if correction.extracted_fields:
        # Bank details never change through document review — only through
        # the dual-control verification flow. (Non-finance reviewers also only
        # ever see them masked, so echoing them back would store the mask.)
        correction = correction.model_copy(update={"extracted_fields": {
            k: v for k, v in correction.extracted_fields.items()
            if k not in (*_PAYMENT_FIELDS, "payment_beneficiary_name")
        }})
    existing = await document_service.get_document(db, document_id)
    if existing is None or not _can_access(existing, user):
        raise HTTPException(status_code=404, detail="document not found")
    doc = await document_service.submit_review(db, request.app.state.kafka_producer, document_id, correction)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return DataResponse(data=_serialize_document(doc, user))
