"""Best-effort recipient resolution for events whose payload (per
shared/schemas/events.md) has no directly-addressable human contact.

notification-agent shares the same Postgres schema as every other
service, so for a few event types we do a small read-only lookup against
tables owned by other services (purchase_requests, contracts) to find a
real recipient instead of always falling back to the generic ops address.
We never write through these — see app/models.py's PurchaseRequestRef /
ContractRef for the (partial, read-only) mappings.

Every lookup here is wrapped so a missing table/column (e.g. running
against a fresh DB before other services' own migrations have run) never
crashes the consumer — it just falls back to config.default_recipient().
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import default_recipient
from app.models import PurchaseRequestRef, ContractRef

logger = logging.getLogger(__name__)


async def requester_for_request_id(db: AsyncSession, request_id: Optional[str]) -> Optional[str]:
    """approval.decided's payload has no requester contact — only
    request_id — so look it up in purchase_requests.requested_by."""
    if not request_id:
        return None
    try:
        row = await db.get(PurchaseRequestRef, request_id)
        return row.requested_by if row else None
    except Exception as e:
        logger.warning(f"requester_for_request_id({request_id}) lookup failed: {e}")
        return None


async def requester_for_contract_id(db: AsyncSession, contract_id: Optional[str]) -> Optional[str]:
    """contract.generated / contract.signed / contract.renewal.due only
    carry contract_id (+ vendor_id) — join contracts -> purchase_requests
    to find the original requester."""
    if not contract_id:
        return None
    try:
        contract = await db.get(ContractRef, contract_id)
        if not contract or not contract.purchase_request_id:
            return None
        return await requester_for_request_id(db, contract.purchase_request_id)
    except Exception as e:
        logger.warning(f"requester_for_contract_id({contract_id}) lookup failed: {e}")
        return None


def as_email(identifier: str) -> str:
    """Some payload fields documented as ids rather than addresses (e.g.
    approval.requested's `approval_chain` is "array of approver ids", not
    emails) can arrive as bare usernames like "dept_manager". A real SMTP
    server (Mailpit included) validates RFC 5321 recipients and rejects
    those outright, so normalize any non-email-looking identifier into a
    deliverable placeholder address rather than losing the notification."""
    if "@" in identifier:
        return identifier
    return f"{identifier}@users.procurement.local"


async def resolve_recipient(db: AsyncSession, candidate: Optional[str]) -> str:
    """Fall back to the configured default recipient if no candidate
    address/id could be resolved; normalize whatever we do have into a
    deliverable email address."""
    return as_email(candidate) if candidate else default_recipient()
