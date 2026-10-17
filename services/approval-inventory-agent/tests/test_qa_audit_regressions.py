"""QA audit (Oct 17): request input validation, bounded list limits,
malformed ids on approve/reject, and stock reservations released when a
request can't be saved. Each test fails against the code before the fix
(see docs/quality-audit-report.md, QA-01..QA-03, QA-05, QA-10)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import requests as requests_api
from app.schemas import CreatePurchaseRequest
from app.services import approval_service as approval_module
from app.services.approval_service import ApprovalService
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser
from shared.http.error_handlers import register_error_handlers

BASE = {"request_type": "license", "department": "IT", "amount": 100}


def _client(role="requester", svc=None):
    app = FastAPI()
    register_error_handlers(app)  # as in app/main.py
    app.include_router(requests_api.router, prefix="/requests")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u1", email="alice@acme.test", role=role)
    svc = svc or MagicMock()
    app.dependency_overrides[requests_api.get_approval_service] = lambda: svc
    return TestClient(app), svc


class TestAmountValidation:
    @pytest.mark.parametrize("amount", [float("nan"), float("inf"), float("-inf"), -0.01, -1000, 1e10, 1e300])
    def test_rejects_non_finite_negative_and_oversized(self, amount):
        with pytest.raises(ValidationError):
            CreatePurchaseRequest(**{**BASE, "amount": amount})

    @pytest.mark.parametrize("amount", [0, 0.01, 499.99, 9_999_999_999.99])
    def test_accepts_valid_amounts(self, amount):
        assert CreatePurchaseRequest(**{**BASE, "amount": amount}).amount == amount

    def test_nan_in_the_request_body_is_a_422_and_nothing_is_created(self):
        # Python's json accepts the bare NaN token; it used to be stored and
        # then broke GET /requests/ for every user.
        client, svc = _client()
        svc.create_request = AsyncMock()
        r = client.post("/requests/", content='{"request_type":"license","department":"IT","amount":NaN}',
                        headers={"content-type": "application/json"})
        assert r.status_code == 422
        svc.create_request.assert_not_called()


class TestDepartmentAndItems:
    @pytest.mark.parametrize("dept", ["", "   ", "\t\n"])
    def test_blank_department_rejected(self, dept):
        with pytest.raises(ValidationError):
            CreatePurchaseRequest(**{**BASE, "department": dept})

    def test_department_is_trimmed(self):
        assert CreatePurchaseRequest(**{**BASE, "department": "  IT  "}).department == "IT"

    @pytest.mark.parametrize("qty", [-3, 0, "two", "2", 1.5, True, None])
    def test_stock_item_quantity_must_be_a_positive_whole_number(self, qty):
        with pytest.raises(ValidationError):
            CreatePurchaseRequest(**{**BASE, "request_type": "hardware", "items": [{"sku": "S1", "quantity": qty}]})

    def test_stock_item_quantity_defaults_to_one(self):
        CreatePurchaseRequest(**{**BASE, "request_type": "hardware", "items": [{"sku": "S1"}]})

    def test_quote_line_items_without_sku_are_not_restricted(self):
        # Drop-folder requests carry extracted line items (fractional hours,
        # strings); they never reserve stock.
        data = CreatePurchaseRequest(**{**BASE, "items": [{"description": "Support", "quantity": 1.5}]})
        assert data.items[0]["quantity"] == 1.5


class TestListLimitAndMalformedIds:
    @pytest.mark.parametrize("limit", [-1, 0, 1001, 10_000_000])
    def test_out_of_range_limit_is_a_422(self, limit):
        client, svc = _client("approver")
        svc.list_requests = AsyncMock(return_value=[])
        assert client.get(f"/requests/?limit={limit}").status_code == 422
        svc.list_requests.assert_not_called()

    @pytest.mark.parametrize("decision", ["approve", "reject"])
    def test_non_uuid_id_is_a_400_not_a_500(self, decision):
        client, svc = _client("approver")
        svc.process_decision = AsyncMock()
        r = client.post(f"/requests/not-a-uuid/{decision}", json={})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "bad_request"
        svc.process_decision.assert_not_called()


def test_failed_insert_releases_the_stock_it_reserved():
    """reserve_stock commits on its own; if saving the request then fails,
    the reservation used to stay behind for a request that doesn't exist."""
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(
        return_value=SimpleNamespace(available_quantity=5))))
    db.commit = AsyncMock(side_effect=RuntimeError("insert failed"))
    db.rollback = AsyncMock()
    data = CreatePurchaseRequest(request_type="hardware", department="IT", amount=100, requested_by="a@x",
                                 items=[{"sku": "S1", "quantity": 2}])
    release = AsyncMock(return_value=True)
    with patch.object(approval_module, "reserve_stock", AsyncMock(return_value=True)), \
         patch.object(approval_module, "release_reservation", release), \
         patch("shared.rules_engine.get_rule", lambda key, fallback=None: fallback):
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RuntimeError):
                loop.run_until_complete(ApprovalService(db, None, MagicMock()).create_request(data))
        finally:
            loop.close()
    db.rollback.assert_awaited()
    release.assert_awaited_once()
    _, _, sku, _, qty = release.await_args.args
    assert (sku, qty) == ("S1", 2)
