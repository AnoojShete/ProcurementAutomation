"""Tests for the pure digest-vs-urgent routing decision
(app/services/routing.py) — no I/O, so these run without a DB/Kafka."""
from app.services.routing import decide_priority, URGENT, DIGEST


class TestNotificationSendPriorityField:
    """notification.send carries an explicit `priority` field — that's
    authoritative over any event-type default."""

    def test_explicit_urgent(self):
        assert decide_priority("notification.send", {"priority": "urgent"}) == URGENT

    def test_explicit_digest(self):
        assert decide_priority("notification.send", {"priority": "digest"}) == DIGEST

    def test_missing_priority_defaults_to_digest_not_urgent(self):
        # Safe default: never spam on a malformed/legacy event.
        assert decide_priority("notification.send", {}) == DIGEST

    def test_unrecognized_priority_value_defaults_to_digest(self):
        assert decide_priority("notification.send", {"priority": "whenever"}) == DIGEST


class TestAlwaysUrgentEventTypes:
    def test_approval_requested_is_always_urgent(self):
        assert decide_priority("approval.requested", {}) == URGENT

    def test_approval_decided_is_always_urgent(self):
        assert decide_priority("approval.decided", {"escalated": True}) == URGENT

    def test_contract_generated_is_always_urgent(self):
        assert decide_priority("contract.generated", {}) == URGENT

    def test_contract_signed_is_always_urgent(self):
        assert decide_priority("contract.signed", {}) == URGENT

    def test_vendor_offboarded_is_always_urgent(self):
        assert decide_priority("vendor.offboarded", {}) == URGENT


class TestAlwaysDigestEventTypes:
    def test_license_usage_updated_is_always_digest(self):
        assert decide_priority("license.usage.updated", {"utilisation_score": 0.01}) == DIGEST

    def test_document_classified_is_always_digest(self):
        assert decide_priority("document.classified", {"needs_review": True}) == DIGEST


class TestRiskScoreUpdatedBandDependentRouting:
    def test_high_band_is_urgent(self):
        assert decide_priority("risk.score.updated", {"risk_band": "High"}) == URGENT

    def test_medium_band_is_digest(self):
        assert decide_priority("risk.score.updated", {"risk_band": "Medium"}) == DIGEST

    def test_low_band_is_digest(self):
        assert decide_priority("risk.score.updated", {"risk_band": "Low"}) == DIGEST


class TestContractRenewalDueAlertLevelDependentRouting:
    def test_alert_level_15_is_urgent(self):
        assert decide_priority("contract.renewal.due", {"alert_level": "15"}) == URGENT

    def test_alert_level_15_as_int_is_urgent(self):
        # events.md documents alert_level as `60`|`30`|`15` without pinning
        # a JSON type; tolerate either.
        assert decide_priority("contract.renewal.due", {"alert_level": 15}) == URGENT

    def test_alert_level_60_is_digest(self):
        assert decide_priority("contract.renewal.due", {"alert_level": "60"}) == DIGEST

    def test_alert_level_30_is_digest(self):
        assert decide_priority("contract.renewal.due", {"alert_level": "30"}) == DIGEST


class TestUnknownEventTypeDefaultsToDigest:
    def test_unknown_event_type_is_digest(self):
        assert decide_priority("some.future.event", {}) == DIGEST
