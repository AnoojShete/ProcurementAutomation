"""Signing authority mandates API (Prompt 10 Section 2.1).

Created only by the user themselves on "My signing authority" page:
- Show exact versioned mandate text.
- Require password re-entry.
- Cap validity at rule contract.mandate_max_days (default 90).
- An admin cannot create a mandate for someone else.
- Revocable at any time.
- Only roles in rule contract.auto_sign_roles (default ["finance"]) can hold a mandate.
"""
import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Contract, SigningMandate, Vendor
from shared.auth import CurrentUser
from shared.auth.middleware import get_current_user, require_role
from shared.rules_engine import get_auth_service_url, get_rule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mandates", tags=["Signing Mandates"])

MANDATE_TEXT_VERSION = "v1.0"
MANDATE_TEMPLATE = (
    "I, {name}, in my role as {role}, hereby authorize the automated application of "
    "my digital signature to standard vendor contracts resulting from purchase requests that "
    "I have approved in bulk or via authenticated email batches, strictly within the approved "
    "maximum spend limit of INR {max_amount:,.2f} and during the validity period specified herein. "
    "I acknowledge that each automated signature applied under this mandate constitutes an "
    "internal authorization record legally equivalent to my personal electronic signature "
    "in accordance with platform policies."
)


def build_mandate_text(name: str, role: str, max_amount: float) -> str:
    return MANDATE_TEMPLATE.format(name=name, role=role, max_amount=max_amount)


async def verify_password_with_auth(authorization: str, password: str) -> None:
    """Asks auth-service whether `password` is the signed-in user's, by
    forwarding the caller's own bearer token (so the identity is the JWT's).
    Wrong password -> 400 wrong_password; auth-service unreachable -> 503.
    No fallback."""
    url = f"{get_auth_service_url()}/auth/verify-password"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json={"password": password},
                                     headers={"Authorization": authorization})
    except httpx.HTTPError as e:
        logger.warning(f"Could not reach auth-service to verify password at {url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "auth_unavailable",
                    "message": "Couldn't check your password right now. Try again in a minute."},
        )
    if resp.status_code == 200:
        return
    if resp.status_code == 429:
        raise HTTPException(status_code=429, detail={
            "code": "account_locked",
            "message": "Too many wrong passwords. Your account is locked for a few minutes."})
    if resp.status_code != 400:
        logger.warning(f"auth-service password check answered {resp.status_code}: {resp.text[:200]}")
    # 400, not 401: the web client treats any 401 as an expired session and signs out.
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "wrong_password",
                "message": "Incorrect password. Password re-entry is required to issue a signing authority mandate."},
    )


class CreateMandateRequest(BaseModel):
    password: str = Field(..., min_length=1)
    max_amount_per_contract: float = Field(..., gt=0)
    validity_days: int = Field(90, ge=1, le=365)


class MandateResponse(BaseModel):
    id: str
    user_id: str
    role: str
    scope: str
    max_amount_per_contract: float
    valid_from: str
    valid_until: str
    mandate_text_version: str
    mandate_text_sha256: str
    accepted_at: str
    status: str
    is_active: bool
    mandate_text: Optional[str] = None


@router.get("/template")
async def get_mandate_template(user: CurrentUser = Depends(get_current_user)):
    """Returns the versioned mandate text template and caller defaults."""
    allowed_roles = get_rule("contract.auto_sign_roles", fallback=["finance"])
    if not isinstance(allowed_roles, list):
        allowed_roles = ["finance"]
    is_eligible = user.role.lower() in [r.lower() for r in allowed_roles]

    max_rule_amount = float(get_rule("contract.auto_sign_max_amount", fallback=25000.0))
    max_days = int(get_rule("contract.mandate_max_days", fallback=90))

    sample_text = build_mandate_text(user.email, user.role.capitalize(), max_rule_amount)
    sample_sha = hashlib.sha256(sample_text.encode("utf-8")).hexdigest()

    return {"data": {
        "version": MANDATE_TEXT_VERSION,
        "template": MANDATE_TEMPLATE,
        "sample_text": sample_text,
        "sample_sha256": sample_sha,
        "is_eligible": is_eligible,
        "max_allowed_amount": max_rule_amount,
        "max_allowed_days": max_days,
    }}


@router.get("/active")
async def get_active_mandate(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Returns the caller's currently active mandate, if any."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(SigningMandate)
        .where(
            SigningMandate.user_id == user.email,
            SigningMandate.status == "active",
            SigningMandate.valid_until > now,
        )
        .order_by(SigningMandate.created_at.desc() if hasattr(SigningMandate, "created_at") else SigningMandate.accepted_at.desc())
    )
    res = await db.execute(stmt)
    mandate = res.scalars().first()
    if not mandate:
        return {"data": None}

    full_text = build_mandate_text(user.email, mandate.role, float(mandate.max_amount_per_contract))
    return {
        "data": {
            "id": str(mandate.id),
            "user_id": mandate.user_id,
            "role": mandate.role,
            "scope": mandate.scope,
            "max_amount_per_contract": float(mandate.max_amount_per_contract),
            "valid_from": mandate.valid_from.isoformat(),
            "valid_until": mandate.valid_until.isoformat(),
            "mandate_text_version": mandate.mandate_text_version,
            "mandate_text_sha256": mandate.mandate_text_sha256,
            "accepted_at": mandate.accepted_at.isoformat(),
            "status": mandate.status,
            "is_active": mandate.status == "active" and mandate.valid_until > now,
            "mandate_text": full_text,
        }
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_mandate(
    body: CreateMandateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Creates a new standing signing mandate for the caller (Prompt 10 Section 2.1).

    Requires password verification and role eligibility.
    """
    allowed_roles = get_rule("contract.auto_sign_roles", fallback=["finance"])
    if not isinstance(allowed_roles, list):
        allowed_roles = ["finance"]

    if user.role.lower() not in [r.lower() for r in allowed_roles]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role}' is not permitted to hold a signing mandate.",
        )

    # 1. Enforce max amount and max days against live rules
    max_rule_amount = float(get_rule("contract.auto_sign_max_amount", fallback=25000.0))
    if body.max_amount_per_contract > max_rule_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum amount per contract cannot exceed rule limit of INR {max_rule_amount:,.2f}",
        )

    max_rule_days = int(get_rule("contract.mandate_max_days", fallback=90))
    if body.validity_days > max_rule_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validity cannot exceed {max_rule_days} days.",
        )

    # 2. Re-check the caller's password with auth-service
    await verify_password_with_auth(request.headers.get("authorization", ""), body.password)

    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(days=body.validity_days)

    mandate_text = build_mandate_text(user.email, user.role.capitalize(), body.max_amount_per_contract)
    mandate_sha = hashlib.sha256(mandate_text.encode("utf-8")).hexdigest()

    # Deactivate existing active mandates for this user
    stmt_deact = select(SigningMandate).where(
        SigningMandate.user_id == user.email,
        SigningMandate.status == "active",
    )
    existing_active = (await db.execute(stmt_deact)).scalars().all()
    for m in existing_active:
        m.status = "revoked"
        m.revoked_at = now
        m.revoked_by = "superseded_by_new_mandate"

    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    mandate = SigningMandate(
        id=str(uuid.uuid4()),
        user_id=user.email,
        role=user.role,
        scope="bulk_approved_contracts",
        max_amount_per_contract=body.max_amount_per_contract,
        valid_from=now,
        valid_until=valid_until,
        mandate_text_version=MANDATE_TEXT_VERSION,
        mandate_text_sha256=mandate_sha,
        accepted_at=now,
        accepted_ip=client_ip,
        accepted_user_agent=user_agent,
        status="active",
    )
    db.add(mandate)
    await db.commit()
    await db.refresh(mandate)

    logger.info(f"Signing mandate {mandate.id} issued for user {user.email} (valid until {valid_until.isoformat()})")

    return {
        "data": {
            "id": str(mandate.id),
            "user_id": mandate.user_id,
            "role": mandate.role,
            "scope": mandate.scope,
            "max_amount_per_contract": float(mandate.max_amount_per_contract),
            "valid_from": mandate.valid_from.isoformat(),
            "valid_until": mandate.valid_until.isoformat(),
            "mandate_text_version": mandate.mandate_text_version,
            "mandate_text_sha256": mandate.mandate_text_sha256,
            "accepted_at": mandate.accepted_at.isoformat(),
            "status": mandate.status,
            "is_active": True,
            "mandate_text": mandate_text,
        }
    }


@router.post("/{mandate_id}/revoke")
async def revoke_mandate(
    mandate_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Revokes a signing mandate immediately."""
    mandate = await db.get(SigningMandate, mandate_id)
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandate not found")

    # Only owner or admin can revoke
    if mandate.user_id != user.email and user.role != "admin":
        raise HTTPException(status_code=403, detail="You can only revoke your own signing mandate.")

    now = datetime.now(timezone.utc)
    mandate.status = "revoked"
    mandate.revoked_at = now
    mandate.revoked_by = user.email
    await db.commit()

    logger.info(f"Signing mandate {mandate.id} revoked by {user.email}")
    return {"data": {"id": str(mandate.id), "status": "revoked", "revoked_at": now.isoformat()}}


@router.get("/recent-auto-signed")
async def list_recent_auto_signed_contracts(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("finance", "admin")),
):
    """Lists recent contracts auto-signed under mandate (Prompt 10 Section 2.4)."""
    stmt = (
        select(Contract)
        .where(Contract.signature_method == "auto_mandate")
        .order_by(desc(Contract.signed_at))
        .limit(limit)
    )
    contracts = (await db.execute(stmt)).scalars().all()

    results = []
    for c in contracts:
        vendor_name = "Unknown Vendor"
        if c.vendor_id:
            v = await db.get(Vendor, c.vendor_id)
            if v:
                vendor_name = v.name

        results.append({
            "contract_id": str(c.id),
            "purchase_request_id": str(c.purchase_request_id) if c.purchase_request_id else None,
            "vendor_name": vendor_name,
            "template": c.template,
            "signed_at": c.signed_at.isoformat() if c.signed_at else None,
            "signed_by": c.signed_by,
            "approval_channel": c.approval_channel,
            "mandate_id": str(c.mandate_id) if c.mandate_id else None,
            "bulk_batch_id": str(c.bulk_batch_id) if c.bulk_batch_id else None,
        })

    return {"data": results, "meta": {"count": len(results)}}
