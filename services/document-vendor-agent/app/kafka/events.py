"""Event envelope + payload builders, matching shared/schemas/events.md
exactly. This is what the schema tests in tests/test_event_schemas.py
guard against drifting."""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


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


def build_document_ingested_payload(document_id, uploaded_by, file_type, minio_path, uploaded_at) -> dict:
    return {
        "document_id": str(document_id),
        "uploaded_by": uploaded_by,
        "file_type": file_type,
        "minio_path": minio_path,
        "uploaded_at": _iso(uploaded_at),
    }


def build_document_classified_payload(
    document_id, document_type, vendor_name_raw, extracted_fields: Dict[str, Any],
    confidence_scores: Dict[str, Any], overall_confidence: float, needs_review: bool
) -> dict:
    return {
        "document_id": str(document_id),
        "document_type": document_type,
        "vendor_name_raw": vendor_name_raw,
        "extracted_fields": extracted_fields,
        "confidence_scores": confidence_scores,
        "overall_confidence": float(overall_confidence) if overall_confidence is not None else None,
        "needs_review": bool(needs_review),
    }


def build_vendor_matched_payload(document_id, vendor_id, vendor_name_normalized, match_type, match_confidence) -> dict:
    return {
        "document_id": str(document_id),
        "vendor_id": str(vendor_id),
        "vendor_name_normalized": vendor_name_normalized,
        "match_type": match_type,
        "match_confidence": float(match_confidence),
    }


def build_vendor_payment_details_flagged_payload(
    vendor_id, change_request_id, submitted_by, source, fields_changed: List[str], flagged_at
) -> dict:
    """Payload for the new `vendor.payment_details_flagged` topic added by
    this service (see shared/kafka-topics.yaml / shared/schemas/events.md —
    appended as the one explicit exception to "don't touch shared files").
    Deliberately does NOT carry the raw bank account/routing values — just
    that a change happened, who submitted it, and which fields, so the
    Kafka bus never broadcasts sensitive payment data."""
    return {
        "vendor_id": str(vendor_id),
        "change_request_id": str(change_request_id),
        "submitted_by": submitted_by,
        "source": source,
        "fields_changed": list(fields_changed),
        "flagged_at": _iso(flagged_at),
    }
