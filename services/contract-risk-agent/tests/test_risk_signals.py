"""BR-7: risk-model inputs from platform history (tenure, on-time
delivery) and finance's compliance record (audit-logged)."""
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.services import risk_signals  # noqa: E402
from app.services.risk_signals import on_time_rate, tenure_months  # noqa: E402

NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def test_tenure_counts_whole_months():
    assert tenure_months(datetime(2025, 10, 16, tzinfo=timezone.utc), NOW) == 12
    assert tenure_months(datetime(2025, 10, 17, tzinfo=timezone.utc), NOW) == 11
    assert tenure_months(NOW, NOW) == 0
    assert tenure_months(None, NOW) is None


def test_on_time_rate_uses_the_delivery_window():
    signed = NOW - timedelta(days=60)
    deliveries = [(signed, signed + timedelta(days=3)),    # on time
                  (signed, signed + timedelta(days=14)),   # exactly the window: on time
                  (signed, signed + timedelta(days=15)),   # late
                  (signed, signed + timedelta(days=40))]   # late
    assert on_time_rate(deliveries, 14) == (0.5, 2, 4)
    assert on_time_rate(deliveries, 30) == (0.75, 3, 4)


def test_no_deliveries_means_unknown_not_zero():
    assert on_time_rate([], 14) == (None, 0, 0)


@pytest.mark.asyncio
async def test_platform_signals_from_history():
    db = AsyncMock()
    first = MagicMock(); first.scalar.return_value = NOW - timedelta(days=400)
    signed = NOW - timedelta(days=30)
    rows = MagicMock(); rows.all.return_value = [SimpleNamespace(ordered_at=signed, received_at=signed + timedelta(days=5)),
                                                 SimpleNamespace(ordered_at=signed, received_at=signed + timedelta(days=20))]
    db.execute.side_effect = [first, rows]
    with patch.object(risk_signals, "expected_delivery_days", return_value=14):
        s = await risk_signals.platform_signals(db, "v1", now=NOW)
    assert s == {"vendor_tenure_months": 13, "on_time_delivery_rate": 0.5, "deliveries": 2,
                 "deliveries_on_time": 1, "expected_delivery_days": 14}


@pytest.mark.asyncio
async def test_compliance_update_changes_only_given_fields_and_is_audited():
    row = SimpleNamespace(security_cert_flag=False, geo_risk_flag=False, breach_disclosure_count=None,
                          financial_stability_score=None, vendor_tenure_months=24, on_time_delivery_rate=0.9,
                          updated_at=None)
    db = AsyncMock()
    db.get.return_value = row
    audit = AsyncMock()
    with patch.object(risk_signals, "write_audit_log", new=audit):
        after = await risk_signals.update_compliance_signals(
            db, "v1", {"security_cert_flag": True, "breach_disclosure_count": 2, "vendor_tenure_months": 999}, "fin@x")
    assert after == {"security_cert_flag": True, "geo_risk_flag": False, "breach_disclosure_count": 2,
                     "financial_stability_score": None}
    assert row.vendor_tenure_months == 24          # platform signals can't be typed in
    payload = audit.await_args.args[4]
    assert audit.await_args.args[3] == "risk_signals_updated" and payload["changed_by"] == "fin@x"
    assert payload["before"]["security_cert_flag"] is False and payload["after"]["security_cert_flag"] is True


@pytest.mark.asyncio
async def test_scoring_collects_fresh_signals_first():
    """Deterministic scorecard: signals (delivery history among them) are
    collected before the ruleset is evaluated, so a rescore after a delivery
    sees it. (Replaces the ML model's refresh-then-load-features test.)"""
    from app.services import risk_service
    order = []

    async def collect(db, vendor, now=None, effective_tier=None):
        order.append("collect")
        return {}

    def evaluate(**kw):
        order.append("evaluate")
        raise RuntimeError("stop here")
    db = AsyncMock()
    db.get = AsyncMock(return_value=SimpleNamespace(id="v1", name="Acme", vendor_tier="standard"))
    db.execute.return_value = MagicMock(first=MagicMock(return_value=None))
    with patch.object(risk_service, "get_active_ruleset", AsyncMock(return_value=SimpleNamespace(definition={"signals": []}))), \
            patch.object(risk_service, "collect_all_signals", collect), \
            patch.object(risk_service, "latest_risk_score", AsyncMock(return_value=None)), \
            patch.object(risk_service, "evaluate_risk", evaluate):
        with pytest.raises(RuntimeError):
            await risk_service.score_vendor(db, None, "v1")
    assert order == ["collect", "evaluate"]


@pytest.mark.asyncio
async def test_drift_compares_informed_vendors_only(tmp_path):
    """Low-signal vendors are left out of the drift check and counted."""
    import json
    from app.services import drift_service
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"bin_edges": [0, 0.5, 1], "counts": [50, 50], "n_samples": 100}))
    rows = MagicMock()
    rows.all.return_value = [SimpleNamespace(score=0.3, signals_used=4), SimpleNamespace(score=0.6, signals_used=6),
                             SimpleNamespace(score=0.45, signals_used=0), SimpleNamespace(score=0.45, signals_used=None)]
    db = AsyncMock()
    db.execute.return_value = rows
    with patch.object(drift_service, "BASELINE_PATH", str(baseline)), \
            patch.object(drift_service, "load_drift_config", return_value={"min_outcomes_for_check": 5}):
        result = await drift_service.check_drift(db)
    assert result["checked"] is False and result["excluded_low_signal_scores"] == 2
    assert "only 2 vendors scored on ≥ 3 signals" in result["reason"]
