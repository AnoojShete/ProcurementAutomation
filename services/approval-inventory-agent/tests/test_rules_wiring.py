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


def test_approval_unrated_vendor_requires_finance(rule):
    from app.services.budget_service import route
    within = _over_check(status="within", used_before=0.0, left_after=8000.0)
    rule("approval.unrated_vendor_requires_finance", False)
    assert route(["dept_manager"], within, "Unrated", True) == (["dept_manager"], [])
    rule("approval.unrated_vendor_requires_finance", True)
    assert route(["dept_manager"], within, "Unrated", True) == (["dept_manager", "finance_head"], ["unrated_vendor"])
    assert route(["dept_manager"], within, "Low", True) == (["dept_manager"], [])
    assert route(["dept_manager"], within, "Unrated", False) == (["dept_manager"], [])


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


# ── Phase 4: TDS and MSME (app/services/tds_service.py) ─────────────────────

def test_tds_category_sections(rule):
    from app.services.tds_service import section_for_category
    rule("tds.category_sections", {"hardware": "194Q", "software": "194J(b)", "saas": "194J(a)", "services": "194J(a)"})
    assert section_for_category("saas") == "194J(a)"
    rule("tds.category_sections", {"hardware": "194Q", "software": "194J(b)", "saas": "194C", "services": "194J(a)"})
    assert section_for_category("saas") == "194C"


def test_msme_payment_days(rule):
    from datetime import date
    from app.services.tds_service import msme_due
    rule("msme.payment_days", 45)
    assert msme_due(date(2026, 9, 1), date(2026, 9, 1))["due_date"] == "2026-10-16"
    rule("msme.payment_days", 15)
    assert msme_due(date(2026, 9, 1), date(2026, 9, 1))["due_date"] == "2026-09-16"


def test_msme_warning_days(rule):
    from datetime import date
    from app.services.tds_service import msme_due
    rule("msme.payment_days", 45)
    rule("msme.warning_days", 7)
    assert msme_due(date(2026, 9, 1), date(2026, 10, 6))["status"] == "ok"        # 10 days left
    rule("msme.warning_days", 14)
    assert msme_due(date(2026, 9, 1), date(2026, 10, 6))["status"] == "due_soon"


# ── Bulk approval (Prompt 10) ────────────────────────────────────────────

def _bulk_request(**kw):
    base = dict(id="r-1", amount=10000, currency="INR", status="pending_approval", request_type="hardware",
                requested_by="requester@company.com", requested_by_user_id=None, budget_status="within",
                approval_chain=["dept_manager"], current_approver_index=0, vendor_id=None, document_id=None)
    return SimpleNamespace(**{**base, **kw})


def _bulk_codes(req):
    from app.services import bulk_service
    from app.services.approval_authority import AuthorityDecision
    allowed = AuthorityDecision(allowed=True, code="ok", reason="")
    with patch.object(bulk_service, "check_request_authority", AsyncMock(return_value=allowed)):
        return run(bulk_service.bulk_eligibility(AsyncMock(), req, "approver@company.com", "approver"))[1]


def test_approval_bulk_approve_enabled(rule):
    rule("approval.bulk_approve_enabled", True)
    assert "bulk_disabled" not in _bulk_codes(_bulk_request())
    rule("approval.bulk_approve_enabled", False)
    assert "bulk_disabled" in _bulk_codes(_bulk_request())


def test_approval_bulk_approve_max_amount(rule):
    rule("approval.bulk_approve_max_amount", 25000)
    assert "above_bulk_limit" not in _bulk_codes(_bulk_request(amount=20000))
    rule("approval.bulk_approve_max_amount", 15000)
    assert "above_bulk_limit" in _bulk_codes(_bulk_request(amount=20000))


def test_approval_bulk_excluded_request_types(rule):
    rule("approval.bulk_excluded_request_types", [])
    assert "excluded_request_type" not in _bulk_codes(_bulk_request(request_type="software"))
    rule("approval.bulk_excluded_request_types", ["software"])
    assert "excluded_request_type" in _bulk_codes(_bulk_request(request_type="software"))


def _bulk_run(request_ids, recent_batches=0, requests=None):
    """execute_bulk_decision with the database mocked: no earlier batch with
    this key, `recent_batches` batches in the last hour, and each id loaded
    from `requests` (eligible, approved through a mocked ApprovalService)."""
    from app.services import bulk_service
    first = MagicMock(scalar_one_or_none=MagicMock(return_value=None), scalar=MagicMock(return_value=recent_batches))
    db = MagicMock(execute=AsyncMock(return_value=first), commit=AsyncMock(), add=MagicMock())
    item = MagicMock(add=MagicMock(), commit=AsyncMock(), get=AsyncMock(return_value=None))
    item.execute = AsyncMock(side_effect=lambda stmt: MagicMock(scalar_one_or_none=MagicMock(
        return_value=(requests or {}).get(item.current))))
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = item
    ids = iter(sorted(request_ids))

    async def enter(*_):
        item.current = next(ids, None)
        return item
    factory.return_value.__aenter__.side_effect = enter
    with patch.object(bulk_service, "async_session_factory", factory), \
         patch.object(bulk_service, "bulk_eligibility", AsyncMock(return_value=(True, [], []))), \
         patch.object(bulk_service, "ApprovalService") as svc:
        svc.return_value.process_decision = AsyncMock()
        return run(bulk_service.execute_bulk_decision(
            db=db, producer=None, approver_id="approver@company.com", approver_role="approver",
            request_ids=request_ids, idempotency_key="k-1"))


def test_approval_bulk_approve_max_items(rule):
    from fastapi import HTTPException
    rule("approval.bulk_approve_max_items", 5)
    assert _bulk_run(["a", "b", "c"])["count_requested"] == 3
    rule("approval.bulk_approve_max_items", 2)
    with pytest.raises(HTTPException) as e:
        _bulk_run(["a", "b", "c"])
    assert e.value.status_code == 400


def test_approval_bulk_actions_per_hour(rule):
    from fastapi import HTTPException
    rule("approval.bulk_actions_per_hour", 20)
    assert _bulk_run(["a"], recent_batches=5)["count_requested"] == 1
    rule("approval.bulk_actions_per_hour", 5)
    with pytest.raises(HTTPException) as e:
        _bulk_run(["a"], recent_batches=5)
    assert e.value.status_code == 429


def test_approval_bulk_approve_max_batch_total(rule):
    reqs = {"a": _bulk_request(id="a", amount=10000), "b": _bulk_request(id="b", amount=10000)}
    rule("approval.bulk_approve_max_batch_total", 30000)
    assert _bulk_run(["a", "b"], requests=reqs)["count_approved"] == 2
    rule("approval.bulk_approve_max_batch_total", 15000)
    result = _bulk_run(["a", "b"], requests=reqs)
    assert result["count_approved"] == 1
    assert result["items"][1]["reason_code"] == "batch_cap_reached_amount"


def test_approval_bulk_email_token_ttl_hours(rule):
    from app.services.email_action_token_service import mint_batch_action_token
    db = MagicMock(add=MagicMock(), commit=AsyncMock())

    def hours_valid():
        _, expires_at, _ = run(mint_batch_action_token(db, "finance@company.com", ["r-1", "r-2"]))
        return round((expires_at - datetime.now(timezone.utc)).total_seconds() / 3600)
    rule("approval.bulk_email_token_ttl_hours", 48)
    assert hours_valid() == 48
    rule("approval.bulk_email_token_ttl_hours", 6)
    assert hours_valid() == 6


def _digest_run(groups, sent_today=()):
    """One bulk_digest.send_digests run over {approver: [requests]}; returns
    the notification.send calls it staged."""
    from app.services import bulk_digest
    publish = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = MagicMock(commit=AsyncMock())
    expires = datetime.now(timezone.utc) + timedelta(hours=48)
    with patch.object(bulk_digest, "eligible_by_approver", AsyncMock(return_value=groups)), \
         patch.object(bulk_digest, "_already_sent_today", AsyncMock(side_effect=lambda db, a, now: a in sent_today)), \
         patch.object(bulk_digest.tokens, "revoke_batch_tokens", AsyncMock(return_value=0)), \
         patch.object(bulk_digest.tokens, "mint_batch_action_token",
                      AsyncMock(return_value=("raw", expires, "http://localhost:8080/email-action/batch/raw"))), \
         patch.object(bulk_digest, "staged", MagicMock(return_value=SimpleNamespace(publish_notification=publish))):
        run(bulk_digest.send_digests(factory, producer=MagicMock()))
    return publish.await_args_list


def _digest_requests(n, prefix="r"):
    return [SimpleNamespace(id=f"{prefix}-{i}-0000-0000", amount=1000, requested_by="req@company.com",
                            department="IT", request_type="software") for i in range(n)]


def test_approval_bulk_digest_enabled(rule):
    groups = {"approver@company.com": _digest_requests(3)}
    rule("approval.bulk_digest_enabled", True)
    [call] = _digest_run(groups)
    assert call.kwargs["template_name"] == "bulk_approval_digest"
    assert call.kwargs["recipient"] == "approver@company.com"
    assert call.kwargs["template_context"]["count"] == 3
    rule("approval.bulk_digest_enabled", False)
    assert _digest_run(groups) == []


def test_approval_bulk_digest_min_items(rule):
    groups = {"a@company.com": _digest_requests(3, "a"), "b@company.com": _digest_requests(1, "b")}
    rule("approval.bulk_digest_min_items", 1)
    assert sorted(c.kwargs["recipient"] for c in _digest_run(groups)) == ["a@company.com", "b@company.com"]
    rule("approval.bulk_digest_min_items", 2)
    assert [c.kwargs["recipient"] for c in _digest_run(groups)] == ["a@company.com"]


def test_approval_bulk_digest_time_ist(rule):
    from app.services import bulk_digest
    at_0915_ist = datetime(2026, 10, 26, 3, 45, tzinfo=timezone.utc)
    rule("approval.bulk_digest_time_ist", "09:00")
    assert bulk_digest.is_due(at_0915_ist, bulk_digest.digest_time())
    rule("approval.bulk_digest_time_ist", "10:00")
    assert not bulk_digest.is_due(at_0915_ist, bulk_digest.digest_time())


def test_approval_bulk_email_enabled(rule):
    from app.api import email_action
    from app.services.email_action_token_service import mint_batch_action_token
    db = MagicMock(add=MagicMock(), commit=AsyncMock())
    token = SimpleNamespace(revoked_at=None, used_at=None, request_ids=[],
                            expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    page_db = MagicMock(execute=AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=token))))
    groups = {"approver@company.com": _digest_requests(3)}

    rule("approval.bulk_email_enabled", True)
    raw, _, url = run(mint_batch_action_token(db, "approver@company.com", ["r-1"]))
    assert url.endswith(f"/email-action/batch/{raw}")
    assert len(_digest_run(groups)) == 1
    # Past the on/off check: this token is expired.
    assert run(email_action.get_email_batch_page("t", MagicMock(), page_db)).status_code == 410

    rule("approval.bulk_email_enabled", False)
    with pytest.raises(ValueError):
        run(mint_batch_action_token(db, "approver@company.com", ["r-1"]))
    assert _digest_run(groups) == []
    assert run(email_action.get_email_batch_page("t", MagicMock(), page_db)).status_code == 403


def test_bulk_digest_caps_items_and_skips_approvers_sent_today(rule):
    rule("approval.bulk_approve_max_items", 2)
    groups = {"a@company.com": _digest_requests(5, "a"), "b@company.com": _digest_requests(3, "b")}
    [call] = _digest_run(groups, sent_today={"b@company.com"})
    assert call.kwargs["recipient"] == "a@company.com"
    assert [i["request_id"] for i in call.kwargs["template_context"]["items"]] == ["a-0-0000-0000", "a-1-0000-0000"]


def test_reorder_create_request_roles(rule):
    from fastapi import HTTPException
    from app.api.requests import create_request

    class PastRoleCheck(Exception):
        pass

    def create_as_approver():
        data = SimpleNamespace(source="reorder_suggestion", model_copy=MagicMock(side_effect=PastRoleCheck))
        user = SimpleNamespace(role="approver", email="approver@company.com", id="u-1")
        run(create_request(data=data, request=MagicMock(), idempotency_key=None, approval_svc=MagicMock(), user=user))
    rule("reorder.create_request_roles", ["requester", "approver"])
    with pytest.raises(PastRoleCheck):
        create_as_approver()
    rule("reorder.create_request_roles", ["requester"])
    with pytest.raises(HTTPException) as e:
        create_as_approver()
    assert e.value.status_code == 403
