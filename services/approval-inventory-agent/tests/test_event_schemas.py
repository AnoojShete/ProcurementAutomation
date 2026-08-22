import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.kafka.events import (
    build_event,
    build_approval_requested_payload,
    build_approval_decided_payload,
    build_license_usage_updated_payload,
)
from datetime import datetime, timezone

class TestEventSchemas:
    """Verify that all published events match the shared contract in
    shared/schemas/events.md exactly.
    
    This test prevents integration breakage when other services
    consume our events.
    """
    
    def test_event_envelope_structure(self):
        """Event envelope must have exactly: event_id, event_type, timestamp, source_service, payload."""
        event = build_event("approval.requested", "approval-inventory-agent", {"test": True})
        
        required_keys = {"event_id", "event_type", "timestamp", "source_service", "payload"}
        assert set(event.keys()) == required_keys
        assert event["event_type"] == "approval.requested"
        assert event["source_service"] == "approval-inventory-agent"
        assert isinstance(event["payload"], dict)
    
    def test_approval_requested_payload_keys(self):
        """approval.requested payload must have exact keys per shared schema."""
        payload = build_approval_requested_payload(
            request_id="test-uuid",
            request_type="hardware",
            requested_by="john@company.com",
            department="Engineering",
            amount=5000.0,
            currency="INR",
            spend_tier="manager",
            approval_chain=["dept_manager"],
            sla_deadline=datetime(2026, 8, 24, 10, 0, 0, tzinfo=timezone.utc)
        )
        
        required_keys = {
            "request_id", "request_type", "requested_by", "department",
            "amount", "currency", "spend_tier", "approval_chain", "sla_deadline"
        }
        assert set(payload.keys()) == required_keys
        assert payload["request_type"] in ("hardware", "license", "saas", "reclaim")
        assert isinstance(payload["amount"], (int, float))
        assert isinstance(payload["approval_chain"], list)
    
    def test_approval_decided_payload_keys(self):
        """approval.decided payload must have exact keys per shared schema."""
        payload = build_approval_decided_payload(
            request_id="test-uuid",
            decision="approved",
            decided_by="manager@company.com",
            decision_level="level_1_dept_manager",
            escalated=False,
            decided_at=datetime.now(timezone.utc),
            comments="Approved for Q3 budget"
        )
        
        required_keys = {
            "request_id", "decision", "decided_by", "decision_level",
            "escalated", "decided_at", "comments"
        }
        assert set(payload.keys()) == required_keys
        assert payload["decision"] in ("approved", "rejected")
        assert isinstance(payload["escalated"], bool)
    
    def test_license_usage_updated_payload_keys(self):
        """license.usage.updated payload must have exact keys per shared schema."""
        payload = build_license_usage_updated_payload(
            license_id="test-license-uuid",
            vendor_id="test-vendor-uuid",
            app_name="Microsoft 365 E3",
            total_seats=500,
            active_seats_30d=350,
            active_seats_60d=400,
            active_seats_90d=420,
            utilisation_score=0.7,
            period_end=datetime(2027, 1, 1).date()
        )
        
        required_keys = {
            "license_id", "vendor_id", "app_name", "total_seats",
            "active_seats_30d", "active_seats_60d", "active_seats_90d",
            "utilisation_score", "period_end"
        }
        assert set(payload.keys()) == required_keys
        assert isinstance(payload["total_seats"], int)
        assert 0 <= payload["utilisation_score"] <= 1
    
    def test_approval_decided_nullable_comments(self):
        """Comments field should accept None per the schema."""
        payload = build_approval_decided_payload(
            request_id="test-uuid",
            decision="rejected",
            decided_by="finance@company.com",
            decision_level="level_2_finance_head",
            escalated=True,
            decided_at=datetime.now(timezone.utc),
            comments=None
        )
        assert payload["comments"] is None
    
    def test_event_timestamp_is_iso8601(self):
        """All timestamps must be ISO-8601 UTC."""
        event = build_event("test.event", "test-service", {})
        # Should not raise
        datetime.fromisoformat(event["timestamp"])
    
    def test_full_event_with_approval_requested(self):
        """Full event (envelope + payload) for approval.requested."""
        payload = build_approval_requested_payload(
            request_id="abc-123",
            request_type="saas",
            requested_by="user@company.com",
            department="Marketing",
            amount=2500.0,
            currency="INR",
            spend_tier="manager",
            approval_chain=["dept_manager"],
            sla_deadline=datetime(2026, 8, 25, tzinfo=timezone.utc)
        )
        event = build_event("approval.requested", "approval-inventory-agent", payload)
        
        assert event["event_type"] == "approval.requested"
        assert event["source_service"] == "approval-inventory-agent"
        assert event["payload"]["request_type"] == "saas"
        assert event["payload"]["spend_tier"] == "manager"
