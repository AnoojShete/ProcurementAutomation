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
    request_id — so look it up in purchase_requests.requested_by / requested_by_user_id."""
    if not request_id:
        return None
    try:
        from app.models import UserRef
        row = await db.get(PurchaseRequestRef, request_id)
        if not row:
            return None
        user_id = getattr(row, "requested_by_user_id", None)
        if user_id:
            user = await db.get(UserRef, user_id)
            if user and user.email:
                return user.email
        return row.requested_by
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


# ── Feature expansion events (budgets, obligations, RFQs, deliveries) ───────
# Raw read-only lookups against other services' tables; each falls back to
# None when the table or row isn't there.
from sqlalchemy import text as _text

FINANCE_MAILBOX = "finance_head@users.procurement.local"


async def _scalar(db: AsyncSession, sql: str, params: dict):
    try:
        async with db.begin_nested():
            return (await db.execute(_text(sql), params)).scalar()
    except Exception as e:
        logger.warning(f"directory lookup failed ({sql[:40]}…): {e}")
        return None


async def budget_owner(db: AsyncSession, budget_id: Optional[str]) -> Optional[str]:
    if not budget_id:
        return None
    return await _scalar(db, "SELECT owner_email FROM budgets WHERE id = CAST(:b AS uuid)", {"b": budget_id})


def vendor_placeholder(vendor_id: str) -> str:
    """Vendors without a contact e-mail get a deliverable placeholder (Mailpit
    in development), so the invitation is still visible and logged."""
    return f"vendor-{str(vendor_id)[:8]}@vendors.procurement.local"


async def vendor_contact(db: AsyncSession, vendor_id: Optional[str]) -> Optional[str]:
    if not vendor_id:
        return None
    email = await _scalar(db, "SELECT contact_email FROM vendors WHERE id = CAST(:v AS uuid)", {"v": vendor_id})
    return email or vendor_placeholder(vendor_id)


async def vendor_name(db: AsyncSession, vendor_id: Optional[str]) -> Optional[str]:
    if not vendor_id:
        return None
    return await _scalar(db, "SELECT name FROM vendors WHERE id = CAST(:v AS uuid)", {"v": vendor_id})


async def rfq_items(db: AsyncSession, rfq_id: Optional[str]) -> list:
    if not rfq_id:
        return []
    items = await _scalar(db, "SELECT items FROM rfq_events WHERE id = CAST(:r AS uuid)", {"r": rfq_id})
    return items if isinstance(items, list) else []


# ── Approvers, reviewers and signers as real people ─────────────────────────
# approval.requested names approval levels (dept_manager, finance_head), not
# people. The approval authority table says who holds each level; without a
# match the level's placeholder mailbox is used, as before.

async def _column(db: AsyncSession, sql: str, params: dict) -> list[str]:
    try:
        async with db.begin_nested():
            return [r[0] for r in (await db.execute(_text(sql), params)).all() if r[0]]
    except Exception as e:
        logger.warning(f"directory lookup failed ({sql[:40]}…): {e}")
        return []


async def approvers_for_level(db: AsyncSession, level: Optional[str], amount: Optional[float] = None) -> list[str]:
    """Active people assigned to an approval level whose limit covers the amount."""
    if not level:
        return []
    return await _column(db, """
        SELECT user_email FROM approver_assignments
        WHERE level = :level AND active
          AND (max_amount IS NULL OR CAST(:amount AS numeric) IS NULL OR max_amount >= CAST(:amount AS numeric))
        ORDER BY user_email
    """, {"level": level, "amount": amount})


async def selected_approver(db: AsyncSession, request_id: Optional[str], level: Optional[str]) -> Optional[str]:
    """The person the requester picked for the manager level, if any."""
    if not request_id or level != "dept_manager":
        return None
    return await _scalar(db, "SELECT selected_approver FROM purchase_requests WHERE id = CAST(:r AS uuid)",
                         {"r": request_id})


async def users_with_roles(db: AsyncSession, roles: list[str]) -> list[str]:
    return await _column(db, "SELECT email FROM auth_users WHERE role = ANY(:roles) AND is_active ORDER BY email",
                         {"roles": roles})


async def signer_for_contract(db: AsyncSession, contract_id: Optional[str]) -> Optional[str]:
    """Whoever the contract was last sent to for signature."""
    if not contract_id:
        return None
    return await _scalar(db, """
        SELECT payload->>'signer_email' FROM audit_log
        WHERE entity_id = CAST(:c AS uuid) AND action = 'sent_for_signature'
        ORDER BY created_at DESC LIMIT 1
    """, {"c": contract_id})


async def approval_chain(db: AsyncSession, request_id: Optional[str]) -> tuple[list[str], Optional[float]]:
    """(approval levels in order, amount) of a purchase request."""
    if not request_id:
        return [], None
    try:
        async with db.begin_nested():
            row = (await db.execute(_text(
                "SELECT approval_chain, amount FROM purchase_requests WHERE id = CAST(:r AS uuid)"
            ), {"r": request_id})).first()
    except Exception as e:
        logger.warning(f"approval_chain({request_id}) lookup failed: {e}")
        return [], None
    if row is None:
        return [], None
    return list(row.approval_chain or []), float(row.amount) if row.amount is not None else None


# Who a reminder.due goes to, by its recipient_role (shared/reminders.py).
_REMINDER_ROLES = {"finance": ["finance"], "reviewer": ["finance"], "approver": ["approver"]}


async def reminder_recipients(db: AsyncSession, payload: dict) -> list[str]:
    role = payload.get("recipient_role") or ""
    if role == "signer":
        signer = await signer_for_contract(db, payload.get("entity_id"))
        return [signer] if signer else await users_with_roles(db, ["finance", "admin"])
    picked = (await selected_approver(db, payload.get("entity_id"), role)
              if payload.get("entity_type") == "purchase_request" else None)
    if picked:
        return [picked]
    people = await approvers_for_level(db, role)  # an approval level (dept_manager, finance_head)
    if not people and role in _REMINDER_ROLES:
        people = await users_with_roles(db, _REMINDER_ROLES[role])
    return people or [as_email(role) if role else default_recipient()]


async def vendor_for_contract(db: AsyncSession, contract_id: Optional[str]) -> Optional[str]:
    if not contract_id:
        return None
    return await _scalar(db, "SELECT vendor_id::text FROM contracts WHERE id = CAST(:c AS uuid)", {"c": contract_id})


async def vendor_for_request(db: AsyncSession, request_id: Optional[str]) -> Optional[str]:
    if not request_id:
        return None
    return await _scalar(db, "SELECT vendor_id::text FROM purchase_requests WHERE id = CAST(:r AS uuid)", {"r": request_id})
