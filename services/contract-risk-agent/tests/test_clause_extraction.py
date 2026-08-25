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
