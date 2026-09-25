"""Envelope helpers for events this service *consumes*.

notification-agent is a pure consumer per shared/schemas/events.md — no
topic lists it under "Published by" — so there's no producer/build_event
here (contrast with services/contract-risk-agent/app/kafka/events.py,
which is written from the producer side).

EVENT SCHEMA VERSIONING addendum: the envelope in shared/schemas/events.md
doesn't yet have a `schema_version` field. We add tolerant support for one
here — a top-level integer alongside event_id/event_type/timestamp/
source_service — defaulting to 1 if the producer hasn't added it yet, so
this consumer never breaks against not-yet-upgraded producers. Once every
service's producer is retrofitted to send `schema_version: 1` (tracked
separately, outside this service's folder), this stays backward compatible
by construction — we only ever read it with `.get(..., 1)`, never require it.
"""
from typing import Tuple


def parse_envelope(event: dict) -> Tuple[str, dict, int]:
    """Return (event_type, payload, schema_version) from a raw consumed
    Kafka message value, tolerating a missing `schema_version`."""
    event_type = event.get("event_type")
    payload = event.get("payload", {}) or {}
    schema_version = event.get("schema_version", 1)
    return event_type, payload, schema_version
import uuid
from datetime import datetime, timezone
from typing import Optional
from shared.logging.context import CorrelationContext

def build_event(event_type: str, source_service: str, payload: dict, correlation_id: Optional[str] = None) -> dict:
    corr_id = correlation_id or CorrelationContext.get() or str(uuid.uuid4())
    return {
        "event_id": str(uuid.uuid4()),
        "correlation_id": corr_id,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_service": source_service,
        "schema_version": 1,
        "payload": payload
    }
