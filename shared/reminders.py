"""reminder.due — one event for "someone has been waiting on you" (FR-03).

Published by the service that owns the item:
  approval_sla               approval-inventory-agent (approval workflow timers)
  signature_waiting          contract-risk-agent (sweep)
  bank_verification_pending  document-vendor-agent (sweep)
  review_stale               document-vendor-agent (sweep)

notification-agent turns it into an email (templates are Anooj's). Sweeps
remind each item once per threshold; the audit_log row written with the
event is what stops a repeat after a restart.
"""
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

TOPIC_REMINDER_DUE = "reminder.due"
KINDS = ("approval_sla", "signature_waiting", "bank_verification_pending", "review_stale")
MARKER_ACTION = "reminder_sent"


def build_reminder_due_payload(
    kind: str, entity_type: str, entity_id: str, waiting_since: datetime, threshold: str,
    recipient_role: str, link: str, detail: Optional[str] = None,
) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown reminder kind {kind!r}")
    now = datetime.now(timezone.utc)
    since = waiting_since if waiting_since.tzinfo else waiting_since.replace(tzinfo=timezone.utc)
    return {
        "kind": kind,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "waiting_since": since.isoformat(),
        "waiting_hours": round((now - since).total_seconds() / 3600, 1),
        "threshold": threshold,          # e.g. "50%" of the SLA, or "72h"
        "recipient_role": recipient_role,  # approver | finance | signer | reviewer
        "link": link,                    # path in the app, e.g. /app/requests/<id>
        "detail": detail,
    }


async def already_reminded(session, kind: str, entity_id: str, threshold: str) -> bool:
    row = (await session.execute(text(
        "SELECT 1 FROM audit_log WHERE action = :a AND entity_id = CAST(:e AS uuid) "
        "AND payload->>'kind' = :k AND payload->>'threshold' = :t LIMIT 1"
    ), {"a": MARKER_ACTION, "e": str(entity_id), "k": kind, "t": threshold})).first()
    return row is not None


async def mark_reminded(session, kind: str, entity_type: str, entity_id: str, threshold: str, service: str) -> None:
    """Write the marker in the caller's transaction (with the outbox row)."""
    await session.execute(text(
        "INSERT INTO audit_log (id, entity_id, entity_type, action, payload, performed_by, created_at) "
        "VALUES (gen_random_uuid(), CAST(:e AS uuid), :et, :a, CAST(:p AS jsonb), :by, now())"
    ), {"e": str(entity_id), "et": entity_type, "a": MARKER_ACTION, "by": service,
        "p": json.dumps({"kind": kind, "threshold": threshold})})


def is_due(waiting_since: datetime, threshold_hours: float, now: datetime) -> bool:
    since = waiting_since if waiting_since.tzinfo else waiting_since.replace(tzinfo=timezone.utc)
    return (now - since).total_seconds() >= threshold_hours * 3600


async def remind_once(session, producer, *, kind: str, entity_type: str, entity_id: str, waiting_since: datetime,
                      threshold: str, recipient_role: str, link: str, service: str,
                      detail: Optional[str] = None) -> bool:
    """Publish reminder.due through the outbox and write the marker, once per
    (kind, item, threshold). The caller commits. Returns whether it was sent."""
    from shared.eventing import staged
    if await already_reminded(session, kind, entity_id, threshold):
        return False
    outbox = staged(producer, session)
    if outbox is None:
        return False
    await outbox.publish_reminder_due(
        kind=kind, entity_type=entity_type, entity_id=entity_id, waiting_since=waiting_since,
        threshold=threshold, recipient_role=recipient_role, link=link, detail=detail,
    )
    await mark_reminded(session, kind, entity_type, entity_id, threshold, service)
    return True
