"""FR-09: every business rule this service reads changes behaviour when an
admin changes it. Each test sets the rule to two values through the shared
rules-engine cache (the same path a live rule takes) and checks the effect.
docs/business-rules.md lists these tests per rule."""
import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import shared.rules_engine as rules_engine  # noqa: E402


@pytest.fixture
def rule(monkeypatch):
    rules_engine.clear_cache()
    monkeypatch.setattr(rules_engine, "fetch_all_rules", lambda: {})
    yield rules_engine.update_rule_cache
    rules_engine.clear_cache()


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_risk_contract_renewal_milestones_days(rule):
    from app.api.contracts import _renewal_schedule
    contract = SimpleNamespace(contract_end_date=date(2028, 1, 1), notice_period_days=30)
    rule("risk.contract_renewal_milestones_days", [60, 30, 15])
    assert [r["alert_level"] for r in _renewal_schedule(contract)["renewal_reminders"]] == [60, 30, 15]
    rule("risk.contract_renewal_milestones_days", [90])
    assert [r["alert_level"] for r in _renewal_schedule(contract)["renewal_reminders"]] == [90]


def _on_time_rate():
    from app.services import risk_signals
    now = datetime(2026, 10, 16, tzinfo=timezone.utc)
    signed = now - timedelta(days=40)
    db = AsyncMock()
    first = MagicMock(scalar=MagicMock(return_value=now - timedelta(days=400)))
    rows = MagicMock(all=MagicMock(return_value=[SimpleNamespace(ordered_at=signed, received_at=signed + timedelta(days=10))]))
    db.execute.side_effect = [first, rows]
    return run(risk_signals.platform_signals(db, "v-1", now=now))["on_time_delivery_rate"]


def test_vendor_expected_delivery_days(rule):
    rule("vendor.expected_delivery_days", 14)     # delivered in 10 days: on time
    assert _on_time_rate() == 1.0
    rule("vendor.expected_delivery_days", 7)
    assert _on_time_rate() == 0.0


def _auto_send():
    from app.services import contract_service
    db = AsyncMock()
    db.execute.return_value = MagicMock(first=MagicMock(return_value=("tried",)))
    contract = SimpleNamespace(id="c-1", status="draft")
    with patch.object(contract_service.settings, "esign_auto_send", True), \
            patch.object(contract_service, "is_drop_folder_contract", AsyncMock(return_value=False)):
        return run(contract_service.auto_send_for_signature(db, None, contract))


def test_contract_auto_send_scope(rule):
    rule("contract.auto_send_scope", "drop_folder")
    assert _auto_send() == "not_from_drop_folder"
    rule("contract.auto_send_scope", "all")
    assert _auto_send() == "already_tried"   # got past the scope check


def _signature_reminders_sent():
    from app.services import reminder_sweep
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    session = AsyncMock()
    session.execute.return_value = MagicMock(all=MagicMock(return_value=[
        SimpleNamespace(id="c-1", request_id="r-1", since=now - timedelta(days=4))]))
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    with patch.object(reminder_sweep, "remind_once", AsyncMock(return_value=True)):
        return run(reminder_sweep.sweep_signature_reminders(factory, object(), now=now))


def test_contract_signature_reminder_days(rule):
    rule("contract.signature_reminder_days", 3)    # waiting 4 days
    assert _signature_reminders_sent() == 1
    rule("contract.signature_reminder_days", 7)
    assert _signature_reminders_sent() == 0


def _drift(tmp_path):
    from app.services import drift_service
    baseline = tmp_path / "b.json"
    baseline.write_text(json.dumps({"bin_edges": [0, 0.5, 1], "counts": [50, 50], "n_samples": 100}))
    rows = MagicMock(all=MagicMock(return_value=[SimpleNamespace(score=0.3, signals_used=6)] * 7
                                   + [SimpleNamespace(score=0.7, signals_used=6)] * 3))
    db = AsyncMock()
    db.execute.return_value = rows
    with patch.object(drift_service, "BASELINE_PATH", str(baseline)), \
            patch.object(drift_service, "load_drift_config", return_value={"min_outcomes_for_check": 5}), \
            patch.object(drift_service, "_log_to_mlflow", lambda *a: None):
        return run(drift_service.check_drift(db))     # PSI here ≈ 0.17


def test_risk_psi_significant_threshold(rule, tmp_path):
    rule("risk.psi_moderate_threshold", 0.01)
    rule("risk.psi_significant_threshold", 0.2)
    assert _drift(tmp_path)["model_drift_detected"] is False
    rule("risk.psi_significant_threshold", 0.1)
    assert _drift(tmp_path)["model_drift_detected"] is True


def test_risk_psi_moderate_threshold(rule, tmp_path):
    rule("risk.psi_significant_threshold", 0.9)
    rule("risk.psi_moderate_threshold", 0.2)
    assert _drift(tmp_path)["moderate_drift_detected"] is False
    rule("risk.psi_moderate_threshold", 0.1)
    assert _drift(tmp_path)["moderate_drift_detected"] is True


def _clause_route():
    from app.services import clause_router
    one_of_three = {"renewal_type": "auto", "notice_period_days": None, "contract_end_date": None}
    with patch.object(clause_router, "extract_clauses", return_value=one_of_three), \
            patch.object(clause_router, "_log_to_db", lambda *a: None):
        return run(clause_router.route_clause_extraction(MagicMock(), "c-1", "text")).route_name


def test_contract_clause_extraction_fallback_threshold(rule):
    rule("contract.clause_extraction_fallback_threshold", 0.4)   # 1 of 3 clauses = 0.33
    assert _clause_route() == "keyword_fallback"
    rule("contract.clause_extraction_fallback_threshold", 0.3)
    assert _clause_route() == "regex_primary"


def _clause_result():
    from app.services import clause_router
    all_three = {"renewal_type": "auto", "notice_period_days": 30, "contract_end_date": "2027-01-01"}
    with patch.object(clause_router, "extract_clauses", return_value=all_three), \
            patch.object(clause_router, "_log_to_db", lambda *a: None):
        return run(clause_router.route_clause_extraction(MagicMock(), "c-1", "text"))


def test_dev_force_model_fallback(rule, monkeypatch):
    """FR-08: forcing the clause router's primary to fail shows the
    fallback (reason "forced") — in development only."""
    rule("contract.clause_extraction_fallback_threshold", 0.4)
    rule("dev.force_model_fallback", [])
    assert _clause_result().route_name == "regex_primary"
    rule("dev.force_model_fallback", ["clauses"])
    r = _clause_result()
    assert r.route_name == "keyword_fallback" and r.fallback_reason == "forced"
    monkeypatch.setenv("APP_ENV", "production")
    assert _clause_result().route_name == "regex_primary"


def test_risk_sanctions_match_threshold_pct(rule):
    """FR-14: the threshold decides what counts as a potential match
    ("Sea Breeze Shipping Lines" vs the listed "Sea Breeze Shipping
    Limited" scores about 86)."""
    from app.services import sanctions
    csv_text = ("id,schema,name,aliases,birth_date,countries,addresses,identifiers,sanctions,phones,emails,dataset,"
                "first_seen,last_seen,last_change\nuk-5,LegalEntity,Sea Breeze Shipping Limited,,,ir,,,,,,UK HMT,,,\n")
    index = sanctions.build_index(csv_text, "v")
    index["_flat"] = [sanctions.normalise(n) for n in index["entries"][0]["names"]]
    index["_owners"] = [(0, n) for n in index["entries"][0]["names"]]
    rule("risk.sanctions_match_threshold_pct", 90)
    assert sanctions.screen_name("Sea Breeze Shipping Lines", index) == []
    rule("risk.sanctions_match_threshold_pct", 85)
    assert sanctions.screen_name("Sea Breeze Shipping Lines", index)[0]["entity_id"] == "uk-5"
