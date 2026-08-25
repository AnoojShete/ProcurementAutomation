"""Verify published events match shared/schemas/events.md exactly — this
is what prevents integration breakage when other services consume them."""
from datetime import datetime, timezone, date

from app.kafka.events import (
    build_event,
    build_contract_generated_payload,
    build_contract_signed_payload,
    build_contract_renewal_due_payload,
    build_risk_score_updated_payload,
    build_vendor_offboarded_payload,
)


class TestEventSchemas:
    def test_event_envelope_structure(self):
        event = build_event("contract.generated", "contract-risk-agent", {"test": True})
        assert set(event.keys()) == {"event_id", "event_type", "timestamp", "source_service", "payload"}
        assert event["source_service"] == "contract-risk-agent"

    def test_event_timestamp_is_iso8601(self):
        event = build_event("test.event", "contract-risk-agent", {})
        datetime.fromisoformat(event["timestamp"])

    def test_contract_generated_payload_keys(self):
        payload = build_contract_generated_payload(
            contract_id="c-1", purchase_request_id="pr-1", vendor_id="v-1",
            template_used="hardware_purchase", version=1, status="draft",
            generated_at=datetime.now(timezone.utc),
        )
        assert set(payload.keys()) == {
            "contract_id", "purchase_request_id", "vendor_id", "template_used",
            "version", "status", "generated_at",
        }
        assert payload["status"] in ("draft", "pending_signature")

    def test_contract_signed_payload_keys(self):
        payload = build_contract_signed_payload(
            contract_id="c-1", signed_at=datetime.now(timezone.utc),
            signed_by="approver@company.com", esign_provider_ref="ref-123",
        )
        assert set(payload.keys()) == {"contract_id", "signed_at", "signed_by", "esign_provider_ref"}

    def test_contract_renewal_due_payload_keys(self):
        payload = build_contract_renewal_due_payload(
            contract_id="c-1", vendor_id="v-1", renewal_type="auto",
            notice_period_days=60, contract_end_date=date(2027, 1, 1),
            days_remaining=60, alert_level=60,
        )
        assert set(payload.keys()) == {
            "contract_id", "vendor_id", "renewal_type", "notice_period_days",
            "contract_end_date", "days_remaining", "alert_level",
        }
        assert payload["alert_level"] in ("60", "30", "15")

    def test_risk_score_updated_payload_keys(self):
        payload = build_risk_score_updated_payload(
            vendor_id="v-1", risk_band="Low", risk_score=0.12,
            top_factors=[{"feature": "on_time_delivery_rate", "contribution": 0.4}],
            model_version="v1", scored_at=datetime.now(timezone.utc),
        )
        assert set(payload.keys()) == {
            "vendor_id", "risk_band", "risk_score", "top_factors", "model_version", "scored_at",
        }
        assert payload["risk_band"] in ("Low", "Medium", "High")
        assert 0 <= payload["risk_score"] <= 1

    def test_vendor_offboarded_payload_keys(self):
        payload = build_vendor_offboarded_payload(
            vendor_id="v-1", offboarded_by="admin@company.com",
            offboarded_at=datetime.now(timezone.utc), contracts_flagged=["c-1", "c-2"],
            data_retention_flag=True,
        )
        assert set(payload.keys()) == {
            "vendor_id", "offboarded_by", "offboarded_at", "contracts_flagged", "data_retention_flag",
        }
        assert isinstance(payload["contracts_flagged"], list)
