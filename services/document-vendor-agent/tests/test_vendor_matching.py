from app.services.vendor_matching import normalize_vendor_name


class TestVendorNameNormalization:
    def test_strips_corporate_suffix(self):
        assert normalize_vendor_name("Acme Corp, Inc.") == normalize_vendor_name("ACME CORP INC")

    def test_case_and_punctuation_insensitive(self):
        assert normalize_vendor_name("Acme IT Supplies, Inc.") == normalize_vendor_name("acme it supplies inc")

    def test_strips_multi_word_suffix(self):
        result = normalize_vendor_name("Beta Traders Private Limited")
        assert "private" not in result and "limited" not in result
        assert result == "beta traders"

    def test_collapses_whitespace(self):
        assert normalize_vendor_name("Acme    IT   Supplies") == "acme it supplies"

    def test_empty_input(self):
        assert normalize_vendor_name("") == ""
        assert normalize_vendor_name(None) == ""

    def test_distinct_vendors_stay_distinct(self):
        assert normalize_vendor_name("Acme Corp") != normalize_vendor_name("Globex Corp")


class TestPaymentDualControl:
    """Dual-control: the user who submits a payment-detail change cannot
    also verify it. SameSubmitterError must be raised synchronously."""

    def test_same_submitter_cannot_verify(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from app.services.vendor_payment_service import verify_payment_change, SameSubmitterError

        change = MagicMock()
        change.submitted_by = "alice@company.com"
        change.id = "change-1"
        change.vendor_id = "vendor-1"
        change.status = "pending"

        vendor = MagicMock()
        vendor.id = "vendor-1"

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))))

        async def _run():
            await verify_payment_change(
                mock_db, change, vendor,
                verified_by="alice@company.com",  # same as submitted_by!
                channel="phone",
                approve=True,
            )

        with pytest.raises(SameSubmitterError):
            asyncio.get_event_loop().run_until_complete(_run())

    def test_different_verifier_succeeds(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.services.vendor_payment_service import verify_payment_change

        change = MagicMock()
        change.submitted_by = "alice@company.com"
        change.id = "change-1"
        change.vendor_id = "vendor-1"
        change.new_bank_account_number = "123456"
        change.new_routing_code = "HDFC0001"
        change.new_beneficiary_name = "Alice"

        vendor = MagicMock()
        vendor.id = "vendor-1"

        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None  # no other pending changes
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.vendor_payment_service.write_audit_log", return_value=None):
            async def _run():
                return await verify_payment_change(
                    mock_db, change, vendor,
                    verified_by="bob@company.com",  # different user — OK
                    channel="phone-call",
                    approve=True,
                )
            result = asyncio.get_event_loop().run_until_complete(_run())

        assert result is change
        assert change.verified_by == "bob@company.com"


import pytest
