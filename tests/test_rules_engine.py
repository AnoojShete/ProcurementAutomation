"""Unit tests for shared/rules_engine client."""
import time
from unittest.mock import MagicMock, patch
import pytest

from shared.rules_engine import (
    get_rule,
    invalidate_rule,
    update_rule_cache,
    clear_cache,
    fetch_all_rules,
)


@pytest.fixture(autouse=True)
def reset_rules_engine_cache():
    clear_cache()
    yield
    clear_cache()


class TestSharedRulesEngine:
    def test_get_rule_fetches_from_auth_service(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "approval.auto_approve_max_amount": 7500.0,
                "vendor.duplicate_invoice_days_window": 7,
            }
        }

        with patch("httpx.Client.get", return_value=mock_resp) as mock_get:
            val = get_rule("approval.auto_approve_max_amount", fallback=5000.0)
            assert val == 7500.0
            mock_get.assert_called_once()
            # Verify X-Internal-Service-Secret header sent
            call_headers = mock_get.call_args[1]["headers"]
            assert "X-Internal-Service-Secret" in call_headers

    def test_cache_hit_on_second_call_no_extra_http_request(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "approval.auto_approve_max_amount": 8000.0,
            }
        }

        with patch("httpx.Client.get", return_value=mock_resp) as mock_get:
            val1 = get_rule("approval.auto_approve_max_amount", fallback=5000.0)
            assert val1 == 8000.0
            assert mock_get.call_count == 1

            # Second call should hit in-memory cache
            val2 = get_rule("approval.auto_approve_max_amount", fallback=5000.0)
            assert val2 == 8000.0
            assert mock_get.call_count == 1  # No additional network request

    def test_invalidate_rule_clears_cache_key(self):
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = {
            "data": {"approval.auto_approve_max_amount": 5000.0}
        }

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = {
            "data": {"approval.auto_approve_max_amount": 10000.0}
        }

        with patch("httpx.Client.get", side_effect=[mock_resp1, mock_resp2]) as mock_get:
            val1 = get_rule("approval.auto_approve_max_amount")
            assert val1 == 5000.0
            assert mock_get.call_count == 1

            # Invalidate
            invalidate_rule("approval.auto_approve_max_amount")

            # Next fetch should re-request
            val2 = get_rule("approval.auto_approve_max_amount")
            assert val2 == 10000.0
            assert mock_get.call_count == 2

    def test_update_rule_cache_applies_immediately(self):
        update_rule_cache("license.anomaly_watch_threshold", 0.85)
        # Should not make any HTTP calls
        with patch("httpx.Client.get") as mock_get:
            val = get_rule("license.anomaly_watch_threshold")
            assert val == 0.85
            mock_get.assert_not_called()

    def test_fallback_when_auth_service_unreachable(self):
        with patch("httpx.Client.get", side_effect=Exception("Connection refused")):
            val = get_rule("budget.variance_warning_threshold", fallback=0.10)
            assert val == 0.10

    def test_cache_expires_after_ttl(self):
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = {
            "data": {"vendor.petty_cash_threshold": 500.0}
        }

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = {
            "data": {"vendor.petty_cash_threshold": 750.0}
        }

        with patch("httpx.Client.get", side_effect=[mock_resp1, mock_resp2]) as mock_get:
            val1 = get_rule("vendor.petty_cash_threshold")
            assert val1 == 500.0
            assert mock_get.call_count == 1

            # Fast-forward time past 300s TTL
            future_time = time.time() + 305
            with patch("time.time", return_value=future_time):
                val2 = get_rule("vendor.petty_cash_threshold")
                assert val2 == 750.0
                assert mock_get.call_count == 2
