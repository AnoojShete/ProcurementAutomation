from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document
from app.schemas import DataResponse, ReviewCorrectionRequest
from app.services import document_service
from app.services.upload_service import scan_upload, store_and_record_upload, MalwareDetectedError, ScanUnavailableError

router = APIRouter()


def _serialize_document(doc: Document) -> dict:
    return {
        "id": doc.id,
        "status": doc.status,
        "document_type": doc.document_type,
        "vendor_id": doc.vendor_id,
        "vendor_name_raw": doc.vendor_name_raw,
        "extracted_fields": doc.extracted or {},
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
    uploaded_by: str = Form("unknown"),
    db: AsyncSession = Depends(get_db),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="uploaded file is empty")

    try:
        await scan_upload(data, db, file.filename or "upload")
    except MalwareDetectedError as e:
        await db.commit()
        raise HTTPException(status_code=422, detail=f"upload rejected: malware detected ({e.signature})")
    except ScanUnavailableError:
        await db.commit()
        raise HTTPException(status_code=503, detail="scanning unavailable, try again")

    doc = await store_and_record_upload(
        db, request.app.state.kafka_producer, data, file.filename or "upload",
        file.content_type or "application/octet-stream", uploaded_by,
    )
    return DataResponse(data={"document_id": doc.id, "status": doc.status})


@router.get("/", response_model=DataResponse)
async def list_documents(limit: int = 100, db: AsyncSession = Depends(get_db)):
    """All documents regardless of status, most recent first — backs the
    tracking dashboard."""
    docs = await document_service.list_all_documents(db, limit=limit)
    return DataResponse(data=[_serialize_document(d) for d in docs], meta={"count": len(docs)})


@router.get("/review-queue", response_model=DataResponse)
async def get_review_queue(limit: int = 50, db: AsyncSession = Depends(get_db)):
    docs = await document_service.list_review_queue(db, limit=limit)
    return DataResponse(data=[_serialize_document(d) for d in docs])


@router.get("/{document_id}", response_model=DataResponse)
async def get_document_endpoint(document_id: str, db: AsyncSession = Depends(get_db)):
    doc = await document_service.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return DataResponse(data=_serialize_document(doc))


@router.post("/{document_id}/review", response_model=DataResponse)
async def review_document(
    document_id: str, correction: ReviewCorrectionRequest, request: Request, db: AsyncSession = Depends(get_db),
):
    doc = await document_service.submit_review(db, request.app.state.kafka_producer, document_id, correction)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return DataResponse(data=_serialize_document(doc))
