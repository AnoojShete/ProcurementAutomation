"""Security audit (Sep 26): ledger controls, request scoping, approval
signal race. Each test fails against the code before the fix."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import invoices, requests as requests_api
from app.database import get_db
from app.services import invoice_ledger
from app.services.approval_service import ApprovalService
from app.workflows.approval_workflow import ApprovalSignal, signal_applies
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser

MATCH = {"document_id": "d1", "vendor_id": "v1", "total": 100.0, "lines": []}


def _client(role, email="alice@acme.test", svc=None):
    app = FastAPI()
    app.include_router(invoices.router, prefix="/invoices")
    app.include_router(requests_api.router, prefix="/requests")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u-" + role, email=email, role=role)
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    if svc is not None:
        app.dependency_overrides[requests_api.get_approval_service] = lambda: svc
    return TestClient(app)


class TestLedgerControls:
    def test_finance_cannot_release_payment_holds_directly(self):
        # H7: holds may only lift through bank-detail verification.
        assert _client("finance").post("/invoices/release-holds/v1").status_code == 403
        assert _client("admin").post("/invoices/release-holds/v1").status_code == 403

    def test_pipeline_can_release_holds(self):
        with patch.object(invoice_ledger, "release_payment_holds", AsyncMock(return_value=2)):
            r = _client("service").post("/invoices/release-holds/v1")
        assert r.status_code == 200 and r.json()["data"]["released"] == 2

    def test_staff_cannot_book_invoices(self):
        # H8: booking spends a request's balance; only the pipeline books.
        book = AsyncMock()
        with patch.object(invoice_ledger, "book_invoice", book):
            r = _client("finance").post("/invoices/match", json=MATCH)
        assert r.status_code == 403
        book.assert_not_called()

    def test_staff_can_simulate(self):
        result = invoice_ledger.MatchResult("no_match")
        with patch.object(invoice_ledger, "book_invoice", AsyncMock(return_value=result)) as book:
            r = _client("finance").post("/invoices/match?dry_run=true", json=MATCH)
        assert r.status_code == 200
        assert book.call_args.kwargs["dry_run"] is True


class TestRequestScoping:
    def _svc(self, req=None):
        svc = MagicMock()
        svc.list_requests = AsyncMock(return_value=[])
        svc.get_request_with_history = AsyncMock(return_value=req)
        return svc

    def test_requester_lists_only_own_requests(self):
        svc = self._svc()
        _client("requester", svc=svc).get("/requests/")
        assert svc.list_requests.call_args.kwargs["requested_by"] == "alice@acme.test"

    def test_approver_lists_all(self):
        svc = self._svc()
        _client("approver", "appr@acme.test", svc=svc).get("/requests/")
        assert svc.list_requests.call_args.kwargs["requested_by"] is None

    def test_requester_cannot_read_someone_elses_request(self):
        svc = self._svc(SimpleNamespace(requested_by="bob@acme.test"))
        assert _client("requester", svc=svc).get("/requests/r1").status_code == 404

    def test_requester_cannot_search_all_requests(self):
        assert _client("requester").get("/requests/search?vendor_id=v1").status_code == 403


class TestApprovalSignalRace:
    def test_signal_only_applies_to_the_level_it_was_authorised_for(self):
        # H2: a second click / concurrent approval must not approve the next level.
        assert signal_applies(ApprovalSignal("approved", "a@x", None, 0), 0)
        assert not signal_applies(ApprovalSignal("approved", "a@x", None, 0), 1)
        assert signal_applies(ApprovalSignal("approved", "a@x"), 1)  # pre-existing signals without a level

    @pytest.mark.asyncio
    async def test_decision_signal_carries_the_authorised_level(self, monkeypatch):
        req = SimpleNamespace(
            id="r1", status="pending_approval", approval_chain=["dept_manager", "finance_head"],
            current_approver_index=1, requested_by="req@x", amount=100, approval_history=[],
        )
        db = AsyncMock()
        svc = ApprovalService(db, None, None)
        monkeypatch.setattr(svc, "get_request_with_history", AsyncMock(return_value=req))
        from app.services import approval_authority
        monkeypatch.setattr(approval_authority, "check_request_authority",
                            AsyncMock(return_value=approval_authority.AuthorityDecision(True, "OK", "ok")))
        handle = MagicMock()
        handle.signal = AsyncMock()
        client = MagicMock()
        client.get_workflow_handle.return_value = handle
        with patch("temporalio.client.Client.connect", AsyncMock(return_value=client)):
            await svc.process_decision("r1", "approved", SimpleNamespace(decided_by="fin@x", comments=None))
        payload = handle.signal.call_args.args[1]
        assert payload["level_index"] == 1


def test_showcase_mode_off_in_production(monkeypatch):
    # M7: fault-injection endpoints only in development.
    from app.config import Settings
    monkeypatch.setenv("APP_ENV", "production")
    assert Settings().showcase_mode is False
    monkeypatch.setenv("APP_ENV", "development")
    assert Settings().showcase_mode is True


def test_order_summaries_are_staff_only():
    from app.api import orders
    app = FastAPI()
    app.include_router(orders.router, prefix="/orders")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email="r@x", role="requester")
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    assert TestClient(app).get("/orders/summary/latest").status_code == 403
