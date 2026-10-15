"""Signature reminders (FR-03): a contract waiting for signature longer
than the business rule contract.signature_reminder_days gets one
reminder.due. Runs every few minutes from the API process; the marker in
audit_log stops repeats."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from shared.reminders import is_due, remind_once

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 300


def signature_reminder_days() -> int:
    from shared.rules_engine import get_rule
    days = get_rule("contract.signature_reminder_days", fallback=3)
    return days if isinstance(days, int) and days > 0 else 3


async def sweep_signature_reminders(session_factory, producer, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    days = signature_reminder_days()
    sent = 0
    async with session_factory() as session:
        rows = (await session.execute(text(
            "SELECT c.id::text AS id, c.purchase_request_id::text AS request_id, "
            "COALESCE((SELECT min(a.created_at) FROM audit_log a WHERE a.entity_id = c.id "
            "AND a.action = 'sent_for_signature'), c.updated_at, c.generated_at) AS since "
            "FROM contracts c WHERE c.status = 'pending_signature'"
        ))).all()
        for r in rows:
            if r.since is None or not is_due(r.since, days * 24, now):
                continue
            if await remind_once(
                session, producer, kind="signature_waiting", entity_type="contract", entity_id=r.id,
                waiting_since=r.since, threshold=f"{days}d", recipient_role="signer",
                link=f"/app/contracts/{r.id}?action=sign", service="contract-risk-agent",
                detail=f"waiting for signature for more than {days} days",
            ):
                sent += 1
        await session.commit()
    if sent:
        logger.info(f"Signature reminders sent: {sent}")
    return sent


async def run_reminder_sweeps(session_factory, producer):
    while True:
        try:
            await sweep_signature_reminders(session_factory, producer)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Signature reminder sweep failed: {e}", exc_info=True)
        await asyncio.sleep(INTERVAL_SECONDS)
