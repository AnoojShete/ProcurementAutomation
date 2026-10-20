"""Feature expansion Phase 2: contract obligations — reading them from our
own templates, the service-credit calculation, due dates and reminders,
the lifecycle, and who may do what through the API."""
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

from app.api import obligations as obligations_api
from app.database import get_db
from app.services import contract_service
from app.services import obligation_extraction as ox
from app.services import obligation_service as svc
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser
from shared.http.error_handlers import register_error_handlers


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _render(template, **extra):
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "..", "app", "templates")))
    return env.get_template(f"{template}.j2").render(
        contract_id="c", generated_at="2026-10-16", vendor_name="Acme", purchase_request_id="p", department="IT",
        items=[], amount=100, currency="INR", contract_end_date="2027-10-16", notice_period_days=30, **extra)


# ── extraction from the contracts we generate ───────────────────────────────

@pytest.mark.parametrize("users,minimum", [(40, 20), (1, 1), (250, 125)])
def test_rules_read_every_saas_obligation(users, minimum):
    found = {o["type"]: o["value"] for o in ox.extract_with_rules(
        _render("saas_subscription", licensed_users=users, minimum_users=minimum))}
    assert found == {
        "sla_uptime": {"uptime_pct": 99.9, "credit_pct_per_step": 10.0, "step_pct": 0.1, "credit_cap_pct": 50.0},
        "license_limit": {"seats": users, "non_transferable": True, "territory": "India"},
        "price_cap": {"max_increase_pct": 5.0},
        "audit_rights": {"days": 30, "frequency": "annual"},
        "minimum_commitment": {"seats": minimum, "months": 12},
        "post_termination": {"days": 30},
        "data_protection": {"breach_notice_hours": 72},
        "liability_cap": {"fees_months": 12},
        "insurance": {"amount": 10000000.0},
    }


def test_rules_read_hardware_and_services_obligations():
    hw = {o["type"]: o["value"] for o in ox.extract_with_rules(_render("hardware_purchase"))}
    assert hw["warranty"] == {"months": 36} and "liability_cap" in hw
    ps = {o["type"]: o["value"] for o in ox.extract_with_rules(_render("professional_services"))}
    assert ps == {"termination_convenience": {"days": 30}, "post_termination": {"days": 15},
                  "liability_cap": {"fees_months": 12}, "insurance": {"amount": 5000000.0}}


def test_renewal_clause_fields_are_untouched_by_the_new_sections():
    """FR-13 reads renewal type / notice / end date from the same text; the
    obligation clauses must not give it a second 'notice' to latch onto."""
    from app.services.clause_extraction import extract_clauses
    result = extract_clauses(_render("saas_subscription", licensed_users=40, minimum_users=20))
    assert result == {"renewal_type": "auto", "notice_period_days": 30, "contract_end_date": date(2027, 10, 16)}


def test_clause_text_is_the_sentence_not_the_heading():
    sla = next(o for o in ox.extract_with_rules(_render("saas_subscription", licensed_users=5, minimum_users=2))
               if o["type"] == "sla_uptime")
    assert "99.9%" in sla["clause_text"] and "credit" in sla["clause_text"].lower()
    assert not sla["clause_text"].lstrip().startswith(("5.", "SERVICE"))


def test_nothing_is_invented_from_unrelated_text():
    assert ox.extract_with_rules("The parties agree to meet quarterly to discuss the roadmap.") == []


@pytest.mark.parametrize("text,months", [("for a period of 24 months", 24), ("for two (2) years", 24),
                                         ("for one year", 12), ("18-month", 18)])
def test_months_parser(text, months):
    assert ox.months_from(text) == months


# ── service credits ─────────────────────────────────────────────────────────

SLA = {"uptime_pct": 99.9, "credit_pct_per_step": 10, "step_pct": 0.1, "credit_cap_pct": 50}


@pytest.mark.parametrize("measured,pct", [(99.95, 0), (99.9, 0), (99.85, 10), (99.8, 10), (99.6, 30),
                                          (99.0, 50), (80.0, 50)])
def test_sla_credit_steps_and_cap(measured, pct):
    out = ox.sla_credit(SLA, measured, 12000.0)
    assert out["credit_pct"] == pct
    assert out["credit_amount"] == round(12000.0 * pct / 100, 2)


def test_sla_credit_needs_terms():
    assert ox.sla_credit({"uptime_pct": 99.9}, 90.0, 1000.0)["credit_amount"] == 0


# ── due dates and reminders ─────────────────────────────────────────────────

def _ob(type_, value=None, **kw):
    base = dict(id="o-1", contract_id="c-1", type=type_, value=value or {}, status="open", due_date=None,
                recurrence=ox.TYPES[type_].recurrence, owner_email=None, license_id=None, clause_text=None,
                extracted_by="regex", confidence=None, confirmed_by=None, confirmed_at=None)
    return SimpleNamespace(**{**base, **kw})


SIGNED = datetime(2026, 3, 15, tzinfo=timezone.utc)
CONTRACT = SimpleNamespace(signed_at=SIGNED, contract_end_date=date(2027, 3, 15), status="signed")


@pytest.mark.parametrize("type_,value,expected", [
    ("sla_uptime", {}, (date(2026, 10, 31), "monthly")),
    ("audit_rights", {}, (date(2027, 3, 15), "annual")),
    ("warranty", {"months": 36}, (date(2029, 3, 15), "none")),
    ("minimum_commitment", {"months": 12}, (date(2027, 3, 15), "none")),
    ("price_cap", {}, (date(2027, 3, 15), "none")),
    ("post_termination", {"days": 30}, (date(2027, 4, 14), "none")),
    ("liability_cap", {}, (None, "none")),
])
def test_first_due(type_, value, expected):
    assert svc.first_due(_ob(type_, value), CONTRACT, date(2026, 10, 20)) == expected


def test_next_due_rolls_monthly_and_yearly():
    assert svc.next_due(_ob("sla_uptime", due_date=date(2026, 1, 31), recurrence="monthly")) == date(2026, 2, 28)
    assert svc.next_due(_ob("audit_rights", due_date=date(2027, 3, 15), recurrence="annual")) == date(2028, 3, 15)
    assert svc.next_due(_ob("warranty", due_date=date(2029, 3, 15), recurrence="none")) is None


TODAY = date(2026, 10, 20)


@pytest.mark.parametrize("days_left,key", [(45, None), (30, "30"), (20, "30"), (7, "7"), (3, "7"), (0, "7"),
                                           (-1, "overdue")])
def test_reminder_due_uses_the_nearest_threshold(days_left, key):
    due = TODAY + timedelta(days=days_left)
    out = svc.reminder_due(_ob("warranty", due_date=due), TODAY, [30, 7])
    assert (out[0] if out else None) == (f"{due}:{key}" if key else None)


def test_monthly_review_reminds_only_on_the_day():
    assert svc.reminder_due(_ob("sla_uptime", due_date=TODAY + timedelta(days=5)), TODAY, [30, 7]) is None
    assert svc.reminder_due(_ob("sla_uptime", due_date=TODAY), TODAY, [30, 7])[0] == f"{TODAY}:0"


# ── lifecycle ───────────────────────────────────────────────────────────────

def test_recurring_obligation_met_rolls_to_next_period():
    ob = _ob("audit_rights", due_date=date(2027, 3, 15), recurrence="annual")
    run(svc.record(MagicMock(), ob, "met", "fin@acme.test"))
    assert ob.status == "open" and ob.due_date == date(2028, 3, 15)


def test_one_off_obligation_met_is_closed():
    ob = _ob("warranty", due_date=date(2029, 3, 15))
    run(svc.record(MagicMock(), ob, "met", "fin@acme.test"))
    assert ob.status == "met"


def test_waive_needs_a_reason_and_unconfirmed_needs_confirming():
    with pytest.raises(svc.ObligationError):
        run(svc.record(MagicMock(), _ob("warranty"), "waived", "fin@acme.test", note=" "))
    with pytest.raises(svc.ObligationError):
        run(svc.record(MagicMock(), _ob("warranty", status="to_confirm"), "met", "fin@acme.test"))


def test_licence_limit_linked_to_a_licence_needs_seats():
    ob = _ob("license_limit", {}, status="to_confirm")
    db = MagicMock(get=AsyncMock(return_value=CONTRACT))
    with pytest.raises(svc.ObligationError):
        run(svc.confirm(db, ob, "fin@acme.test", license_id="22222222-2222-2222-2222-222222222222"))


def test_confirm_sets_due_date_and_opens():
    ob = _ob("warranty", {"months": 36}, status="to_confirm")
    run(svc.confirm(MagicMock(get=AsyncMock(return_value=CONTRACT)), ob, "fin@acme.test", owner_email="it@acme.test"))
    assert (ob.status, ob.due_date, ob.owner_email, ob.confirmed_by) == \
        ("open", date(2029, 3, 15), "it@acme.test", "fin@acme.test")


# ── the sweep: licence limit ────────────────────────────────────────────────

def _sweep(ob, assigned, last_breach_source=None):
    contract = SimpleNamespace(id="c-1", vendor_id="v-1")
    session = MagicMock()
    session.execute = AsyncMock(side_effect=lambda stmt, params=None: _answer(stmt, params, ob, contract, assigned,
                                                                              last_breach_source))
    session.commit = AsyncMock()
    factory = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=session),
                                               __aexit__=AsyncMock(return_value=False)))
    producer = MagicMock(service_name="contract-risk-agent")
    published = []
    proxy = MagicMock(publish_obligation_due=AsyncMock(side_effect=lambda p: published.append(p)))
    with patch.object(svc, "staged", return_value=proxy):
        run(svc.sweep_reminders(factory, producer, today=TODAY))
    return published


def _answer(stmt, params, ob, contract, assigned, last_breach_source):
    sql = str(stmt)
    if "FROM licenses" in sql:
        return MagicMock(first=MagicMock(return_value=SimpleNamespace(app_name="Figma", assigned_seats=assigned)))
    if "kind = 'breach'" in sql:
        return MagicMock(first=MagicMock(return_value=(last_breach_source,) if last_breach_source else None))
    if "reminder_sent" in sql:
        return MagicMock(first=MagicMock(return_value=None))
    return MagicMock(all=MagicMock(return_value=[(ob, contract)]))


def test_sweep_flags_more_users_than_the_contract_allows():
    ob = _ob("license_limit", {"seats": 10}, license_id="l-1")
    published = _sweep(ob, assigned=12)
    assert ob.status == "breached"
    assert published[0]["kind"] == "breach" and "12 users assigned, contract allows 10" in published[0]["detail"]


def test_sweep_leaves_a_licence_within_its_limit_alone():
    ob = _ob("license_limit", {"seats": 10}, license_id="l-1")
    assert _sweep(ob, assigned=10) == [] and ob.status == "open"


def test_sweep_reopens_once_back_within_the_limit():
    ob = _ob("license_limit", {"seats": 10}, license_id="l-1", status="breached")
    _sweep(ob, assigned=9, last_breach_source="licence")
    assert ob.status == "open"


def test_sweep_keeps_a_manual_breach():
    ob = _ob("license_limit", {"seats": 10}, license_id="l-1", status="breached")
    _sweep(ob, assigned=9, last_breach_source="manual")
    assert ob.status == "breached"


def test_sweep_sends_a_due_reminder():
    ob = _ob("warranty", {"months": 36}, due_date=TODAY + timedelta(days=6))
    published = _sweep(ob, assigned=0)
    assert published[0]["kind"] == "due" and published[0]["days_left"] == 6


# ── API: who may do what ───────────────────────────────────────────────────

CONTRACT_ID = "11111111-1111-1111-1111-111111111111"
OB_ID = "33333333-3333-3333-3333-333333333333"


def _client(role, email="alice@acme.test", requester=True):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(obligations_api.router, prefix="/contracts")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=email, role=role)
    db = MagicMock()
    ob = _ob("warranty", {"months": 36}, status="open", due_date=date(2029, 3, 15), id=OB_ID)
    db.get = AsyncMock(side_effect=lambda model, _id: CONTRACT if model.__name__ == "Contract" else ob)
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    contract = SimpleNamespace(id=CONTRACT_ID, status="signed", obligations_extracted_at=None)
    patches = [patch.object(contract_service, "get_contract", AsyncMock(return_value=contract)),
               patch.object(contract_service, "is_requester_of", AsyncMock(return_value=requester))]
    for p in patches:
        p.start()
    return TestClient(app), patches


@pytest.fixture
def client():
    made = []

    def make(*a, **kw):
        c, patches = _client(*a, **kw)
        made.extend(patches)
        return c
    yield make
    for p in made:
        p.stop()


def test_requester_reads_obligations_of_own_contract(client):
    assert client("requester").get(f"/contracts/{CONTRACT_ID}/obligations").status_code == 200


def test_someone_elses_contract_is_a_404(client):
    assert client("requester", requester=False).get(f"/contracts/{CONTRACT_ID}/obligations").status_code == 404


@pytest.mark.parametrize("role,status", [("requester", 403), ("approver", 403), ("finance", 200)])
def test_only_finance_or_admin_confirms(client, role, status):
    assert client(role).patch(f"/contracts/obligations/{OB_ID}/confirm", json={}).status_code == status


@pytest.mark.parametrize("role,action,status", [
    ("requester", "met", 403), ("approver", "met", 200), ("approver", "waived", 403), ("finance", "reopened", 422),
])
def test_actions_by_role(client, role, action, status):
    r = client(role).post(f"/contracts/obligations/{OB_ID}/actions", json={"action": action, "note": "why"})
    assert r.status_code == status


def test_licence_view_is_staff_only(client):
    lid = "22222222-2222-2222-2222-222222222222"
    assert client("requester").get(f"/contracts/obligations/by-license/{lid}").status_code == 403
    assert client("approver").get(f"/contracts/obligations/by-license/{lid}").status_code == 200


def test_actor_comes_from_the_token_not_the_body(client):
    c = client("finance", email="fin@acme.test")
    r = c.patch(f"/contracts/obligations/{OB_ID}/confirm", json={"confirmed_by": "mallory@evil.test"})
    assert r.status_code == 200 and r.json()["data"]["confirmed_by"] == "fin@acme.test"
