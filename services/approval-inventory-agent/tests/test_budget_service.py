"""Phase 1: budget control before approval (app/services/budget_service.py,
app/api/budgets.py). Rule-by-rule behaviour is in test_rules_wiring.py."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import shared.rules_engine as rules_engine
from app.api import budgets as budgets_api
from app.api import requests as requests_api
from app.database import get_db
from app.services import budget_service
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser


@pytest.fixture(autouse=True)
def rules(monkeypatch):
    rules_engine.clear_cache()
    monkeypatch.setattr(rules_engine, "fetch_all_rules", lambda: {})
    rules_engine.update_rule_cache("budget.fiscal_period_type", "quarterly")
    rules_engine.update_rule_cache("budget.fiscal_year_start_month", 4)
    rules_engine.update_rule_cache("budget.warning_threshold_pct", 0.8)
    yield rules_engine.update_rule_cache
    rules_engine.clear_cache()


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


BUDGET = SimpleNamespace(id="b-1", amount_inr=10000, fiscal_year="2026-27", period="Q3", department="IT",
                         category="hardware", owner_email="cto@acme.test")


def _check(used, amount, budget=BUDGET):
    with patch.object(budget_service, "find_budget", AsyncMock(return_value=budget)), \
            patch.object(budget_service, "usage", AsyncMock(return_value={"b-1": {"used": used}})):
        return run(budget_service.check_request(AsyncMock(), request_type="hardware", department="IT", amount=amount))


def test_request_types_that_move_seats_have_no_budget():
    assert run(budget_service.check_request(AsyncMock(), request_type="reclaim", department="IT", amount=0)) is None
    assert budget_service.category_for("license") == "software"
    assert budget_service.category_for("saas") == "saas"


def test_check_within_warning_over():
    assert _check(1000, 2000).status == "within"
    c = _check(6000, 2500)            # 85 % after the request
    assert (c.status, c.warning_crossed, c.left_after) == ("warning", True, 1500)
    c = _check(9000, 2000)
    assert (c.status, c.warning_crossed, c.left_after) == ("over", True, -1000)


def test_warning_is_announced_once_not_on_every_later_request():
    # Already in warning before this request, still in warning after it.
    c = _check(8500, 100)
    assert c.status == "warning" and c.warning_crossed is False


def test_no_budget_row():
    with patch.object(budget_service, "find_budget", AsyncMock(return_value=None)):
        c = run(budget_service.check_request(AsyncMock(), request_type="saas", department="Data", amount=500))
    assert (c.status, c.budget_id, c.category) == ("no_budget", None, "saas")


def test_summary_figures():
    s = budget_service.summarise(BUDGET, {"consumed": 3000.0, "committed": 2000.0, "pending": 1000.0, "used": 6000.0})
    assert (s["left"], s["used_pct"], s["status"]) == (4000.0, 0.6, "within")


def test_vendor_rule_ignored_for_requests_that_spend_nothing(rules):
    rules("approval.high_risk_vendor_requires_finance", True)
    assert budget_service.route(["dept_manager"], None, "High", spends_money=False) == (["dept_manager"], [])


def test_finance_step_not_duplicated(rules):
    rules("budget.over_budget_requires_finance_approval", True)
    over = _check(9000, 2000)
    chain, reasons = budget_service.route(["dept_manager", "finance_head"], over, None, True)
    assert chain == ["dept_manager", "finance_head"] and reasons == ["over_budget"]


# --- API ---------------------------------------------------------------

def _client(role, svc=None):
    app = FastAPI()
    app.include_router(budgets_api.router, prefix="/budgets")
    app.include_router(requests_api.router, prefix="/requests")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u-" + role, email=f"{role}@acme.test", role=role)
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    if svc is not None:
        app.dependency_overrides[requests_api.get_approval_service] = lambda: svc
    return TestClient(app)


BODY = {"department": "IT", "category": "hardware", "amount_inr": 50000}


def test_requesters_cannot_read_or_write_budgets():
    c = _client("requester")
    assert c.get("/budgets/").status_code == 403
    assert c.post("/budgets/", json=BODY).status_code == 403


def test_approvers_read_but_cannot_write():
    c = _client("approver")
    assert c.post("/budgets/", json=BODY).status_code == 403
    assert c.patch("/budgets/b-1", json={"amount_inr": 1}).status_code == 403


@pytest.mark.parametrize("body", [
    {**BODY, "category": "furniture"},
    {**BODY, "amount_inr": -1},
    {**BODY, "fiscal_year": "2026"},
    {**BODY, "period": "Q5"},
])
def test_invalid_budgets_are_refused(body):
    assert _client("finance").post("/budgets/", json=body).status_code == 422


def test_quarterly_budgets_refuse_an_annual_period():
    r = _client("finance").post("/budgets/", json={**BODY, "period": "FY"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "period_mismatch"


def test_request_budget_line_is_hidden_from_other_requesters():
    req = SimpleNamespace(id="r-1", requested_by="someone.else@acme.test", request_type="hardware",
                          budget_id=None, budget_status=None, budget_check=None)
    svc = SimpleNamespace(get_request_with_history=AsyncMock(return_value=req), db=AsyncMock())
    r = _client("requester", svc).get("/requests/11111111-1111-1111-1111-111111111111/budget")
    assert r.status_code == 404


def test_blocked_request_returns_the_rules_code():
    svc = SimpleNamespace(create_request=AsyncMock(side_effect=budget_service.BudgetBlocked("over_budget", "no money left")))
    r = _client("requester", svc).post("/requests/", json={
        "request_type": "hardware", "requested_by": "x", "department": "IT", "amount": 1000})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "over_budget"
