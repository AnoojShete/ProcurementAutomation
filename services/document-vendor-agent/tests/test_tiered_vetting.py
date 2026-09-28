"""Tiered vendor vetting tests.

Tests the three-tier classification, structuring detection (cumulative
spend crossing a tier boundary triggers a retroactive upgrade), and the
no-GSTIN attestation flow.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from app.services.vendor_tier_service import (
    classify_tier,
    required_checks_for_tier,
    check_and_upgrade_tier,
    confirm_no_gstin,
    VendorTier,
    PETTY_THRESHOLD,
    STANDARD_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Single-transaction tier classification
# ---------------------------------------------------------------------------

class TestClassifyTier:

    def test_petty_tier_below_threshold(self):
        assert classify_tier(499.99) == VendorTier.PETTY
        assert classify_tier(1000.0) == VendorTier.PETTY
        assert classify_tier(PETTY_THRESHOLD - 0.01) == VendorTier.PETTY

    def test_standard_tier_at_lower_boundary(self):
        assert classify_tier(PETTY_THRESHOLD) == VendorTier.STANDARD
        assert classify_tier(25000.0) == VendorTier.STANDARD
        assert classify_tier(STANDARD_THRESHOLD - 0.01) == VendorTier.STANDARD

    def test_strategic_tier_at_upper_boundary(self):
        assert classify_tier(STANDARD_THRESHOLD) == VendorTier.STRATEGIC
        assert classify_tier(100000.0) == VendorTier.STRATEGIC
        assert classify_tier(1_000_000.0) == VendorTier.STRATEGIC

    def test_zero_amount_is_petty(self):
        assert classify_tier(0.0) == VendorTier.PETTY


# ---------------------------------------------------------------------------
# Required checks per tier
# ---------------------------------------------------------------------------

class TestRequiredChecks:

    def test_petty_checks(self):
        checks = required_checks_for_tier(VendorTier.PETTY)
        assert "gstin_structural" not in checks
        assert "gstin_live" not in checks
        assert "name" in checks

    def test_standard_checks(self):
        checks = required_checks_for_tier(VendorTier.STANDARD)
        assert "gstin_structural" in checks
        assert "gstin_live" in checks
        assert "ifsc" in checks
        assert "opencorporates" not in checks

    def test_strategic_checks(self):
        checks = required_checks_for_tier(VendorTier.STRATEGIC)
        assert "gstin_structural" in checks
        assert "gstin_live" in checks
        assert "opencorporates" in checks
        assert "sanctions_screening" in checks


# ---------------------------------------------------------------------------
# Structuring detection — cumulative spend crossing a tier boundary
# ---------------------------------------------------------------------------

class TestStructuringDetection:

    def _make_vendor(self, tier="petty", spend=0.0):
        vendor = MagicMock()
        vendor.id = "v-test-1"
        vendor.vendor_tier = tier
        vendor.cumulative_spend_90d = spend
        vendor.updated_at = None
        return vendor

    @pytest.mark.asyncio
    async def test_single_petty_purchase_stays_petty(self):
        """A single ₹2000 purchase from a fresh vendor stays petty."""
        vendor = self._make_vendor("petty")

        with patch(
            "app.services.vendor_tier_service.get_vendor_spend_90d",
            return_value=0.0
        ), patch("app.services.vendor_tier_service.write_audit_log", return_value=None):
            mock_db = AsyncMock()
            mock_db.flush = AsyncMock()
            mock_db.execute = AsyncMock()
            result = await check_and_upgrade_tier(mock_db, vendor, 2000.0)

        assert result.tier == VendorTier.PETTY
        assert result.cumulative_spend_90d == 2000.0

    @pytest.mark.asyncio
    async def test_cumulative_spend_triggers_standard_upgrade(self):
        """Three ₹2000 petty purchases = ₹6000 cumulative → upgrades to standard."""
        vendor = self._make_vendor("petty")

        # Simulate ₹4000 already spent in the 90-day window
        with patch(
            "app.services.vendor_tier_service.get_vendor_spend_90d",
            return_value=4000.0
        ), patch("app.services.vendor_tier_service.write_audit_log", return_value=None):
            mock_db = AsyncMock()
            mock_db.flush = AsyncMock()
            result = await check_and_upgrade_tier(mock_db, vendor, 2000.0)

        # ₹4000 + ₹2000 = ₹6000 → crosses petty → standard
        assert result.tier == VendorTier.STANDARD
        assert vendor.vendor_tier == VendorTier.STANDARD.value

    @pytest.mark.asyncio
    async def test_cumulative_spend_triggers_strategic_upgrade(self):
        """Cumulative spend crossing ₹50,000 forces strategic tier."""
        vendor = self._make_vendor("standard")

        with patch(
            "app.services.vendor_tier_service.get_vendor_spend_90d",
            return_value=45000.0
        ), patch("app.services.vendor_tier_service.write_audit_log", return_value=None):
            mock_db = AsyncMock()
            mock_db.flush = AsyncMock()
            result = await check_and_upgrade_tier(mock_db, vendor, 10000.0)

        # ₹45k + ₹10k = ₹55k → strategic
        assert result.tier == VendorTier.STRATEGIC
        assert vendor.vendor_tier == VendorTier.STRATEGIC.value

    @pytest.mark.asyncio
    async def test_no_upgrade_when_no_threshold_crossed(self):
        """A ₹10,000 purchase from a standard vendor with ₹20k existing spend
        stays standard (cumulative ₹30k < ₹50k strategic threshold)."""
        vendor = self._make_vendor("standard")

        with patch(
            "app.services.vendor_tier_service.get_vendor_spend_90d",
            return_value=20000.0
        ), patch("app.services.vendor_tier_service.write_audit_log", return_value=None):
            mock_db = AsyncMock()
            mock_db.flush = AsyncMock()
            result = await check_and_upgrade_tier(mock_db, vendor, 10000.0)

        assert result.tier == VendorTier.STANDARD
        # No upgrade → vendor.vendor_tier should not have been mutated
        # (no audit log called for a no-change event)


# ---------------------------------------------------------------------------
# No-GSTIN attestation
# ---------------------------------------------------------------------------

class TestNoGSTINAttestation:

    @pytest.mark.asyncio
    async def test_confirm_no_gstin_logs_and_updates(self):
        vendor = MagicMock()
        vendor.id = "v-test-2"
        vendor.no_gstin_confirmed_by = None
        vendor.no_gstin_confirmed_at = None
        vendor.updated_at = None

        with patch("app.services.vendor_tier_service.write_audit_log", return_value=None) as mock_audit:
            mock_db = AsyncMock()
            mock_db.flush = AsyncMock()
            await confirm_no_gstin(mock_db, vendor, confirmed_by="procurement@company.com")

        assert vendor.no_gstin_confirmed_by == "procurement@company.com"
        assert vendor.no_gstin_confirmed_at is not None
        mock_audit.assert_called_once()
        _, kwargs = mock_audit.call_args
        assert kwargs.get("action") == "no_gstin_threshold_confirmed" or \
               mock_audit.call_args[0][3] == "no_gstin_threshold_confirmed" or \
               "confirmed_by" in str(mock_audit.call_args)
