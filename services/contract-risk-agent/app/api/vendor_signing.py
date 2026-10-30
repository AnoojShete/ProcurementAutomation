"""The vendor's contract signing page (/sign on the frontend).

Not JWT-gated: the vendor's signatory has no platform account. The emailed
link's random token is the credential (only its SHA-256 is stored), sent in
the body because the link carries it after "#".
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import DataResponse, VendorSigningRequest
from app.services import signing_service

router = APIRouter()


@router.post("/vendor-signing/session", response_model=DataResponse)
async def vendor_signing_session(data: VendorSigningRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """What the vendor is signing and, while it is their turn, their
    Documenso signing token for the embedded frame."""
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else None)
    try:
        session = await signing_service.vendor_session(
            db, data.link_token, ip_address=ip, user_agent=request.headers.get("user-agent"))
    except signing_service.SigningLinkInvalid as e:
        raise HTTPException(status_code=404, detail={"code": "invalid_link", "message": str(e)})
    return DataResponse(data=session)
