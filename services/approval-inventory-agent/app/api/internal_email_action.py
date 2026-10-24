"""Internal endpoint for minting email action tokens (Prompt 8 A4).

Never exposed through the gateway. Requires X-Internal-Service-Token header.
"""
import hmac
import os
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_INTERNAL_SERVICE_TOKEN
from app.database import get_db
from app.services.email_action_token_service import mint_email_action_token

logger = logging.getLogger(__name__)

router = APIRouter()

def get_internal_token() -> str:
    return os.environ.get("INTERNAL_SERVICE_TOKEN", DEFAULT_INTERNAL_SERVICE_TOKEN)


class MintTokenRequest(BaseModel):
    request_id: str
    approver_id: str
    step_index: int = Field(ge=0)


class MintTokenResponse(BaseModel):
    action_url: str
    expires_at: str


@router.post("/mint", response_model=dict)
async def mint_email_action(
    payload: MintTokenRequest,
    x_internal_service_token: Optional[str] = Header(None, alias="X-Internal-Service-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Mints an email action token for an active step in the approval chain.

    Requires secret token in X-Internal-Service-Token header.
    Validates approver is active, authorized, and not the requester before minting.
    """
    expected_token = get_internal_token()
    if not x_internal_service_token or not hmac.compare_digest(x_internal_service_token, expected_token):
        logger.warning("Rejected /internal/email-actions/mint request with invalid/missing token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: invalid or missing internal service token",
        )

    try:
        raw_token, expires_at, action_url = await mint_email_action_token(
            db,
            request_id=payload.request_id,
            approver_id=payload.approver_id,
            step_index=payload.step_index,
        )
    except ValueError as e:
        logger.warning(f"Minting refused: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return {
        "data": {
            "action_url": action_url,
            "expires_at": expires_at.isoformat(),
        }
    }


class MintBatchTokenRequest(BaseModel):
    approver_id: str
    request_ids: list[str] = Field(..., min_length=1)


@router.post("/mint-batch", response_model=dict)
async def mint_email_batch(
    payload: MintBatchTokenRequest,
    x_internal_service_token: Optional[str] = Header(None, alias="X-Internal-Service-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Mints an email batch token for bulk digest approvals (Prompt 10 Section 1.5)."""
    expected_token = get_internal_token()
    if not x_internal_service_token or not hmac.compare_digest(x_internal_service_token, expected_token):
        logger.warning("Rejected /internal/email-actions/mint-batch with invalid/missing token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: invalid or missing internal service token",
        )

    from app.services.email_action_token_service import mint_batch_action_token
    try:
        raw_token, expires_at, action_url = await mint_batch_action_token(
            db,
            approver_id=payload.approver_id,
            request_ids=payload.request_ids,
        )
    except Exception as e:
        logger.warning(f"Batch minting refused: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return {
        "data": {
            "batch_url": action_url,
            "expires_at": expires_at.isoformat(),
        }
    }
