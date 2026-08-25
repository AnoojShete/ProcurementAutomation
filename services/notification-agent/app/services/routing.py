"""Pure digest-vs-urgent routing decision.

`notification.send` (shared/schemas/events.md) carries an explicit
`priority` field (`urgent` | `digest`) — that's authoritative when present.
Every other event type this service consumes has no such field, so we
derive a sensible default per event type/payload here. Kept as a pure
function (no I/O) so it's trivially unit-testable.
"""
from typing import Optional

from app.config import urgent_risk_bands, urgent_renewal_alert_levels

URGENT = "urgent"
DIGEST = "digest"

# Event types that are always time-sensitive enough to send immediately.
_ALWAYS_URGENT = {
    "approval.requested",
    "approval.decided",
    "contract.generated",
    "contract.signed",
    "vendor.offboarded",
}

# Event types that are inherently routine/informational and safe to batch.
_ALWAYS_DIGEST = {
    "license.usage.updated",
    "document.classified",
}


def decide_priority(event_type: str, payload: Optional[dict] = None) -> str:
    """Return "urgent" or "digest" for a given consumed event.

    payload is used for the event types whose urgency depends on a field
    value rather than the event type alone (risk band, renewal alert
    level, or the explicit `priority` on notification.send).
    """
    payload = payload or {}

    if event_type == "notification.send":
        # Authoritative field on this topic. Unknown/missing values fall
        # back to "digest" — the safer default (never spam) — mirroring
        # the schema_version backward-tolerance convention: don't require
        # a field strictly, degrade gracefully if it's absent/unexpected.
        priority = payload.get("priority")
        return URGENT if priority == URGENT else DIGEST

    if event_type == "risk.score.updated":
        band = payload.get("risk_band")
        return URGENT if band in urgent_risk_bands() else DIGEST

    if event_type == "contract.renewal.due":
        alert_level = str(payload.get("alert_level", ""))
        return URGENT if alert_level in urgent_renewal_alert_levels() else DIGEST

    if event_type in _ALWAYS_URGENT:
        return URGENT

    if event_type in _ALWAYS_DIGEST:
        return DIGEST

    # Unknown event type: default to digest so a mis-routed/unexpected
    # message can never flood inboxes with an immediate send.
    return DIGEST
