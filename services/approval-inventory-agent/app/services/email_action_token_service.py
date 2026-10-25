"""Token lifecycle, Step-Up rules, and revocation for Email Actions (Prompt 8 Part A).

Guarantees:
1. Tokens are 256-bit URL-safe secrets (secrets.token_urlsafe(32)), stored strictly
   as SHA-256 hashes in the database.
2. Tokens are single-action, sequentially minted only when that step is active.
3. Expiry is computed using database time (func.now() / UTC), comparing against
   the earlier of SLA deadline and email_token_ttl_hours rule.
4. Step-Up rules enforce portal-only login for high-risk / over-budget / large requests.
"""
import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailActionToken, PurchaseRequest, Vendor
from app.services import approval_authority as authority
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)


def hash_token(raw_token: str) -> str:
    """Computes SHA-256 hex digest of the raw token."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def get_public_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", os.environ.get("APP_BASE_URL", "http://localhost:8080")).rstrip("/")


async def revoke_tokens(
    db: AsyncSession,
    request_id: str,
    step_index: Optional[int] = None,
    reason: str = "revoked",
) -> int:
    """Revokes active, unused email action tokens for a request.
    Called on portal decision, SLA escalation, cancellation, delegation change, etc.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        update(EmailActionToken)
        .where(
            EmailActionToken.request_id == request_id,
            EmailActionToken.revoked_at.is_(None),
            EmailActionToken.used_at.is_(None),
        )
        .values(revoked_at=now, revoked_reason=reason)
    )
    if step_index is not None:
        stmt = stmt.where(EmailActionToken.step_index == step_index)

    result = await db.execute(stmt)
    count = getattr(result, "rowcount", 0)
    if isinstance(count, int) and count > 0:
        logger.info(f"Revoked {count} email action token(s) for request {request_id} (reason: {reason})")
    return count if isinstance(count, int) else 0



async def mint_email_action_token(
    db: AsyncSession,
    request_id: str,
    approver_id: str,
    step_index: int,
) -> Tuple[str, datetime, str]:
    """Mints a single-action token for an active step in the approval chain.

    Returns:
        (raw_token, expires_at, action_url)

    Raises:
        ValueError if request is not pending, step is inactive, SoD fails, etc.
    """
    req = await db.get(PurchaseRequest, request_id)
    if not req:
        raise ValueError(f"Purchase request {request_id} not found")
    if req.status != "pending_approval":
        raise ValueError(f"Request {request_id} is in status '{req.status}', cannot mint token")

    chain = req.approval_chain or []
    if req.current_approver_index != step_index:
        raise ValueError(
            f"Step {step_index} is not currently active (current active step is {req.current_approver_index})"
        )
    if step_index >= len(chain):
        raise ValueError("Approval chain already completed")

    level = chain[step_index]

    # Resolve delegation: if this step was delegated, token belongs to the DELEGATE
    delegations = await authority.load_delegations(db, level)
    now = datetime.now(timezone.utc)
    target_approver = approver_id
    for d in delegations:
        if d.level == level and d.delegator_email.lower() == approver_id.lower() and (d.valid_from <= now <= d.valid_until):
            target_approver = d.delegate_email
            logger.info(f"Delegation resolved: step {step_index} delegator {approver_id} -> delegate {target_approver}")
            break

    # Segregation of duties at mint time: approver cannot be the requester
    if target_approver.lower() == (req.requested_by or "").lower():
        raise ValueError(f"Approver {target_approver} cannot approve request raised by self (Segregation of Duties)")

    # Revoke any previous active token for (request_id, target_approver, step_index)
    await revoke_tokens(db, request_id, step_index=step_index, reason="superseded")

    # Expiry calculation: min(sla_deadline, now + email_token_ttl_hours)
    ttl_hours = int(get_rule("approval.email_token_ttl_hours", fallback=48))
    ttl_deadline = now + timedelta(hours=ttl_hours)
    if req.sla_deadline:
        # Normalize timezone
        sla_dt = req.sla_deadline if req.sla_deadline.tzinfo else req.sla_deadline.replace(tzinfo=timezone.utc)
        expires_at = min(sla_dt, ttl_deadline)
    else:
        expires_at = ttl_deadline

    # Generate 256-bit URL-safe token
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)

    row = EmailActionToken(
        id=str(uuid.uuid4()),
        token_hash=token_hash,
        request_id=request_id,
        approver_id=target_approver,
        step_index=step_index,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(row)
    await db.commit()

    action_url = f"{get_public_base_url()}/email-action/{raw_token}"
    logger.info(f"Minted email action token for request {request_id}, step {step_index}, approver {target_approver}")
    return raw_token, expires_at, action_url


def evaluate_step_up(
    amount: float | Decimal,
    over_budget: bool,
    vendor_risk_band: Optional[str],
    risk_lookup_failed: bool = False,
) -> Tuple[bool, bool, Optional[str]]:
    """Evaluates Step-Up rules from the Business Rules Engine.

    Returns:
        (email_action_enabled, step_up_required, reason)
        - If email_action_enabled is False: both Approve & Reject are disabled.
        - If step_up_required is True: Approve is disabled (requires portal login),
          but Reject remains allowed.
    """
    enabled = bool(get_rule("approval.email_action_enabled", fallback=True))
    if not enabled:
        return False, True, "Email actions are currently disabled by system policy."

    max_amount = Decimal(str(get_rule("approval.email_action_max_amount", fallback=50000)))
    allowed_over_budget = bool(get_rule("approval.email_action_allowed_over_budget", fallback=False))
    allowed_high_risk = bool(get_rule("approval.email_action_allowed_high_risk_vendor", fallback=False))

    dec_amount = Decimal(str(amount))
    if dec_amount > max_amount:
        return True, True, f"Request amount ({dec_amount:,.2f}) exceeds the email action limit of {max_amount:,.2f}. Login to portal required."

    if over_budget and not allowed_over_budget:
        return True, True, "Request is over budget. Login to portal required to authorize over-budget spend."

    if risk_lookup_failed:
        # Fail closed
        return True, True, "Vendor risk assessment is unavailable. Login to portal required for verification."

    if (vendor_risk_band or "").strip().lower() == "high" and not allowed_high_risk:
        return True, True, "Vendor is categorized as High Risk. Login to portal required for high-risk vendor approval."

    return True, False, None


async def mint_batch_action_token(
    db: AsyncSession,
    approver_id: str,
    request_ids: list,
) -> Tuple[str, datetime, str]:
    """Mints an email batch token for digest approvals (Prompt 10 Section 1.5)."""
    from app.models import EmailBatchToken
    now = datetime.now(timezone.utc)
    ttl_hours = int(get_rule("approval.bulk_email_token_ttl_hours", fallback=48))
    expires_at = now + timedelta(hours=ttl_hours)

    raw_token = secrets.token_urlsafe(32)
    token_h = hash_token(raw_token)

    batch_token = EmailBatchToken(
        id=str(uuid.uuid4()),
        token_hash=token_h,
        approver_id=approver_id,
        request_ids=request_ids,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(batch_token)
    await db.commit()

    action_url = f"{get_public_base_url()}/email-action/batch/{raw_token}"
    return raw_token, expires_at, action_url


async def revoke_batch_tokens(
    db: AsyncSession,
    approver_id: str,
    reason: str,
) -> int:
    """Revokes all active email batch tokens for an approver."""
    from app.models import EmailBatchToken
    now = datetime.now(timezone.utc)
    stmt = (
        update(EmailBatchToken)
        .where(
            EmailBatchToken.approver_id == approver_id,
            EmailBatchToken.used_at.is_(None),
            EmailBatchToken.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoked_reason=reason)
    )
    res = await db.execute(stmt)
    await db.commit()
    return res.rowcount
