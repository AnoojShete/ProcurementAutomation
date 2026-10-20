"""Feature expansion Phase 3: catalog resolution, RFQ scoring and sealed
bids, partial goods receipts and the three-way invoice match. Rule-by-rule
behaviour is in test_rules_wiring.py; the live flow in
tests/e2e/sourcing_flow.py."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import shared.rules_engine as rules_engine
from app.api import rfqs as rfqs_api
from app.database import get_db
from app.services import catalog_service, receipt_service, sourcing_service
from app.services.invoice_ledger import Candidate, InvoiceLine, POLine, Tolerances, evaluate
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser
from shared.lifecycle import IllegalTransition, check_transition


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


# ── RFQ scoring ─────────────────────────────────────────────────────────────

W = sourcing_service.DEFAULT_CRITERIA


def _q(id_, total, **kw):
    return {"id": id_, "vendor_id": f"v{id_}", "total_inr": total, **kw}


def test_cheapest_gets_full_price_score_and_others_proportionally():
    ranked = sourcing_service.score([_q("a", 100000), _q("b", 125000)], W, {})
    by = {r["id"]: r for r in ranked}
    assert by["a"]["scores"]["price"] == 1.0 and by["b"]["scores"]["price"] == 0.8
    assert ranked[0]["id"] == "a" and ranked[0]["rank"] == 1


def test_unknowns_count_as_average_not_zero():
    r = sourcing_service.score([_q("a", 100000)], W, {})[0]["scores"]
    assert r["lead_time"] == r["warranty"] == r["support"] == r["vendor_risk"] == r["delivery_record"] == 0.5


def test_better_terms_and_record_can_beat_a_slightly_lower_price():
    quotes = [_q("a", 100000, lead_time_days=45, warranty_months=12, support_rating=2),
              _q("b", 104000, lead_time_days=7, warranty_months=36, support_rating=5)]
    info = {"va": {"risk_band": "High", "on_time_rate": 0.4}, "vb": {"risk_band": "Low", "on_time_rate": 0.95}}
    ranked = sourcing_service.score(quotes, W, info)
    assert ranked[0]["id"] == "b"
    assert ranked[0]["scores"]["vendor_risk"] == 1.0 and ranked[1]["scores"]["vendor_risk"] == 0.2


def test_tie_on_score_goes_to_the_lower_price():
    ranked = sourcing_service.score([_q("a", 100), _q("b", 100)], {"support": 1}, {})
    assert [r["rank"] for r in ranked] == [1, 2]


@pytest.mark.parametrize("weights,ok", [(W, True), ({"price": 1}, True), ({"price": 0.5}, False),
                                        ({"price": 0.5, "luck": 0.5}, False), ({}, False), ("x", False)])
def test_criteria_validation(weights, ok):
    assert sourcing_service.valid_criteria(weights) is ok


def test_sealed_until_the_deadline_or_until_closed():
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    rfq = SimpleNamespace(sealed=True, status="open", deadline=now + timedelta(hours=1))
    assert sourcing_service.sealed_now(rfq, now) is True
    assert sourcing_service.sealed_now(rfq, now + timedelta(hours=2)) is False
    assert sourcing_service.sealed_now(SimpleNamespace(**{**rfq.__dict__, "status": "closed"}), now) is False
    assert sourcing_service.sealed_now(SimpleNamespace(**{**rfq.__dict__, "sealed": False}), now) is False


@pytest.mark.parametrize("text,ref", [("Ref: RFQ-3f9a2c for laptops", "RFQ-3F9A2C"), ("RFQ 3F9A2C", None),
                                      ("rfq-ABCDEF.", "RFQ-ABCDEF"), (None, None)])
def test_rfq_reference_on_a_quote(text, ref):
    assert sourcing_service.find_rfq_reference(text) == ref


def test_award_spreads_the_total_when_the_quote_has_no_priced_lines():
    rfq = SimpleNamespace(items=[{"name": "Laptop", "quantity": 3}, {"name": "Dock", "quantity": 1}])
    resp = SimpleNamespace(total_inr=400000, line_items=[])
    items = sourcing_service._request_items(rfq, resp)
    assert [i["unit_price"] for i in items] == [100000, 100000]
    resp = SimpleNamespace(total_inr=1, line_items=[{"description": "Laptop", "quantity": 3, "unit_price": 95000}])
    assert sourcing_service._request_items(rfq, resp)[0]["unit_price"] == 95000


# ── three-way match ─────────────────────────────────────────────────────────

def _cand(received):
    return Candidate(request_id="r1", status="ordered", amount=5_000_000,
                     lines=[POLine(0, "Developer laptop", 50, 100000)], received_qty=received)


def test_invoice_for_more_than_received_is_a_variance():
    res = evaluate(5_000_000, [InvoiceLine("Developer laptop", 50, 100000)], [_cand({0: 30})], Tolerances())
    assert res.status == "variance" and "only 30 received" in res.issues[0]


def test_invoice_for_what_was_received_matches():
    res = evaluate(3_000_000, [InvoiceLine("Developer laptop", 30, 100000)], [_cand({0: 30})], Tolerances())
    assert res.status == "partial"


def test_without_receipts_the_match_is_unchanged():
    res = evaluate(5_000_000, [InvoiceLine("Developer laptop", 50, 100000)], [_cand(None)], Tolerances())
    assert res.status == "matched"


def test_second_delivery_lets_the_rest_be_invoiced():
    cand = _cand({0: 50})
    cand.invoiced_qty = {0: 30}
    cand.invoiced_amount = 3_000_000
    res = evaluate(2_000_000, [InvoiceLine("Developer laptop", 20, 100000)], [cand], Tolerances())
    assert res.status == "matched"


# ── goods receipts ──────────────────────────────────────────────────────────

def _req(status="ordered", qty=50):
    return SimpleNamespace(id="r1", status=status, vendor_id="v1", request_type="hardware", updated_at=None,
                           items=[{"name": "Developer laptop", "quantity": qty, "unit_price": 100000}])


def _db(prior=()):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=list(prior))))))
    return db


def test_partial_delivery_moves_ordered_to_partially_received():
    req = _req()
    receipt, outcome = run(receipt_service.record_receipt(
        _db(), req, [{"line_no": 0, "quantity": 30, "asset_tags": ["LT-001", "LT-002"]}], "it@acme.test"))
    assert outcome == "partially_received" and req.status == "partially_received"
    assert receipt.lines == [{"line_no": 0, "quantity": 30, "asset_tags": ["LT-001", "LT-002"]}]


@pytest.mark.parametrize("lines,msg", [
    ([{"line_no": 0, "quantity": 60}], "only 50 still to come"),
    ([{"line_no": 3, "quantity": 1}], "not on this request"),
    ([{"line_no": 0, "quantity": 0}], "nothing received"),
    ([{"line_no": 0, "quantity": 1, "asset_tags": ["a", "b"]}], "more asset tags"),
])
def test_bad_receipts_are_refused(lines, msg):
    with pytest.raises(receipt_service.ReceiptError, match=msg):
        run(receipt_service.record_receipt(_db(), _req(), lines, "it@acme.test"))


def test_nothing_can_be_received_before_the_contract_is_signed():
    with pytest.raises(receipt_service.ReceiptError, match="contract is signed"):
        run(receipt_service.record_receipt(_db(), _req(status="approved"), [{"line_no": 0, "quantity": 1}], "x"))


def test_earlier_deliveries_count_towards_what_is_left():
    prior = [SimpleNamespace(lines=[{"line_no": 0, "quantity": 45}])]
    with pytest.raises(receipt_service.ReceiptError, match="only 5 still to come"):
        run(receipt_service.record_receipt(_db(prior), _req(status="partially_received"),
                                           [{"line_no": 0, "quantity": 10}], "x"))


def test_lifecycle_allows_partial_then_full_but_not_back():
    check_transition("ordered", "partially_received")
    check_transition("partially_received", "fulfilled")
    with pytest.raises(IllegalTransition):
        check_transition("partially_received", "ordered")
    with pytest.raises(IllegalTransition):
        check_transition("approved", "partially_received")


# ── catalog resolution ──────────────────────────────────────────────────────

def _item(**kw):
    base = dict(id="c1", sku="LAP-DEV", name="Developer laptop", category="hardware", vendor_id="v1", unit_price=95000,
                active=True, valid_until=None, inventory_sku=None, license_id=None, lead_time_days=7, warranty_months=36)
    return SimpleNamespace(**{**base, **kw})


def _catalog_db(*items, licence=None, cap=None):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=list(items))))))
    db.get = AsyncMock(return_value=licence)
    return db


def test_catalog_price_vendor_and_type_come_from_the_catalog():
    res = run(catalog_service.resolve_items(_catalog_db(_item()), [{"catalog_item_id": "c1", "quantity": 2, "unit_price": 1}]))
    assert res.amount == 190000 and res.vendor_id == "v1" and res.request_type == "hardware" and res.all_catalog
    assert res.items[0]["unit_price"] == 95000 and res.items[0]["warranty_months"] == 36


def test_expired_or_switched_off_items_cannot_be_ordered():
    for item in (_item(valid_until=date(2020, 1, 1)), _item(active=False)):
        with pytest.raises(catalog_service.CatalogError) as e:
            run(catalog_service.resolve_items(_catalog_db(item), [{"catalog_item_id": "c1", "quantity": 1}]))
        assert e.value.code == "catalog_unavailable"


def test_one_vendor_per_catalog_request():
    db = _catalog_db(_item(), _item(id="c2", vendor_id="v2"))
    with pytest.raises(catalog_service.CatalogError) as e:
        run(catalog_service.resolve_items(db, [{"catalog_item_id": "c1", "quantity": 1}, {"catalog_item_id": "c2", "quantity": 1}]))
    assert e.value.code == "catalog_mixed_vendors"


def test_free_text_lines_are_not_requests_from_the_catalog():
    assert run(catalog_service.resolve_items(_catalog_db(), [{"name": "Laptop", "quantity": 1, "unit_price": 1}])) is None


def test_seat_addon_beyond_the_contract_limit_is_flagged(monkeypatch):
    lic = SimpleNamespace(app_name="Figma", total_seats=48)
    monkeypatch.setattr(catalog_service, "contract_seat_limit", AsyncMock(return_value=50))
    item = _item(category="saas", license_id="l1", name="Figma seat", unit_price=1500)
    res = run(catalog_service.resolve_items(_catalog_db(item, licence=lic), [{"catalog_item_id": "c1", "quantity": 5}]))
    assert res.request_type == "saas" and res.items[0]["seat_addon"] is True
    assert res.flags[0]["code"] == "over_contract_seats" and "48 + 5" in res.flags[0]["message"]


def test_manager_step_dropped_but_finance_steps_stay():
    assert catalog_service.drop_manager_step(["dept_manager", "finance_head"]) == ["finance_head"]


# ── RFQ API: who may see and do what ───────────────────────────────────────

def _client(role):
    app = FastAPI()
    app.include_router(rfqs_api.router, prefix="/rfqs")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=f"{role}@acme.test", role=role)
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.mark.parametrize("role,status", [("requester", 403), ("approver", 200), ("finance", 200)])
def test_who_sees_rfqs(role, status):
    assert _client(role).get("/rfqs/").status_code == status


def test_approver_cannot_issue_an_rfq():
    body = {"title": "x", "department": "IT", "request_type": "hardware", "items": [{"name": "a", "quantity": 1}],
            "vendor_ids": ["11111111-1111-1111-1111-111111111111"], "deadline": "2030-01-01T00:00:00Z"}
    assert _client("approver").post("/rfqs/", json=body).status_code == 403


def test_sealed_view_has_no_amounts(monkeypatch):
    rfq = SimpleNamespace(id="r", reference="RFQ-ABC123", title="t", department="IT", request_type="hardware", items=[],
                          criteria=W, sealed=True, round=1, deadline=datetime.now(timezone.utc) + timedelta(days=1),
                          status="open", created_by="f", awarded_vendor_id=None, awarded_response_id=None,
                          awarded_request_id=None, created_at=None)
    resp = SimpleNamespace(id="x", vendor_id="v1", round=1, total_inr=123456, lead_time_days=5, warranty_months=12,
                           support_rating=4, support_terms="", line_items=[], source="manual", quote_id=None,
                           submitted_at=datetime.now(timezone.utc))
    monkeypatch.setattr(sourcing_service, "invitations", AsyncMock(return_value=[]))
    monkeypatch.setattr(sourcing_service, "responses", AsyncMock(return_value=[resp]))
    out = run(rfqs_api.view(MagicMock(), rfq))
    assert out["sealed_now"] is True and out["comparison"] is None
    assert "total_inr" not in out["responses"][0] and "123456" not in str(out)


def test_received_seat_addon_adds_seats_to_the_licence():
    from app.kafka.consumer import _apply_seat_addons
    lic = SimpleNamespace(id="l1", app_name="Slack", total_seats=45, status="active")
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=lic)))
    req = SimpleNamespace(id="r1", items=[{"seat_addon": True, "license_id": "l1", "quantity": 3},
                                          {"name": "Laptop", "quantity": 1}])
    assert run(_apply_seat_addons(session, req)) == [("l1", 3)]
    assert lic.total_seats == 48
