"""Pending-action reminders owned by this service (FR-03):
  bank_verification_pending  a bank-detail change still waiting for the
                             second person after vendor.bank_verification_reminder_hours
  review_stale               a document in the review queue longer than
                             document.review_reminder_hours
One reminder.due per item and threshold (audit_log marker). Called from
the worker's periodic sweep."""
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from shared.reminders import is_due, remind_once

logger = logging.getLogger(__name__)


def _hours(rule: str, fallback: int) -> int:
    from shared.rules_engine import get_rule
    value = get_rule(rule, fallback=fallback)
    return value if isinstance(value, int) and value > 0 else fallback


async def sweep_reminders(session_factory, producer, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    bank_h = _hours("vendor.bank_verification_reminder_hours", 24)
    review_h = _hours("document.review_reminder_hours", 24)
    sent = {"bank_verification_pending": 0, "review_stale": 0}
    async with session_factory() as session:
        pending = (await session.execute(text(
            "SELECT id::text AS id, vendor_id::text AS vendor_id, COALESCE(submitted_at, created_at) AS since "
            "FROM vendor_payment_change_requests WHERE status = 'pending'"
        ))).all()
        for r in pending:
            if r.since is not None and is_due(r.since, bank_h, now) and await remind_once(
                session, producer, kind="bank_verification_pending", entity_type="vendor_payment_change",
                entity_id=r.id, waiting_since=r.since, threshold=f"{bank_h}h", recipient_role="finance",
                link=f"/app/vendors/{r.vendor_id}", service="document-vendor-agent",
                detail=f"bank-detail change waiting for a second person for more than {bank_h}h",
            ):
                sent["bank_verification_pending"] += 1
        stale = (await session.execute(text(
            "SELECT id::text AS id, COALESCE(updated_at, uploaded_at, created_at) AS since FROM documents "
            "WHERE needs_review AND status = 'classified' AND reviewed_at IS NULL"
        ))).all()
        for r in stale:
            if r.since is not None and is_due(r.since, review_h, now) and await remind_once(
                session, producer, kind="review_stale", entity_type="document", entity_id=r.id,
                waiting_since=r.since, threshold=f"{review_h}h", recipient_role="reviewer",
                link=f"/app/documents/{r.id}", service="document-vendor-agent",
                detail=f"in the review queue for more than {review_h}h",
            ):
                sent["review_stale"] += 1
        await session.commit()
    if any(sent.values()):
        logger.info(f"Reminders sent: {sent}")
    return sent
