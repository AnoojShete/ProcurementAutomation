"""Template rendering tests: for at least 3 event types, rendering the
documented payload shape produces non-empty subject/body, with the
correct data actually threaded through (not just non-empty boilerplate)."""
from app.services.templating import render_template


class TestTemplateRendering:
    def test_approval_requested_renders_with_correct_content(self):
        payload = {
            "request_id": "req-123",
            "request_type": "hardware",
            "requested_by": "alice@company.com",
            "department": "Engineering",
            "amount": 1500.00,
            "currency": "INR",
            "spend_tier": "manager",
            "approval_chain": ["manager-1", "finance-1"],
            "sla_deadline": "2026-09-01T00:00:00Z",
        }
        subject, body = render_template("approval_requested", payload)

        assert subject and subject.strip()
        assert body and body.strip()
        assert "hardware" in subject
        assert "Engineering" in subject
        assert "req-123" in body
        assert "alice@company.com" in body
        assert "1500.0" in body or "1500" in body

    def test_contract_signed_renders_with_correct_content(self):
        payload = {
            "contract_id": "c-789",
            "signed_at": "2026-08-20T10:00:00Z",
            "signed_by": "vendor-rep@acme.com",
            "esign_provider_ref": "ref-abc-999",
        }
        subject, body = render_template("contract_signed", payload)

        assert subject and subject.strip()
        assert body and body.strip()
        assert "c-789" in subject
        assert "vendor-rep@acme.com" in body
        assert "ref-abc-999" in body

    def test_risk_score_updated_renders_with_correct_content_and_high_risk_flag(self):
        payload = {
            "vendor_id": "v-42",
            "risk_band": "High",
            "risk_score": 0.91,
            "top_factors": [
                {"feature": "breach_disclosure_count", "contribution": 0.5},
                {"feature": "financial_stability_score", "contribution": 0.3},
            ],
            "model_version": "v2",
            "scored_at": "2026-08-24T00:00:00Z",
        }
        subject, body = render_template("risk_score_updated", payload)

        assert subject and subject.strip()
        assert body and body.strip()
        assert "v-42" in subject
        assert "High" in subject
        assert "breach_disclosure_count" in body
        # High band gets an extra escalation line in the body.
        assert "HIGH RISK" in body

    def test_license_usage_updated_low_utilisation_flags_alert(self):
        payload = {
            "license_id": "lic-1",
            "vendor_id": "v-1",
            "app_name": "Slack",
            "total_seats": 100,
            "active_seats_30d": 10,
            "active_seats_60d": 15,
            "active_seats_90d": 20,
            "utilisation_score": 0.10,
            "period_end": "2026-12-31",
        }
        subject, body = render_template("license_usage_updated", payload)

        assert "Slack" in subject
        assert "LOW-UTILISATION" in body

    def test_contract_renewal_due_renders(self):
        payload = {
            "contract_id": "c-1",
            "vendor_id": "v-1",
            "renewal_type": "auto",
            "notice_period_days": 60,
            "contract_end_date": "2027-01-01",
            "days_remaining": 15,
            "alert_level": "15",
        }
        subject, body = render_template("contract_renewal_due", payload)
        assert "c-1" in subject
        assert "15" in subject

    def test_missing_required_field_raises_instead_of_rendering_blank(self):
        """Jinja StrictUndefined means a payload missing a documented field
        fails loudly at render time rather than silently producing a
        blank/garbled email — this is what makes rendering itself act as a
        schema guard."""
        import pytest
        from jinja2 import UndefinedError

        incomplete_payload = {"request_id": "req-1"}  # missing everything else
        with pytest.raises(UndefinedError):
            render_template("approval_requested", incomplete_payload)
