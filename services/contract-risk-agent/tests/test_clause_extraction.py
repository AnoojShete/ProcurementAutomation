from datetime import date

from app.services.clause_extraction import extract_clauses


class TestClauseExtraction:
    def test_auto_renew_with_notice_period(self):
        text = """
        SAAS SUBSCRIPTION AGREEMENT
        This subscription shall renew automatically for successive 12-month
        terms unless either party gives written notice of non-renewal at
        least 60 days prior to the contract end date.
        Contract end date: 2027-03-15
        """
        result = extract_clauses(text)
        assert result["renewal_type"] == "auto"
        assert result["notice_period_days"] == 60
        assert result["contract_end_date"] == date(2027, 3, 15)

    def test_manual_renewal_no_auto_renew(self):
        text = """
        HARDWARE PURCHASE AGREEMENT
        This agreement does not automatically renew; renewal requires
        written renewal executed by both parties at least 30 days notice
        before the contract end date.
        Expiration date: January 5, 2027
        """
        result = extract_clauses(text)
        assert result["renewal_type"] == "manual"
        assert result["notice_period_days"] == 30
        assert result["contract_end_date"] == date(2027, 1, 5)

    def test_professional_services_manual_renewal(self):
        text = """
        PROFESSIONAL SERVICES AGREEMENT
        This engagement does not automatically renew (manual renew); any
        extension requires written renewal at least 15 days notice before
        the contract end date.
        Contract End Date: 2026-12-01
        """
        result = extract_clauses(text)
        assert result["renewal_type"] == "manual"
        assert result["notice_period_days"] == 15
        assert result["contract_end_date"] == date(2026, 12, 1)

    def test_missing_clauses_return_none(self):
        text = "This is a contract with no structured renewal information at all."
        result = extract_clauses(text)
        assert result["renewal_type"] is None
        assert result["notice_period_days"] is None
        assert result["contract_end_date"] is None


import pytest  # noqa: E402
from jinja2 import Environment, FileSystemLoader  # noqa: E402


@pytest.mark.parametrize("template,renewal", [
    ("saas_subscription", "auto"), ("hardware_purchase", "manual"), ("professional_services", "manual")])
@pytest.mark.parametrize("notice", [7, 15, 45, 90])
def test_rules_read_our_own_templates(template, renewal, notice):
    """The rules are the fallback when the model isn't downloaded, so they
    must read every contract we generate — including where the template
    wraps "N days" and "notice" onto separate lines."""
    import os
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "..", "app", "templates")))
    text = env.get_template(f"{template}.j2").render(
        contract_id="c", generated_at="2026-10-16", vendor_name="Acme", purchase_request_id="p", department="IT",
        items=[], amount=100, currency="INR", contract_end_date="2027-10-16", notice_period_days=notice)
    result = extract_clauses(text)
    assert result == {"renewal_type": renewal, "notice_period_days": notice, "contract_end_date": date(2027, 10, 16)}
