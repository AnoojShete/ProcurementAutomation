"""Tests for GSTIN structural validation and live-mode gating.

All live API calls and live_mode checks are mocked — never burn free-tier
quota in automated tests. The offline checks (format + check-digit) are
exercised directly against known-good and known-bad GSTINs.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.gstin_service import (
    validate_gstin_format,
    validate_gstin_checkdigit,
    validate_gstin_offline,
    verify_gstin,
    GSTINStatus,
)


# ---------------------------------------------------------------------------
# Offline format validation
# ---------------------------------------------------------------------------

class TestGSTINFormatValidation:

    def test_valid_format_passes(self):
        # 29AABCT1332L1ZA — well-known test GSTIN (Karnataka, valid structure)
        assert validate_gstin_format("29AABCT1332L1ZA") is True

    def test_lowercase_also_accepted(self):
        # validate_gstin_format normalises to uppercase internally
        assert validate_gstin_format("29aabct1332l1za") is True

    def test_too_short_rejected(self):
        assert validate_gstin_format("29AABCT1332L1Z") is False  # 14 chars

    def test_too_long_rejected(self):
        assert validate_gstin_format("29AABCT1332L1ZAA") is False  # 16 chars

    def test_invalid_state_code_zero(self):
        # State code 00 is not a valid state code
        assert validate_gstin_format("00AABCT1332L1ZD") is False

    def test_invalid_state_code_38(self):
        # State codes only go up to 37
        assert validate_gstin_format("38AABCT1332L1ZD") is False

    def test_empty_string_rejected(self):
        assert validate_gstin_format("") is False

    def test_none_rejected(self):
        assert validate_gstin_format(None) is False  # type: ignore


# ---------------------------------------------------------------------------
# Check-digit algorithm
# ---------------------------------------------------------------------------

class TestGSTINCheckDigit:

    def test_known_valid_checkdigit(self):
        # 29AABCT1332L1ZA — the check digit 'D' is correct for this GSTIN
        assert validate_gstin_checkdigit("29AABCT1332L1ZA") is True

    def test_wrong_checkdigit_rejected(self):
        # Replace last char 'D' with 'X' — same format, wrong check digit
        assert validate_gstin_checkdigit("29AABCT1332L1ZX") is False

    def test_another_valid_gstin(self):
        # 27AAACR5055K1Z7 — Maharashtra, check digit '5'
        assert validate_gstin_checkdigit("27AAACR5055K1Z7") is True

    def test_short_input_rejected(self):
        assert validate_gstin_checkdigit("29AABCT") is False


# ---------------------------------------------------------------------------
# Combined offline validation
# ---------------------------------------------------------------------------

class TestGSTINOfflineValidation:

    def test_valid_gstin_passes_both_checks(self):
        ok, reason = validate_gstin_offline("29AABCT1332L1ZA")
        assert ok is True
        assert reason == ""

    def test_format_fail_short_circuits(self):
        """Should fail on format check before reaching check-digit."""
        ok, reason = validate_gstin_offline("INVALID")
        assert ok is False
        assert "format" in reason.lower() or "structure" in reason.lower() or "INVALID" in reason

    def test_checkdigit_fail_after_format_pass(self):
        ok, reason = validate_gstin_offline("29AABCT1332L1ZX")
        assert ok is False
        assert "check" in reason.lower() or "digit" in reason.lower()

    def test_empty_string(self):
        ok, reason = validate_gstin_offline("")
        assert ok is False


# ---------------------------------------------------------------------------
# Live-mode gating
# ---------------------------------------------------------------------------

class TestGSTINLiveModeGating:

    @pytest.mark.asyncio
    async def test_live_mode_off_returns_structural_only(self):
        """When live mode is disabled, verify_gstin must return
        structural_only — never INVALID and never call the live API."""
        # Patch the shared module at the gstin_service import site
        import app.services.gstin_service as gstin_mod

        class _FakeChecker:
            @staticmethod
            def is_live_mode_enabled():
                return False

            @staticmethod
            def check_and_reserve_quota(_):
                return False

        with patch.object(gstin_mod, "_fetch_gstin_live", side_effect=Exception("should not be called")):
            # Force the try/except live_mode branch to use our stub
            original_import = __builtins__.__dict__.get("__import__") if hasattr(__builtins__, "__dict__") else None

            import importlib
            import sys
            # Inject a fake shared.live_mode.checker
            fake_checker = MagicMock()
            fake_checker.is_live_mode_enabled.return_value = False
            fake_checker.check_and_reserve_quota.return_value = False
            sys.modules["shared.live_mode.checker"] = fake_checker
            try:
                result = await verify_gstin("29AABCT1332L1ZA", db=None)
            finally:
                # Clean up the injected module
                sys.modules.pop("shared.live_mode.checker", None)

        assert result.status == GSTINStatus.STRUCTURAL_ONLY
        assert result.data_source == "simulated"

    @pytest.mark.asyncio
    async def test_api_outage_returns_pending(self):
        """When the live API is reachable from the quota gate but the HTTP
        call fails, status must be 'pending' — not INVALID."""
        import httpx
        import sys

        fake_checker = MagicMock()
        fake_checker.is_live_mode_enabled.return_value = True
        fake_checker.check_and_reserve_quota.return_value = True
        sys.modules["shared.live_mode.checker"] = fake_checker

        try:
            with patch("app.services.gstin_service._fetch_gstin_live",
                       side_effect=httpx.ConnectError("connection refused")):
                result = await verify_gstin("29AABCT1332L1ZA", db=None)
        finally:
            sys.modules.pop("shared.live_mode.checker", None)

        assert result.status == GSTINStatus.PENDING

    @pytest.mark.asyncio
    async def test_invalid_format_never_reaches_live_api(self):
        """A malformed GSTIN must be rejected offline before the quota gate."""
        live_called = []

        async def _fake_fetch(*args, **kwargs):
            live_called.append(True)
            return {}

        with patch("app.services.gstin_service._fetch_gstin_live", side_effect=_fake_fetch):
            result = await verify_gstin("INVALID_GSTIN", db=None)

        assert result.status == GSTINStatus.INVALID
        assert not live_called, "Live API should never be called for a malformed GSTIN"
