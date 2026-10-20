"""Feature expansion Phase 4: TDS worked out when an invoice is booked,
MSME payment deadlines, and the vendor tax profile's checks. Rule-by-rule
behaviour is in test_rules_wiring.py; the live flow in tests/e2e/gst_flow.py."""
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import shared.rules_engine as rules_engine
from app.api import tds as tds_api
from app.database import get_db
from app.services import invoice_ledger, tds_service
from app.services.tds_service import Section, VendorTax, compute, financial_year, msme_due
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser

J_A = Section("194J(a)", "technical services", 2, 20, None, 50000)
C = Section("194C", "contracts", 2, 20, 30000, 100000)
Q = Section("194Q", "goods", 0.1, 5, None, 5_000_000, above_threshold_only=True)
PAN = VendorTax(pan="AABCD5678E")
DAY = date(2026, 10, 15)


@pytest.fixture(autouse=True)
def rules(monkeypatch):
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


def tds(section, vendor=PAN, total=118000.0, taxable=100000.0, ytd=0.0, when=DAY, foreign=False):
    return compute(section, vendor, total=total, taxable_value=taxable, year_to_date=ytd, invoice_date=when, foreign=foreign)


# ── the calculation ─────────────────────────────────────────────────────────

def test_tds_is_on_the_amount_before_gst_and_reduces_what_is_paid():
    r = tds(J_A)
    assert (r.section, r.rate_pct, r.base, r.amount, r.net_payable) == ("194J(a)", 2, 100000.0, 2000.0, 116000.0)


def test_without_gst_shown_separately_the_whole_amount_is_the_base():
    r = tds(J_A, taxable=None)
    assert r.base == 118000.0 and r.amount == 2360.0 and "full amount" in r.notes[0]


def test_nothing_is_deducted_below_the_threshold_until_the_year_passes_it():
    small = tds(J_A, total=23600, taxable=20000, ytd=10000)
    assert small.amount == 0 and small.net_payable == 23600 and "threshold" in small.notes[0]
    crossing = tds(J_A, total=23600, taxable=20000, ytd=40000)
    assert crossing.amount == 400 and any("earlier invoices" in n for n in crossing.notes)


def test_single_or_yearly_threshold_for_contracts():
    assert tds(C, total=40000, taxable=35000).amount == 700            # one invoice above 30,000
    assert tds(C, total=20000, taxable=20000, ytd=50000).amount == 0   # neither limit passed
    assert tds(C, total=20000, taxable=20000, ytd=90000).amount == 400  # the year passes 1,00,000


def test_goods_are_taxed_only_above_fifty_lakh_a_year():
    assert tds(Q, total=590000, taxable=500000, ytd=1_000_000).amount == 0
    part = tds(Q, total=1_180_000, taxable=1_000_000, ytd=4_600_000)     # 6,00,000 of it is above the limit
    assert part.amount == 600 and any("above the ₹50,00,000" in n for n in part.notes)
    assert tds(Q, total=1_180_000, taxable=1_000_000, ytd=6_000_000).amount == 1000


def test_no_pan_means_the_higher_rate():
    r = tds(J_A, vendor=VendorTax(pan=None))
    assert r.rate_pct == 20 and r.amount == 20000 and "No PAN" in r.notes[0]
    assert tds(J_A, vendor=VendorTax(pan="BADPAN")).rate_pct == 20


def test_lower_deduction_certificate_applies_until_it_expires():
    ldc = VendorTax(pan="AABCD5678E", ldc_rate_pct=0.5, ldc_valid_until=date(2026, 12, 31))
    assert tds(J_A, vendor=ldc).amount == 500
    assert tds(J_A, vendor=ldc, when=date(2027, 1, 5)).rate_pct == 2


def test_foreign_supplier_and_no_section_are_left_alone():
    assert tds(J_A, foreign=True).amount == 0 and "outside India" in tds(J_A, foreign=True).notes[0]
    assert tds(J_A, vendor=VendorTax(pan="AABCD5678E", country="US")).amount == 0
    r = tds(None)
    assert r.amount == 0 and r.net_payable == 118000.0 and r.section is None
    assert tds(Section("194J(a)", "x", 2, 20, active=False)).amount == 0


def test_financial_year_runs_april_to_march():
    assert financial_year(date(2026, 10, 15))[0] == "2026-27"
    assert financial_year(date(2027, 3, 31))[0] == "2026-27"
    assert financial_year(date(2027, 4, 1)) == ("2027-28", date(2027, 4, 1), date(2028, 4, 1))


def test_section_from_vendor_profile_else_category_rule():
    db = MagicMock()
    calls = []

    async def execute(sql, params=None):
        calls.append(str(sql))
        if "FROM vendors" in str(sql):
            return MagicMock(first=lambda: SimpleNamespace(pan="AABCD5678E", tds_section=None, ldc_rate_pct=None,
                                                          ldc_valid_until=None, country="IN"))
        if "FROM tds_sections" in str(sql):
            assert params["s"] == "194Q"                                # hardware request -> rule default
            return MagicMock(first=lambda: SimpleNamespace(section="194Q", description="goods", rate_pct=0.1,
                                                          rate_no_pan_pct=5, threshold_single_inr=None,
                                                          threshold_annual_inr=5_000_000, above_threshold_only=True,
                                                          active=True))
        return MagicMock(scalar=lambda: 5_200_000)                     # booked so far this year

    db.execute = execute
    r = run(tds_service.tds_for_invoice(db, vendor_id="v", document_id="d", request_type="hardware", total=118000,
                                        taxable_value=100000, invoice_date=DAY))
    assert r.section == "194Q" and r.amount == 100


# ── booking stores it ───────────────────────────────────────────────────────

def test_booking_keeps_tds_with_the_invoice(monkeypatch):
    req = SimpleNamespace(id="r-1", status="ordered", amount=118000, items=[{"description": "IT support", "quantity": 1,
                          "unit_price": 100000}], created_at=None, request_type="saas", updated_at=None)
    monkeypatch.setattr(invoice_ledger, "_load_candidates", AsyncMock(return_value=[req]))
    monkeypatch.setattr(invoice_ledger, "_balances", AsyncMock(return_value={}))
    monkeypatch.setattr(invoice_ledger, "_received", AsyncMock(return_value={}))
    monkeypatch.setattr(invoice_ledger, "expected_credit_notes", AsyncMock(return_value=[]))
    monkeypatch.setattr(tds_service, "tds_for_invoice",
                        AsyncMock(return_value=tds_service.TdsResult("194J(a)", 2, 100000, 2000, 116000, [])))
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(first=lambda: None))
    result = run(invoice_ledger.book_invoice(
        db, document_id="d-1", vendor_id="v-1", invoice_number="INV-1", total=118000,
        lines=[invoice_ledger.InvoiceLine("IT support", 1, 100000)], taxable_value=100000, gst_amount=18000,
        invoice_date="2026-10-15"))
    assert result.status == "matched" and result.tds["amount"] == 2000
    insert = next(c for c in db.execute.await_args_list if "INSERT INTO invoice_matches" in str(c.args[0]))
    params = insert.args[1]
    assert (params["tds_section"], params["tds_amount"], params["net"], params["taxable"], params["inv_date"]) == \
        ("194J(a)", 2000, 116000, 100000, date(2026, 10, 15))
    assert tds_service.tds_for_invoice.await_args.kwargs["request_type"] == "saas"


def test_unbooked_invoice_gets_no_tds(monkeypatch):
    monkeypatch.setattr(invoice_ledger, "_load_candidates", AsyncMock(return_value=[]))
    monkeypatch.setattr(invoice_ledger, "_balances", AsyncMock(return_value={}))
    monkeypatch.setattr(invoice_ledger, "_received", AsyncMock(return_value={}))
    spy = AsyncMock()
    monkeypatch.setattr(tds_service, "tds_for_invoice", spy)
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(first=lambda: None))
    result = run(invoice_ledger.book_invoice(db, document_id="d", vendor_id="v", invoice_number="I", total=100, lines=[]))
    assert result.status == "no_match" and result.tds is None and not spy.await_count


# ── MSME deadlines ──────────────────────────────────────────────────────────

def test_msme_due_date_and_status():
    assert msme_due(date(2026, 9, 1), date(2026, 10, 1), 45, 7) == {
        "acceptance_date": "2026-09-01", "due_date": "2026-10-16", "days_left": 15, "status": "ok"}
    assert msme_due(date(2026, 9, 1), date(2026, 10, 10), 45, 7)["status"] == "due_soon"
    assert msme_due(date(2026, 9, 1), date(2026, 10, 17), 45, 7)["status"] == "overdue"


# ── vendor tax profile API ──────────────────────────────────────────────────

VENDOR = SimpleNamespace(id="11111111-1111-1111-1111-111111111111", name="Kaveri", gstin="29AABCD5678E1ZG", country="IN",
                         pan=None, tds_section=None, ldc_rate_pct=None, ldc_valid_until=None, msme_udyam_number=None,
                         msme_category=None, annual_turnover_inr=None)


def client(role="finance"):
    app = FastAPI()
    app.include_router(tds_api.router, prefix="/tds")
    db = MagicMock()

    async def execute(sql, params=None):
        s = str(sql)
        if "FROM vendors" in s:
            return MagicMock(first=lambda: VENDOR)
        if "FROM tds_sections" in s:
            return MagicMock(first=lambda: (1,) if params["s"] in ("194J(a)", "194C") else None)
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute)
    db.commit = AsyncMock()

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=f"{role}@x.test", role=role)
    return TestClient(app), db


URL = f"/tds/vendors/{VENDOR.id}"


def test_profile_accepts_a_consistent_profile_and_audits_it():
    c, db = client()
    r = c.put(URL, json={"pan": "aabcd5678e", "tds_section": "194J(a)", "msme_udyam_number": "UDYAM-KR-03-0012345",
                         "msme_category": "small"})
    assert r.status_code == 200, r.text
    update = next(x for x in db.execute.await_args_list if "UPDATE vendors" in str(x.args[0])).args[1]
    assert update["pan"] == "AABCD5678E" and update["msme_category"] == "small"
    assert db.add.call_args.args[0].performed_by == "finance@x.test"     # from the token


@pytest.mark.parametrize("body,code", [
    ({"pan": "AAB12"}, "invalid_pan"),
    ({"pan": "ZZZZZ9999Z"}, "pan_gstin_mismatch"),
    ({"tds_section": "195"}, "unknown_section"),
    ({"ldc_rate_pct": 0.5}, "ldc_incomplete"),
    ({"msme_udyam_number": "UDYAM-12"}, "invalid_udyam"),
    ({"msme_category": "micro"}, "msme_incomplete"),
])
def test_profile_rejects_inconsistent_values(body, code):
    c, _ = client()
    r = c.put(URL, json=body)
    assert r.status_code == 422 and code in r.text


def test_only_finance_and_admin_edit_profiles_and_sections():
    for role in ("approver", "requester"):
        c, _ = client(role)
        assert c.put(URL, json={}).status_code == 403
        assert c.put("/tds/sections/194C", json={"description": "x", "rate_pct": 1, "rate_no_pan_pct": 20}).status_code == 403
    c, _ = client("requester")
    assert c.get(URL).status_code == 403 and c.get("/tds/msme").status_code == 403


def test_paid_is_recorded_once_and_never_in_the_future():
    c, db = client()

    async def execute(sql, params=None):
        if "FROM invoice_matches" in str(sql):
            return MagicMock(first=lambda: SimpleNamespace(purchase_request_id="22222222-2222-2222-2222-222222222222",
                                                          status="matched", paid_at=None))
        return MagicMock()

    db.execute = AsyncMock(side_effect=execute)
    doc = "33333333-3333-3333-3333-333333333333"
    assert c.post(f"/tds/invoices/{doc}/paid", json={"paid_on": "2099-01-01"}).status_code == 422
    r = c.post(f"/tds/invoices/{doc}/paid", json={})
    assert r.status_code == 200 and r.json()["data"]["paid_by"] == "finance@x.test"

    async def paid(sql, params=None):
        return MagicMock(first=lambda: SimpleNamespace(purchase_request_id=None, status="matched", paid_at=DAY))

    db.execute = AsyncMock(side_effect=paid)
    assert c.post(f"/tds/invoices/{doc}/paid", json={}).status_code == 409
