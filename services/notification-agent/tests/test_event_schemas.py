"""Schema test for a *consumer* (contrast with the producer-side exact-key
assertions in services/contract-risk-agent/tests/test_event_schemas.py):
for every one of the 10 topics naming notification-agent as a consumer in
shared/schemas/events.md's "Consumed by" column, build a sample event dict
using exactly the documented payload keys and verify our handler's field
extraction — i.e. rendering the template it maps to in
app/kafka/consumer.py — succeeds and produces the expected content.

This also covers the two topics the task brief's own list missed:
document.classified and vendor.offboarded both name notification-agent as
a consumer too.
"""
from datetime import datetime, timezone

from app.kafka.consumer import CONSUME_TOPICS, _HANDLERS
from app.kafka.events import parse_envelope
from app.services.templating import render_template, template_exists

# One sample payload per topic, using exactly the field names/types
# documented in shared/schemas/events.md.
SAMPLE_PAYLOADS = {
    "document.classified": {
        "document_id": "doc-1",
        "document_type": "invoice",
        "vendor_name_raw": "Acme Corp",
        "extracted_fields": {"line_items": [], "total": 100.0, "currency": "INR",
                              "document_number": "INV-1", "document_date": "2026-08-01"},
        "confidence_scores": {"total": 0.4},
        "overall_confidence": 0.4,
        "needs_review": True,
    },
    "license.usage.updated": {
        "license_id": "lic-1",
        "vendor_id": "v-1",
        "app_name": "Zoom",
        "total_seats": 50,
        "active_seats_30d": 5,
        "active_seats_60d": 8,
        "active_seats_90d": 12,
        "utilisation_score": 0.10,
        "period_end": "2026-12-31",
    },
    "approval.requested": {
        "request_id": "req-1",
        "request_type": "saas",
        "requested_by": "bob@company.com",
        "department": "Sales",
        "amount": 999.0,
        "currency": "INR",
        "spend_tier": "manager+finance",
        "approval_chain": ["mgr-1", "fin-1"],
        "sla_deadline": "2026-09-01T00:00:00Z",
    },
    "approval.decided": {
        "request_id": "req-1",
        "decision": "approved",
        "decided_by": "mgr-1",
        "decision_level": "manager",
        "escalated": False,
        "decided_at": "2026-08-24T00:00:00Z",
        "comments": None,
    },
    "contract.generated": {
        "contract_id": "c-1",
        "purchase_request_id": "req-1",
        "vendor_id": "v-1",
        "template_used": "saas_subscription",
        "version": 1,
        "status": "pending_signature",
        "generated_at": "2026-08-24T00:00:00Z",
    },
    "contract.signed": {
        "contract_id": "c-1",
        "signed_at": "2026-08-25T00:00:00Z",
        "signed_by": "vendor-rep@acme.com",
        "esign_provider_ref": "ref-1",
    },
    "contract.renewal.due": {
        "contract_id": "c-1",
        "vendor_id": "v-1",
        "renewal_type": "manual",
        "notice_period_days": 30,
        "contract_end_date": "2027-01-01",
        "days_remaining": 30,
        "alert_level": "30",
    },
    "risk.score.updated": {
        "vendor_id": "v-1",
        "risk_band": "Medium",
        "risk_score": 0.5,
        "top_factors": [{"feature": "on_time_delivery_rate", "contribution": 0.2}],
        "model_version": "v1",
        "scored_at": "2026-08-24T00:00:00Z",
    },
    "vendor.offboarded": {
        "vendor_id": "v-1",
        "offboarded_by": "admin@company.com",
        "offboarded_at": "2026-08-24T00:00:00Z",
        "contracts_flagged": ["c-1", "c-2"],
        "data_retention_flag": True,
    },
    "notification.send": {
        "recipient": "someone@company.com",
        "channel": "email",
        "template_name": "risk_score_updated",
        "template_context": {
            "vendor_id": "v-1", "risk_band": "Low", "risk_score": 0.1,
            "top_factors": [], "model_version": "v1", "scored_at": "2026-08-24T00:00:00Z",
        },
        "priority": "digest",
        "related_entity_id": "v-1",
    },
}

# Template each event type's handler renders, per app/kafka/consumer.py.
EXPECTED_TEMPLATE = {
    "document.classified": "document_classified",
    "license.usage.updated": "license_usage_updated",
    "approval.requested": "approval_requested",
    "approval.decided": "approval_decided",
    "contract.generated": "contract_generated",
    "contract.signed": "contract_signed",
    "contract.renewal.due": "contract_renewal_due",
    "risk.score.updated": "risk_score_updated",
    "vendor.offboarded": "vendor_offboarded",
    # notification.send doesn't map to one fixed template — its own
    # template_name field picks it (see test below).
}


class TestConsumedTopicsCoverage:
    def test_all_ten_documented_topics_are_consumed(self):
        """shared/schemas/events.md names notification-agent as a consumer
        on exactly these 10 topics (cross-checked row by row against the
        'Consumed by' column) — including document.classified and
        vendor.offboarded, which the task brief's own topic list omitted."""
        expected = {
            "document.classified", "license.usage.updated", "approval.requested",
            "approval.decided", "contract.generated", "contract.signed",
            "contract.renewal.due", "risk.score.updated", "vendor.offboarded",
            "notification.send",
        }
        assert set(CONSUME_TOPICS) == expected
        assert set(_HANDLERS.keys()) == expected

    def test_every_topic_has_a_sample_payload_in_this_test_file(self):
        assert set(SAMPLE_PAYLOADS.keys()) == set(CONSUME_TOPICS)


class TestHandlerFieldExtractionPerTopic:
    """For every non-generic topic, the handler's context is the raw
    payload rendered against a fixed template — so a correct extraction
    means rendering the documented payload shape succeeds (StrictUndefined
    would raise if a field name were wrong)."""

    def test_extraction_succeeds_for_every_fixed_template_topic(self):
        for event_type, template_name in EXPECTED_TEMPLATE.items():
            payload = SAMPLE_PAYLOADS[event_type]
            subject, body = render_template(template_name, payload)
            assert subject.strip(), f"{event_type}: empty subject"
            assert body.strip(), f"{event_type}: empty body"

    def test_document_classified_needs_review_field_present(self):
        payload = SAMPLE_PAYLOADS["document.classified"]
        assert "needs_review" in payload and payload["needs_review"] is True

    def test_approval_decided_escalated_flag_present(self):
        payload = SAMPLE_PAYLOADS["approval.decided"]
        assert "escalated" in payload
        subject, body = render_template("approval_decided", payload)
        assert "False" in body  # escalated: False rendered into the body


class TestNotificationSendGenericFallback:
    def test_recipient_and_priority_and_template_name_are_extracted(self):
        payload = SAMPLE_PAYLOADS["notification.send"]
        assert payload["recipient"] == "someone@company.com"
        assert payload["priority"] == "digest"
        assert payload["template_name"] == "risk_score_updated"

    def test_referenced_template_exists_and_renders_with_its_context(self):
        payload = SAMPLE_PAYLOADS["notification.send"]
        assert template_exists(payload["template_name"])
        subject, body = render_template(payload["template_name"], payload["template_context"])
        assert subject.strip() and body.strip()

    def test_unknown_template_name_falls_back_to_generic(self):
        assert template_exists("some_template_that_does_not_ship") is False
        subject, body = render_template(
            "generic_fallback",
            {"template_name": "some_template_that_does_not_ship", "context": {"foo": "bar"}},
        )
        assert "some_template_that_does_not_ship" in subject
        assert "foo" in body and "bar" in body


class TestEnvelopeSchemaVersionTolerance:
    """EVENT SCHEMA VERSIONING addendum: schema_version defaults to 1 when
    a producer hasn't been retrofitted with it yet, and is read tolerantly
    (never required) when present."""

    def test_envelope_without_schema_version_defaults_to_1(self):
        event = {
            "event_id": "e-1",
            "event_type": "approval.requested",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_service": "approval-inventory-agent",
            "payload": SAMPLE_PAYLOADS["approval.requested"],
        }
        event_type, payload, schema_version = parse_envelope(event)
        assert schema_version == 1
        assert event_type == "approval.requested"
        assert payload == SAMPLE_PAYLOADS["approval.requested"]

    def test_envelope_with_explicit_schema_version_is_read_through(self):
        event = {
            "event_id": "e-1",
            "event_type": "approval.requested",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_service": "approval-inventory-agent",
            "schema_version": 2,
            "payload": SAMPLE_PAYLOADS["approval.requested"],
        }
        _, _, schema_version = parse_envelope(event)
        assert schema_version == 2

    def test_missing_payload_key_defaults_to_empty_dict(self):
        event = {"event_type": "notification.send"}
        event_type, payload, schema_version = parse_envelope(event)
        assert payload == {}
        assert schema_version == 1
