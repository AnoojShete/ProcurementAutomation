"""Admin endpoints for Breach Catalogue and system operations (Prompt 11 Section 1.1)."""
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import DataResponse
from app.services.breach_catalogue import (
    download_and_store_catalogue,
    get_latest_catalogue_meta,
)
from shared.auth import CurrentUser, require_role

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/breach-catalogue/status", response_model=DataResponse)
async def get_catalogue_status(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin", "compliance", "procurement")),
):
    """Returns the current status of the local Have I Been Pwned breach catalogue."""
    meta = await get_latest_catalogue_meta(db)
    if not meta:
        return DataResponse(
            data={
                "loaded": False,
                "record_count": 0,
                "version_sha256": None,
                "fetched_at": None,
                "source": None,
                "attribution": "Breach data from Have I Been Pwned",
            }
        )

    return DataResponse(
        data={
            "loaded": True,
            "record_count": meta.record_count,
            "version_sha256": meta.version_sha256,
            "fetched_at": meta.fetched_at.isoformat(),
            "source": meta.source,
            "uploaded_by": meta.uploaded_by,
            "attribution": "Breach data from Have I Been Pwned",
        }
    )


@router.post("/breach-catalogue/import", response_model=DataResponse)
async def import_catalogue_manually(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    """Allows an administrator to manually upload or post the HIBP breaches JSON file."""
    raw_body = await request.body()
    if not raw_body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A JSON payload must be provided",
        )

    try:
        body_str = raw_body.decode("utf-8")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payload must be UTF-8 encoded: {e}",
        )

    # Validate JSON schema: must be a list of dicts with Name, Title, etc.
    try:
        parsed = json.loads(body_str)
        if not isinstance(parsed, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Expected a JSON array of breach objects",
            )
        if parsed and not isinstance(parsed[0], dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Breach objects in array must be JSON dictionaries",
            )
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed JSON: {e}",
        )

    uploader = getattr(user, "email", None) or getattr(user, "user_id", "admin")
    ok, msg, count = await download_and_store_catalogue(
        db,
        source="manual_upload",
        uploaded_by=uploader,
        raw_json_str=body_str,
    )

    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    meta = await get_latest_catalogue_meta(db)
    return DataResponse(
        data={
            "status": "imported",
            "message": msg,
            "record_count": count,
            "version_sha256": meta.version_sha256 if meta else None,
            "fetched_at": meta.fetched_at.isoformat() if meta else None,
            "attribution": "Breach data from Have I Been Pwned",
        }
    )


@router.post("/breach-catalogue/refresh", response_model=DataResponse)
async def refresh_catalogue_live(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    """Triggers an immediate download of the public HIBP breach catalogue."""
    uploader = getattr(user, "email", None) or getattr(user, "user_id", "admin")
    ok, msg, count = await download_and_store_catalogue(
        db, source="download", uploaded_by=uploader
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=msg)

    meta = await get_latest_catalogue_meta(db)
    return DataResponse(
        data={
            "status": "refreshed",
            "message": msg,
            "record_count": count,
            "version_sha256": meta.version_sha256 if meta else None,
            "fetched_at": meta.fetched_at.isoformat() if meta else None,
            "attribution": "Breach data from Have I Been Pwned",
        }
    )
