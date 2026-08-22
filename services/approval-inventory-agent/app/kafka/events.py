import uuid
from datetime import datetime, timezone

def build_event(event_type: str, source_service: str, payload: dict) -> dict:
    """Build a Kafka event envelope per the shared contract."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_service": source_service,
        "payload": payload
    }

def build_approval_requested_payload(
    request_id, request_type, requested_by, department,
    amount, currency, spend_tier, approval_chain, sla_deadline
) -> dict:
    """Build payload for approval.requested event."""
    return {
        "request_id": str(request_id),
        "request_type": request_type,
        "requested_by": requested_by,
        "department": department,
        "amount": float(amount),
        "currency": currency,
        "spend_tier": spend_tier,
        "approval_chain": approval_chain,
        "sla_deadline": sla_deadline.isoformat() if hasattr(sla_deadline, 'isoformat') else str(sla_deadline)
    }

def build_approval_decided_payload(
    request_id, decision, decided_by, decision_level,
    escalated, decided_at, comments=None
) -> dict:
    """Build payload for approval.decided event."""
    return {
        "request_id": str(request_id),
        "decision": decision,
        "decided_by": decided_by,
        "decision_level": decision_level,
        "escalated": escalated,
        "decided_at": decided_at.isoformat() if hasattr(decided_at, 'isoformat') else str(decided_at),
        "comments": comments
    }

def build_license_usage_updated_payload(
    license_id, vendor_id, app_name, total_seats,
    active_seats_30d, active_seats_60d, active_seats_90d,
    utilisation_score, period_end
) -> dict:
    """Build payload for license.usage.updated event."""
    return {
        "license_id": str(license_id),
        "vendor_id": str(vendor_id),
        "app_name": app_name,
        "total_seats": total_seats,
        "active_seats_30d": active_seats_30d,
        "active_seats_60d": active_seats_60d,
        "active_seats_90d": active_seats_90d,
        "utilisation_score": float(utilisation_score),
        "period_end": period_end.isoformat() if hasattr(period_end, 'isoformat') else str(period_end)
    }
