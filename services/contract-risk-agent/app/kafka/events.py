"""Event envelope + payload builders, matching shared/schemas/events.md
exactly. This is what the schema tests in tests/test_event_schemas.py
guard against drifting."""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict


def build_event(event_type: str, source_service: str, payload: dict) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_service": source_service,
        "payload": payload,
    }


def _iso(value) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value is not None else None)


def build_contract_generated_payload(
    contract_id, purchase_request_id, vendor_id, template_used, version, status, generated_at
) -> dict:
    return {
        "contract_id": str(contract_id),
        "purchase_request_id": str(purchase_request_id) if purchase_request_id else None,
        "vendor_id": str(vendor_id) if vendor_id else None,
        "template_used": template_used,
        "version": version,
        "status": status,
        "generated_at": _iso(generated_at),
    }


def build_contract_signed_payload(contract_id, signed_at, signed_by, esign_provider_ref) -> dict:
    return {
        "contract_id": str(contract_id),
        "signed_at": _iso(signed_at),
        "signed_by": signed_by,
        "esign_provider_ref": esign_provider_ref,
    }


def build_contract_renewal_due_payload(
    contract_id, vendor_id, renewal_type, notice_period_days, contract_end_date, days_remaining, alert_level
) -> dict:
    return {
        "contract_id": str(contract_id),
        "vendor_id": str(vendor_id) if vendor_id else None,
        "renewal_type": renewal_type,
        "notice_period_days": notice_period_days,
        "contract_end_date": _iso(contract_end_date),
        "days_remaining": days_remaining,
        "alert_level": str(alert_level),
    }


def build_risk_score_updated_payload(
    vendor_id, risk_band, risk_score, top_factors: List[Dict], model_version, scored_at
) -> dict:
    return {
        "vendor_id": str(vendor_id),
        "risk_band": risk_band,
        "risk_score": float(risk_score),
        "top_factors": top_factors,
        "model_version": model_version,
        "scored_at": _iso(scored_at),
    }


def build_vendor_offboarded_payload(
    vendor_id, offboarded_by, offboarded_at, contracts_flagged: List[str], data_retention_flag: bool
) -> dict:
    return {
        "vendor_id": str(vendor_id),
        "offboarded_by": offboarded_by,
        "offboarded_at": _iso(offboarded_at),
        "contracts_flagged": [str(c) for c in contracts_flagged],
        "data_retention_flag": data_retention_flag,
    }


def build_notification_send_payload(
    recipient, channel, template_name, template_context, priority, related_entity_id
) -> dict:
    return {
        "recipient": recipient,
        "channel": channel,
        "template_name": template_name,
        "template_context": template_context,
        "priority": priority,
        "related_entity_id": str(related_entity_id) if related_entity_id else None,
    }
