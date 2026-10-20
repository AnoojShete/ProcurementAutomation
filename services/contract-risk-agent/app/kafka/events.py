"""Event envelope + payload builders, matching shared/schemas/events.md
exactly. This is what the schema tests in tests/test_event_schemas.py
guard against drifting."""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict


from shared.logging.context import CorrelationContext

def build_event(event_type: str, source_service: str, payload: dict, correlation_id: Optional[str] = None, schema_version: Optional[int] = None) -> dict:
    corr_id = correlation_id or CorrelationContext.get() or str(uuid.uuid4())
    version = schema_version if schema_version is not None else (2 if event_type == "risk.score.updated" else 1)
    return {
        "event_id": str(uuid.uuid4()),
        "correlation_id": corr_id,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_service": source_service,
        "schema_version": version,
        "payload": payload,
    }


def _iso(value) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value is not None else None)


def build_contract_generated_payload(
    contract_id, purchase_request_id, vendor_id, template_used, version, status, generated_at,
    model_used: Optional[str] = None, fallback_triggered: bool = False
) -> dict:
    return {
        "contract_id": str(contract_id),
        "purchase_request_id": str(purchase_request_id) if purchase_request_id else None,
        "vendor_id": str(vendor_id) if vendor_id else None,
        "template_used": template_used,
        "version": version,
        "status": status,
        "generated_at": _iso(generated_at),
        "model_used": model_used,
        "fallback_triggered": fallback_triggered,
    }


def build_contract_signed_payload(contract_id, signed_at, signed_by, esign_provider_ref) -> dict:
    return {
        "contract_id": str(contract_id),
        "signed_at": _iso(signed_at),
        "signed_by": signed_by,
        "esign_provider_ref": esign_provider_ref,
    }


def build_contract_renewal_due_payload(
    contract_id, vendor_id, renewal_type, notice_period_days, contract_end_date, days_remaining, alert_level,
    notice_deadline=None,
) -> dict:
    return {
        "contract_id": str(contract_id),
        "vendor_id": str(vendor_id) if vendor_id else None,
        "renewal_type": renewal_type,
        "notice_period_days": notice_period_days,
        "contract_end_date": _iso(contract_end_date),
        "days_remaining": days_remaining,
        "alert_level": str(alert_level),
        # Last day to give notice (end date − notice period); the reminders count back from it.
        "notice_deadline": _iso(notice_deadline) if notice_deadline else None,
    }


def build_risk_score_updated_payload(
    vendor_id,
    risk_band,
    risk_score,
    top_factors: Optional[List[Dict]] = None,
    model_version: Optional[str] = None,
    scored_at: Optional[datetime] = None,
    total_points: Optional[int] = None,
    points_band: Optional[str] = None,
    final_band: Optional[str] = None,
    override_rule_ids: Optional[List[str]] = None,
    unassessed_potential_points: Optional[int] = None,
    worst_case_band: Optional[str] = None,
    ruleset_version: Optional[int] = None,
    is_provisional: bool = False,
    effective_tier: Optional[str] = None,
    previous_band: Optional[str] = None,
    band_changed: bool = False,
    trigger_type: Optional[str] = None,
    explanation_url: Optional[str] = None,
    rating_status: Optional[str] = None,
    applicable_max_points: Optional[int] = 100,
    due_diligence_potential_points: Optional[int] = 0,
    history_potential_points: Optional[int] = 0,
    points_is_lower_bound: bool = False,
    blocked_by: Optional[List[str]] = None,
    remediation_path: Optional[List[Dict]] = None,
) -> dict:
    payload = {
        "vendor_id": str(vendor_id),
        "risk_band": final_band or risk_band,
        "risk_score": float(risk_score) if risk_score is not None else None,
        "top_factors": top_factors or [],
        "model_version": model_version or f"ruleset_v{ruleset_version or 1}",
        "scored_at": _iso(scored_at),
        # Prompt 9B & 9C additive fields
        "total_points": total_points if total_points is not None else (int(round((risk_score or 0) * 100)) if risk_score is not None else None),
        "points_band": points_band or risk_band,
        "final_band": final_band or risk_band,
        "override_rule_ids": override_rule_ids or [],
        "unassessed_potential_points": unassessed_potential_points or 0,
        "worst_case_band": worst_case_band or points_band or risk_band,
        "ruleset_version": ruleset_version or 1,
        "is_provisional": is_provisional,
        "effective_tier": effective_tier or "standard",
        "previous_band": previous_band,
        "band_changed": band_changed,
        "trigger_type": trigger_type or "manual",
        "explanation_url": explanation_url or f"/app/vendors/{vendor_id}/risk",
        "rating_status": rating_status or ("provisional" if is_provisional else "assessed"),
        "applicable_max_points": applicable_max_points or 100,
        "due_diligence_potential_points": due_diligence_potential_points or 0,
        "history_potential_points": history_potential_points or 0,
        "points_is_lower_bound": points_is_lower_bound,
        "blocked_by": blocked_by or [],
        "remediation_path": remediation_path or [],
    }
    return payload


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
