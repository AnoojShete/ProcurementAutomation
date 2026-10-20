"""FR-09: every business rule this service reads changes behaviour when an
admin changes it. Each test sets the rule to two values through the shared
rules-engine cache (the same path a live rule takes) and checks the effect.
docs/business-rules.md lists these tests per rule."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import shared.rules_engine as rules_engine


@pytest.fixture
def rule(monkeypatch):
    rules_engine.clear_cache()
    monkeypatch.setattr(rules_engine, "fetch_all_rules", lambda: {})
    yield rules_engine.update_rule_cache
    rules_engine.clear_cache()


def run(coro):
    loop = asyncio.new_event_loop()   # not asyncio.run: other tests rely on the current loop
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_approval_spend_tiers(rule):
    from app.services.approval_service import ApprovalService
    rule("approval.spend_tiers", [
        {"tier_name": "auto", "min_amount": 0, "max_amount": 5000, "required_roles": []},
        {"tier_name": "manager", "min_amount": 5000, "max_amount": None, "required_roles": ["dept_manager"]},
    ])
    assert ApprovalService.determine_spend_tier_static(3000) == ("auto", [])
    rule("approval.spend_tiers", [
        {"tier_name": "auto", "min_amount": 0, "max_amount": 1000, "required_roles": []},
        {"tier_name": "manager", "min_amount": 1000, "max_amount": None, "required_roles": ["dept_manager"]},
    ])
    assert ApprovalService.determine_spend_tier_static(3000) == ("manager", ["dept_manager"])


def _request_details():
    from app.workflows import activities
    req = SimpleNamespace(id="r-1", approval_chain=["dept_manager"], request_type="hardware", items=[])
    session = AsyncMock()
    session.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=req))
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    with patch.object(activities, "async_session_factory", factory):
        return run(activities.fetch_request_details("r-1"))


def test_approval_sla_escalation_hours(rule):
    rule("approval.sla_escalation_hours", 48)
    assert _request_details()["sla_hours"] == 48
    rule("approval.sla_escalation_hours", 8)
    assert _request_details()["sla_hours"] == 8


def test_approval_reminder_sla_percents(rule):
    rule("approval.reminder_sla_percents", [50, 80])
    assert _request_details()["reminder_percents"] == [50, 80]
    rule("approval.reminder_sla_percents", [25])
    assert _request_details()["reminder_percents"] == [25]


def test_approval_email_action_enabled(rule):
    from app.services.email_action_token_service import evaluate_step_up
    rule("approval.email_action_enabled", True)
    assert evaluate_step_up(100, False, "Low")[0] is True
    rule("approval.email_action_enabled", False)
    assert evaluate_step_up(100, False, "Low")[0] is False


def test_approval_email_action_max_amount(rule):
    from app.services.email_action_token_service import evaluate_step_up
    rule("approval.email_action_max_amount", 50000)
    assert evaluate_step_up(20000, False, "Low")[1] is False      # approve from email allowed
    rule("approval.email_action_max_amount", 10000)
    assert evaluate_step_up(20000, False, "Low")[1] is True       # must log in


def test_approval_email_action_allowed_over_budget(rule):
    from app.services.email_action_token_service import evaluate_step_up
    rule("approval.email_action_allowed_over_budget", False)
    assert evaluate_step_up(100, True, "Low")[1] is True
    rule("approval.email_action_allowed_over_budget", True)
    assert evaluate_step_up(100, True, "Low")[1] is False


def test_approval_email_action_allowed_high_risk_vendor(rule):
    from app.services.email_action_token_service import evaluate_step_up
    rule("approval.email_action_allowed_high_risk_vendor", False)
    assert evaluate_step_up(100, False, "High")[1] is True
    rule("approval.email_action_allowed_high_risk_vendor", True)
    assert evaluate_step_up(100, False, "High")[1] is False


def _token_lifetime_hours():
    from app.services import email_action_token_service as svc
    req = SimpleNamespace(status="pending_approval", approval_chain=["dept_manager"], current_approver_index=0,
                          requested_by="requester@x", sla_deadline=None)
    db = AsyncMock()
    db.get.return_value = req
    db.add = MagicMock()
    with patch.object(svc.authority, "load_delegations", AsyncMock(return_value=[])), \
            patch.object(svc, "revoke_tokens", AsyncMock()):
        _, expires_at, _ = run(svc.mint_email_action_token(db, "r-1", "approver@x", 0))
    return round((expires_at - datetime.now(timezone.utc)).total_seconds() / 3600)


def test_approval_email_token_ttl_hours(rule):
    rule("approval.email_token_ttl_hours", 48)
    assert _token_lifetime_hours() == 48
    rule("approval.email_token_ttl_hours", 6)
    assert _token_lifetime_hours() == 6


def _cooldown_days():
    from app.services.approval_service import ApprovalService
    lic = SimpleNamespace(reclaim_cooldown_until=None)
    req = SimpleNamespace(id="r-1", request_type="reclaim", status="pending_grace_period",
                          items=[{"license_id": "l-1"}])
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=lic))
    svc = ApprovalService(db, AsyncMock(), None)
    svc.get_request_with_history = AsyncMock(return_value=req)
    with patch("temporalio.client.Client.connect", AsyncMock(side_effect=RuntimeError("no temporal"))), \
            patch("app.services.email_action_token_service.revoke_tokens", AsyncMock()), \
            patch.object(req, "status", "pending_grace_period", create=True):
        try:
            run(svc.decline_reclaim("r-1", "owner@x"))
        except Exception:
            pass  # the status write after the cooldown isn't what this test checks
    return round((lic.reclaim_cooldown_until - datetime.now(timezone.utc)).total_seconds() / 86400)


def test_license_reclaim_cooldown_days(rule):
    rule("license.reclaim_cooldown_days", 45)
    assert _cooldown_days() == 45
    rule("license.reclaim_cooldown_days", 10)
    assert _cooldown_days() == 10


def test_license_anomaly_watch_threshold(rule):
    from app.config import anomaly_status_for
    rule("license.anomaly_anomalous_threshold", 0.9)
    rule("license.anomaly_watch_threshold", 0.5)
    assert anomaly_status_for(0.6) == "watch"
    rule("license.anomaly_watch_threshold", 0.7)
    assert anomaly_status_for(0.6) == "normal"


def test_license_anomaly_anomalous_threshold(rule):
    from app.config import anomaly_status_for
    rule("license.anomaly_watch_threshold", 0.3)
    rule("license.anomaly_anomalous_threshold", 0.9)
    assert anomaly_status_for(0.8) == "watch"
    rule("license.anomaly_anomalous_threshold", 0.7)
    assert anomaly_status_for(0.8) == "anomalous"
    # A reclaim is proposed exactly when the page says "anomalous".
    from app.services.usage_service import UsageService
    assert UsageService.should_trigger_reclaim_ml(0.7) is True
    assert UsageService.should_trigger_reclaim_ml(0.69) is False
    assert UsageService.should_trigger_reclaim_ml(None) is False
    rule("license.anomaly_anomalous_threshold", 0.39)
    assert UsageService.should_trigger_reclaim_ml(0.5) is True


def _reorder(point_pct=None, qty_pct=None):
    from app.services import reorder
    item = SimpleNamespace(id="i", sku="S", total_quantity=20, available_quantity=4, reorder_point=None, reorder_quantity=None)
    p, q = reorder.rule_defaults()
    return reorder.suggest(item, 0, p, q)


def test_inventory_reorder_point_pct(rule):
    rule("inventory.reorder_quantity_pct", 25)
    rule("inventory.reorder_point_pct", 20)          # point 4: 4 on the shelf → reorder
    assert _reorder()["needs_reorder"] is True
    rule("inventory.reorder_point_pct", 10)          # point 2 → fine
    assert _reorder()["needs_reorder"] is False


def test_inventory_reorder_quantity_pct(rule):
    rule("inventory.reorder_point_pct", 20)
    rule("inventory.reorder_quantity_pct", 25)
    assert _reorder()["reorder_quantity"] == 5
    rule("inventory.reorder_quantity_pct", 50)
    assert _reorder()["reorder_quantity"] == 10


def _match(total, unit_price):
    from app.services.invoice_ledger import Candidate, InvoiceLine, POLine, evaluate, tolerances_from_rules
    po = Candidate(request_id="r-1", status="ordered", amount=1000.0,
                   lines=[POLine(1, "Dell Latitude laptop", 1, 1000.0)])
    return evaluate(total, [InvoiceLine("Dell Latitude laptop", 1, unit_price)], [po], tolerances_from_rules()).status


def test_invoice_overbill_tolerance_pct(rule):
    rule("invoice.unit_price_tolerance_pct", 0.10)
    rule("invoice.overbill_tolerance_pct", 0.01)     # 1,030 on a 1,000 order: held
    assert _match(1030.0, 1030.0) == "variance"
    rule("invoice.overbill_tolerance_pct", 0.05)
    assert _match(1030.0, 1030.0) == "matched"


def test_invoice_unit_price_tolerance_pct(rule):
    rule("invoice.overbill_tolerance_pct", 0.10)
    rule("invoice.unit_price_tolerance_pct", 0.01)   # unit price 2 % over the PO: held
    assert _match(1020.0, 1020.0) == "variance"
    rule("invoice.unit_price_tolerance_pct", 0.05)
    assert _match(1020.0, 1020.0) == "matched"


# --- Phase 1: budget control (app/services/budget_service.py) -------------

def _over_check(**kw):
    from app.services.budget_service import BudgetCheck
    base = dict(status="over", fiscal_year="2026-27", period="Q3", category="hardware", department="IT",
                budget_id="b-1", budget_amount=10000.0, used_before=9000.0, request_amount=2000.0, left_after=-1000.0)
    return BudgetCheck(**{**base, **kw})


def test_budget_fiscal_period_type(rule):
    from app.services.budget_service import fiscal_period
    rule("budget.fiscal_year_start_month", 4)
    rule("budget.fiscal_period_type", "quarterly")
    assert fiscal_period(datetime(2026, 10, 20)) == ("2026-27", "Q3")
    rule("budget.fiscal_period_type", "annual")
    assert fiscal_period(datetime(2026, 10, 20)) == ("2026-27", "FY")


def test_budget_fiscal_year_start_month(rule):
    from app.services.budget_service import fiscal_period
    rule("budget.fiscal_period_type", "quarterly")
    rule("budget.fiscal_year_start_month", 4)
    assert fiscal_period(datetime(2027, 2, 1)) == ("2026-27", "Q4")
    rule("budget.fiscal_year_start_month", 1)
    assert fiscal_period(datetime(2027, 2, 1)) == ("2027-28", "Q1")


def test_budget_warning_threshold_pct(rule):
    from app.services.budget_service import status_for
    rule("budget.warning_threshold_pct", 0.8)
    assert status_for(1000, 850) == "warning"
    rule("budget.warning_threshold_pct", 0.9)
    assert status_for(1000, 850) == "within"


def test_budget_over_budget_requires_finance_approval(rule):
    from app.services.budget_service import route
    rule("budget.block_when_over", False)
    rule("budget.over_budget_requires_finance_approval", True)
    assert route(["dept_manager"], _over_check(), None, True) == (["dept_manager", "finance_head"], ["over_budget"])
    rule("budget.over_budget_requires_finance_approval", False)
    assert route(["dept_manager"], _over_check(), None, True) == (["dept_manager"], [])


def test_budget_block_when_over(rule):
    from app.services.budget_service import BudgetBlocked, route
    rule("budget.over_budget_requires_finance_approval", True)
    rule("budget.block_when_over", False)
    assert route([], _over_check(), None, True)[0] == ["finance_head"]
    rule("budget.block_when_over", True)
    with pytest.raises(BudgetBlocked) as e:
        route([], _over_check(), None, True)
    assert e.value.code == "over_budget"


def test_budget_no_budget_policy(rule):
    from app.services.budget_service import BudgetBlocked, route
    none = _over_check(status="no_budget", budget_id=None, budget_amount=None, left_after=None)
    rule("budget.no_budget_policy", "allow")
    assert route(["dept_manager"], none, None, True) == (["dept_manager"], [])
    rule("budget.no_budget_policy", "finance_approval")
    assert route(["dept_manager"], none, None, True) == (["dept_manager", "finance_head"], ["no_budget"])
    rule("budget.no_budget_policy", "block")
    with pytest.raises(BudgetBlocked):
        route(["dept_manager"], none, None, True)


def test_approval_high_risk_vendor_requires_finance(rule):
    from app.services.budget_service import route
    within = _over_check(status="within", used_before=0.0, left_after=8000.0)
    rule("approval.high_risk_vendor_requires_finance", False)
    assert route(["dept_manager"], within, "High", True) == (["dept_manager"], [])
    rule("approval.high_risk_vendor_requires_finance", True)
    assert route(["dept_manager"], within, "High", True) == (["dept_manager", "finance_head"], ["high_risk_vendor"])
    assert route(["dept_manager"], within, "Medium", True) == (["dept_manager"], [])


# ── Phase 3: catalog, RFQs, goods receipts ──────────────────────────────────

def _resolution(amount, all_catalog=True):
    from app.services.catalog_service import CatalogResolution
    return CatalogResolution(items=[], vendor_id="v1", request_type="hardware", amount=amount, all_catalog=all_catalog)


def test_catalog_preapproved_max_inr(rule):
    from app.services.catalog_service import preapproved
    rule("catalog.preapproved_max_inr", 0)            # off
    assert preapproved(_resolution(30000)) is False
    rule("catalog.preapproved_max_inr", 50000)
    assert preapproved(_resolution(30000)) is True
    assert preapproved(_resolution(60000)) is False
    assert preapproved(_resolution(30000, all_catalog=False)) is False   # a free-text line needs the manager


def test_sourcing_rfq_required_above_inr(rule):
    from app.services.sourcing_service import rfq_flag
    kw = dict(spends_money=True, all_catalog=False, from_rfq=False)
    rule("sourcing.rfq_required_above_inr", 200000)
    assert rfq_flag(250000, **kw)["code"] == "rfq_recommended"
    assert rfq_flag(150000, **kw) is None
    assert rfq_flag(250000, **{**kw, "from_rfq": True}) is None
    rule("sourcing.rfq_required_above_inr", 300000)
    assert rfq_flag(250000, **kw) is None
    rule("sourcing.rfq_required_above_inr", 0)        # off
    assert rfq_flag(10_000_000, **kw) is None


def test_sourcing_default_criteria(rule):
    from app.services.sourcing_service import score
    quotes = [{"id": "a", "vendor_id": "va", "total_inr": 100000, "lead_time_days": 30},
              {"id": "b", "vendor_id": "vb", "total_inr": 110000, "lead_time_days": 5}]
    from app.services.sourcing_service import default_criteria
    rule("sourcing.default_criteria", {"price": 1})
    assert score(quotes, default_criteria(), {})[0]["id"] == "a"          # cheapest wins on price alone
    rule("sourcing.default_criteria", {"price": 0.3, "lead_time": 0.7})
    assert score(quotes, default_criteria(), {})[0]["id"] == "b"          # fastest wins when speed weighs more
    rule("sourcing.default_criteria", {"price": 0.9})                     # doesn't add up to 1: defaults
    assert default_criteria()["price"] == 0.45


def test_invoice_match_against_received(rule):
    from app.services.invoice_ledger import _received
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[
        SimpleNamespace(request_id="r1", line_no=0, qty=30)])))
    rule("invoice.match_against_received", True)
    assert run(_received(db, ["r1"])) == {"r1": {0: 30.0}}
    rule("invoice.match_against_received", False)
    assert run(_received(db, ["r1"])) == {}
