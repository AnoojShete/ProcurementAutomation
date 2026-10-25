"""Service-to-service endpoints (no user login).

Never exposed through the gateway: nginx only forwards /api/<prefix>/ paths,
and none of them map to /internal/. Requires the X-Internal-Service-Token
header (INTERNAL_SERVICE_TOKEN, shared with approval-inventory-agent).

approval-inventory-agent checks vendor clearance here for bulk approval and
email approval, where there is no user JWT to forward. The public
GET /vendors/{id}/clearance still requires a login.
"""
import hmac
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_INTERNAL_SERVICE_TOKEN
from app.database import get_db
from app.schemas import DataResponse
from app.services import clearance

logger = logging.getLogger(__name__)

router = APIRouter()


def require_internal_token(
    x_internal_service_token: Optional[str] = Header(None, alias="X-Internal-Service-Token"),
) -> None:
    expected = os.environ.get("INTERNAL_SERVICE_TOKEN", DEFAULT_INTERNAL_SERVICE_TOKEN)
    if not x_internal_service_token or not hmac.compare_digest(x_internal_service_token, expected):
        logger.warning("Rejected internal request with invalid/missing X-Internal-Service-Token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "forbidden", "message": "Invalid or missing internal service token"},
        )


@router.get("/vendors/{vendor_id}/clearance", response_model=DataResponse,
            dependencies=[Depends(require_internal_token)])
async def get_vendor_clearance_internal(
    vendor_id: str,
    purpose: str = Query("purchase", pattern="^(activation|purchase|contract)$"),
    spend_amount: Optional[float] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Same check as GET /vendors/{id}/clearance (app/services/clearance.py)."""
    result = await clearance.evaluate(db, vendor_id, purpose=purpose, spend_amount=spend_amount)
    if result is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    return DataResponse(data=result)
