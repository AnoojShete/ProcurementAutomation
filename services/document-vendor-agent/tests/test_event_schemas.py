"""Verify published events match shared/schemas/events.md exactly — this
is what prevents integration breakage when other services consume them."""
from datetime import datetime, timezone

from app.kafka.events import (
    build_event,
    build_document_ingested_payload,
    build_document_classified_payload,
    build_vendor_matched_payload,
    build_vendor_payment_details_flagged_payload,
)


class TestEventSchemas:
    def test_event_envelope_structure(self):
        event = build_event("document.ingested", "document-vendor-agent", {"test": True})
        assert set(event.keys()) == {"event_id", "event_type", "timestamp", "source_service", "payload"}
        assert event["source_service"] == "document-vendor-agent"

    def test_event_timestamp_is_iso8601(self):
        event = build_event("test.event", "document-vendor-agent", {})
        datetime.fromisoformat(event["timestamp"])

    def test_document_ingested_payload_keys(self):
        payload = build_document_ingested_payload(
            document_id="d-1", uploaded_by="jane@company.com", file_type="pdf",
            minio_path="documents/d-1.pdf", uploaded_at=datetime.now(timezone.utc),
        )
        assert set(payload.keys()) == {"document_id", "uploaded_by", "file_type", "minio_path", "uploaded_at"}
        assert payload["file_type"] in ("pdf", "image")

    def test_document_classified_payload_keys(self):
        payload = build_document_classified_payload(
            document_id="d-1", document_type="invoice", vendor_name_raw="Acme Corp",
            extracted_fields={"line_items": [], "total": 100.0, "currency": "INR",
                               "document_number": "INV-1", "document_date": "2026-01-01"},
            confidence_scores={"total": 0.9}, overall_confidence=0.9, needs_review=False,
        )
        assert set(payload.keys()) == {
            "document_id", "document_type", "vendor_name_raw", "extracted_fields",
            "confidence_scores", "overall_confidence", "needs_review",
        }
        assert payload["document_type"] in ("po", "invoice", "quote")
        assert 0 <= payload["overall_confidence"] <= 1

    def test_vendor_matched_payload_keys(self):
        payload = build_vendor_matched_payload(
            document_id="d-1", vendor_id="v-1", vendor_name_normalized="acme corp",
            match_type="existing", match_confidence=0.95,
        )
        assert set(payload.keys()) == {
            "document_id", "vendor_id", "vendor_name_normalized", "match_type", "match_confidence",
        }
        assert payload["match_type"] in ("existing", "new")

    def test_vendor_payment_details_flagged_payload_keys(self):
        payload = build_vendor_payment_details_flagged_payload(
            vendor_id="v-1", change_request_id="c-1", submitted_by="jane@company.com",
            source="portal", fields_changed=["bank_account_number"], flagged_at=datetime.now(timezone.utc),
        )
        assert set(payload.keys()) == {
            "vendor_id", "change_request_id", "submitted_by", "source", "fields_changed", "flagged_at",
        }
        # Never leaks the actual bank/routing values onto the bus — only
        # field NAMES, never the values that were submitted.
        assert payload["fields_changed"] == ["bank_account_number"]
        assert "000123456789" not in str(payload)
