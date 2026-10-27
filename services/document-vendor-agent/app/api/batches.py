"""Document Batch Upload API endpoints (Prompt 11 Section 4).
Supports multi-file and folder upload batches with tracking, cancellation, retry, and CSV reporting.
"""
import csv
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document, DocumentBatch, DocumentBatchFile
from app.schemas import DataResponse
from shared.auth import CurrentUser, get_current_user
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)
router = APIRouter()


class BatchFileItem(BaseModel):
    client_file_id: str
    client_relative_path: str
    filename: str
    file_size_bytes: int


class CreateBatchRequest(BaseModel):
    total_files: int = Field(gt=0)
    files: List[BatchFileItem]
    metadata: Optional[Dict[str, Any]] = None


@router.post("/batches", response_model=DataResponse, status_code=201)
async def create_document_batch(
    payload: CreateBatchRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Initializes a multi-file or folder document batch."""
    max_batch_files = get_rule("document.upload_max_files_per_batch", fallback=500)
    if payload.total_files > max_batch_files or len(payload.files) > max_batch_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size exceeds maximum limit of {max_batch_files} files",
        )

    batch_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    uploader = user.email

    batch = DocumentBatch(
        id=batch_id,
        user_id=uploader,
        status="in_progress",
        total_files=len(payload.files),
        processed_files=0,
        failed_files=0,
        cancelled_files=0,
        created_at=now,
        metadata_json=payload.metadata or {},
    )
    db.add(batch)

    for item in payload.files:
        batch_file = DocumentBatchFile(
            id=str(uuid.uuid4()),
            batch_id=batch_id,
            client_file_id=item.client_file_id,
            client_relative_path=item.client_relative_path,
            filename=item.filename,
            file_size_bytes=item.file_size_bytes,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        db.add(batch_file)

    await db.commit()

    return DataResponse(
        data={
            "batch_id": batch_id,
            "status": "in_progress",
            "total_files": len(payload.files),
            "created_at": now.isoformat(),
        }
    )


@router.get("/batches/{batch_id}", response_model=DataResponse)
async def get_document_batch(
    batch_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves batch status, file counts, and individual file items."""
    batch = await db.get(DocumentBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    files_res = await db.execute(
        select(DocumentBatchFile)
        .where(DocumentBatchFile.batch_id == batch_id)
        .order_by(DocumentBatchFile.created_at)
    )
    files = files_res.scalars().all()

    file_items = [
        {
            "id": f.id,
            "client_file_id": f.client_file_id,
            "client_relative_path": f.client_relative_path,
            "filename": f.filename,
            "file_size_bytes": f.file_size_bytes,
            "sha256_hash": f.sha256_hash,
            "status": f.status,
            "document_id": f.document_id,
            "error_code": f.error_code,
            "error_detail": f.error_detail,
            "retry_count": f.retry_count,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        }
        for f in files
    ]

    return DataResponse(
        data={
            "batch_id": batch.id,
            "user_id": batch.user_id,
            "status": batch.status,
            "total_files": batch.total_files,
            "processed_files": batch.processed_files,
            "failed_files": batch.failed_files,
            "cancelled_files": batch.cancelled_files,
            "created_at": batch.created_at.isoformat() if batch.created_at else None,
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
            "metadata": batch.metadata_json or {},
            "files": file_items,
        }
    )


@router.post("/batches/{batch_id}/cancel", response_model=DataResponse)
async def cancel_document_batch(
    batch_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancels remaining queued files in a batch."""
    batch = await db.get(DocumentBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Update queued files to cancelled
    res = await db.execute(
        update(DocumentBatchFile)
        .where(DocumentBatchFile.batch_id == batch_id, DocumentBatchFile.status == "queued")
        .values(status="cancelled", updated_at=datetime.now(timezone.utc))
    )
    cancelled_count = res.rowcount or 0

    batch.cancelled_files += cancelled_count
    batch.status = "cancelled"
    batch.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return DataResponse(
        data={
            "batch_id": batch.id,
            "status": "cancelled",
            "cancelled_files": batch.cancelled_files,
        }
    )


@router.post("/batches/{batch_id}/retry-failed", response_model=DataResponse)
async def retry_failed_batch_files(
    batch_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resets failed files in a batch back to queued for retry."""
    batch = await db.get(DocumentBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    res = await db.execute(
        update(DocumentBatchFile)
        .where(DocumentBatchFile.batch_id == batch_id, DocumentBatchFile.status == "failed")
        .values(
            status="queued",
            error_code=None,
            error_detail=None,
            retry_count=DocumentBatchFile.retry_count + 1,
            updated_at=datetime.now(timezone.utc),
        )
    )
    retried_count = res.rowcount or 0

    batch.failed_files = max(0, batch.failed_files - retried_count)
    batch.status = "in_progress"
    batch.completed_at = None
    await db.commit()

    return DataResponse(
        data={
            "batch_id": batch.id,
            "status": "in_progress",
            "retried_files": retried_count,
        }
    )


@router.get("/batches/{batch_id}/report.csv")
async def download_batch_csv_report(
    batch_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Streams a CSV summary report of all files in the batch."""
    batch = await db.get(DocumentBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    files_res = await db.execute(
        select(DocumentBatchFile)
        .where(DocumentBatchFile.batch_id == batch_id)
        .order_by(DocumentBatchFile.client_relative_path)
    )
    files = files_res.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "client_file_id",
        "filename",
        "client_relative_path",
        "file_size_bytes",
        "sha256_hash",
        "status",
        "document_id",
        "error_code",
        "error_detail",
        "retry_count",
        "created_at",
        "updated_at",
    ])

    for f in files:
        writer.writerow([
            f.client_file_id,
            f.filename,
            f.client_relative_path,
            f.file_size_bytes,
            f.sha256_hash or "",
            f.status,
            f.document_id or "",
            f.error_code or "",
            f.error_detail or "",
            f.retry_count,
            f.created_at.isoformat() if f.created_at else "",
            f.updated_at.isoformat() if f.updated_at else "",
        ])

    csv_data = output.getvalue()
    filename = f"batch_{batch_id[:8]}_report.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
