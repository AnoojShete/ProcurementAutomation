"""QA audit (Oct 17): contracts and their PDFs were readable by any
signed-in user. Staff see every contract; a requester only the contracts
on their own purchase requests, and someone else's is a 404. Also the
Documenso webhook's non-JSON body and the bounded list limit.
(docs/quality-audit-report.md QA-04, QA-05, QA-09)"""
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import contracts as contracts_api
from app.api import webhooks as webhooks_api
from app.database import get_db
from app.services import contract_service
from shared.auth import get_current_user
from shared.auth.middleware import CurrentUser
from shared.http.error_handlers import register_error_handlers

CONTRACT_ID = "11111111-1111-1111-1111-111111111111"


def _contract(pr_id="pr-1"):
    return SimpleNamespace(
        id=CONTRACT_ID, purchase_request_id=pr_id, vendor_id=None, template="saas_subscription", version=1,
        status="pending_signature", renewal_type=None, notice_period_days=None, contract_end_date=None,
        generated_at=None, signed_at=None, signed_by=None, esign_provider_ref=None, reconciliation_status=None,
        contract_text="x",
    )


def _client(role, email="alice@acme.test", requester="alice@acme.test"):
    """`requester` is who raised the contract's purchase request."""
    app = FastAPI()
    register_error_handlers(app)
    app.state.kafka_producer = AsyncMock()
    app.include_router(contracts_api.router, prefix="/contracts")
    app.include_router(webhooks_api.router, prefix="/webhooks")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id="u", email=email, role=role)
    db = MagicMock()
    db.get = AsyncMock(return_value=SimpleNamespace(requested_by=requester))
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.fixture
def svc():
    with patch.object(contract_service, "get_contract", AsyncMock(return_value=_contract())), \
         patch.object(contract_service, "list_contracts", AsyncMock(return_value=[])) as list_contracts, \
         patch.object(contract_service, "get_renewals_due", AsyncMock(return_value=[])) as renewals, \
         patch.object(contract_service, "render_document", AsyncMock(return_value=b"%PDF")) as render, \
         patch.object(contract_service, "render_signed_document", AsyncMock(return_value=b"%PDF")) as render_signed, \
         patch.object(contract_service, "get_signature_certificate", AsyncMock(return_value={"ok": 1})), \
         patch.object(contract_service, "was_sent_automatically", AsyncMock(return_value=False)), \
         patch.object(contract_service, "signing_risk", AsyncMock(return_value=None)):
        yield SimpleNamespace(list=list_contracts, renewals=renewals, render=render, render_signed=render_signed)


class TestListScoping:
    def test_requester_lists_only_contracts_on_own_requests(self, svc):
        _client("requester").get("/contracts/")
        assert svc.list.await_args.kwargs["requested_by"] == "alice@acme.test"

    def test_filter_by_purchase_request_id(self, svc):
        _client("requester").get("/contracts/?purchase_request_id=pr-123")
        assert svc.list.await_args.kwargs["purchase_request_id"] == "pr-123"

    def test_requester_renewals_are_scoped_too(self, svc):
        _client("requester").get("/contracts/renewals-due?within_days=30")
        assert svc.renewals.await_args.kwargs["requested_by"] == "alice@acme.test"

    @pytest.mark.parametrize("role", ["approver", "finance", "admin"])
    def test_staff_list_everything(self, svc, role):
        _client(role, email="staff@acme.test").get("/contracts/")
        assert svc.list.await_args.kwargs["requested_by"] is None

    @pytest.mark.parametrize("limit", [-1, 0, 1001])
    def test_out_of_range_limit_is_a_422(self, svc, limit):
        assert _client("finance").get(f"/contracts/?limit={limit}").status_code == 422
        svc.list.assert_not_awaited()


class TestReadScoping:
    PATHS = ["", "/document", "/signed-document", "/signature-certificate"]

    @pytest.mark.parametrize("path", PATHS)
    def test_requester_gets_404_for_someone_elses_contract(self, svc, path):
        r = _client("requester", requester="bob@acme.test").get(f"/contracts/{CONTRACT_ID}{path}")
        assert r.status_code == 404
        svc.render.assert_not_awaited()
        svc.render_signed.assert_not_awaited()

    @pytest.mark.parametrize("path", PATHS)
    def test_requester_reads_own_contract(self, svc, path):
        r = _client("requester", email="Alice@Acme.test", requester="alice@acme.test").get(f"/contracts/{CONTRACT_ID}{path}")
        assert r.status_code == 200, r.text

    @pytest.mark.parametrize("path", PATHS)
    def test_staff_read_any_contract(self, svc, path):
        r = _client("finance", email="fin@acme.test", requester="bob@acme.test").get(f"/contracts/{CONTRACT_ID}{path}")
        assert r.status_code == 200, r.text

    def test_contract_without_a_request_is_staff_only(self):
        db = MagicMock(get=AsyncMock())
        loop = asyncio.new_event_loop()
        try:
            assert loop.run_until_complete(
                contract_service.is_requester_of(db, _contract(pr_id=None), "alice@acme.test")) is False
        finally:
            loop.close()
        db.get.assert_not_awaited()


def test_documenso_webhook_rejects_non_json_with_400():
    r = _client("finance").post("/webhooks/documenso", content=b"not json",
                                headers={"content-type": "application/json"})
    assert r.status_code == 400
