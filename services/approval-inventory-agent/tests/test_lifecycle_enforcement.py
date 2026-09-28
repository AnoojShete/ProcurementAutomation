"""The state machine is enforced on the model, and the contract.signed
effect is idempotent — the two properties that make redelivery and the
reconciler safe."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.kafka import consumer
from app.models import PurchaseRequest
from shared.eventing import PermanentEventError
from shared.lifecycle import IllegalTransition


def test_model_rejects_illegal_transition():
    req = PurchaseRequest(id="r1", request_type="saas", requested_by="a", department="IT", amount=1, status="rejected")
    with pytest.raises(IllegalTransition):
        req.status = "invoice_received"


def test_model_allows_legal_and_repeated_transition():
    req = PurchaseRequest(id="r1", request_type="saas", requested_by="a", department="IT", amount=1, status="approved")
    req.status = "approved"
    req.status = "fulfilled"
    assert req.status == "fulfilled"


def _session(contract, req, fulfilled_before=False):
    session = AsyncMock()
    session.add = MagicMock()

    async def execute(stmt, *a, **k):
        res = MagicMock()
        target = str(stmt)
        res.scalar_one_or_none.return_value = contract if "FROM contracts" in target else req
        res.first.return_value = ("marker",) if (fulfilled_before and "audit_log" in target) else None
        return res

    session.execute = execute
    return session


@pytest.mark.asyncio
async def test_contract_signed_fulfils_approved_request(monkeypatch):
    monkeypatch.setattr(consumer, "_activate_license_for_request", AsyncMock(return_value=True))
    req = PurchaseRequest(id="r1", request_type="saas", requested_by="a", department="IT", amount=1, status="approved")
    contract = SimpleNamespace(id="c1", purchase_request_id="r1", vendor_id=None)
    session = _session(contract, req)
    assert await consumer.apply_contract_signed(session, "c1") == "fulfilled+fulfilment_applied"
    assert req.status == "fulfilled"
    consumer._activate_license_for_request.assert_awaited_once()
    assert session.add.call_args.args[0].action == consumer.FULFILMENT_MARKER


@pytest.mark.asyncio
async def test_redelivered_contract_signed_does_nothing_twice(monkeypatch):
    activate = AsyncMock(return_value=True)
    monkeypatch.setattr(consumer, "_activate_license_for_request", activate)
    req = PurchaseRequest(id="r1", request_type="saas", requested_by="a", department="IT", amount=1, status="fulfilled")
    contract = SimpleNamespace(id="c1", purchase_request_id="r1", vendor_id=None)
    assert await consumer.apply_contract_signed(_session(contract, req, fulfilled_before=True), "c1") == "already_fulfilled"
    activate.assert_not_called()


@pytest.mark.asyncio
async def test_contract_signed_after_invoice_keeps_status_but_still_fulfils(monkeypatch):
    activate = AsyncMock(return_value=True)
    monkeypatch.setattr(consumer, "_activate_license_for_request", activate)
    req = PurchaseRequest(id="r1", request_type="saas", requested_by="a", department="IT", amount=1, status="invoice_received")
    contract = SimpleNamespace(id="c1", purchase_request_id="r1", vendor_id=None)
    assert await consumer.apply_contract_signed(_session(contract, req), "c1") == "fulfilment_applied"
    assert req.status == "invoice_received"  # never moves backwards
    activate.assert_awaited_once()          # but the license still gets activated


@pytest.mark.asyncio
async def test_contract_signed_for_rejected_request_is_dead_lettered_not_applied():
    req = PurchaseRequest(id="r1", request_type="saas", requested_by="a", department="IT", amount=1, status="rejected")
    contract = SimpleNamespace(id="c1", purchase_request_id="r1", vendor_id=None)
    with pytest.raises(PermanentEventError):
        await consumer.apply_contract_signed(_session(contract, req), "c1")
    assert req.status == "rejected"


@pytest.mark.asyncio
async def test_missing_contract_is_retryable():
    with pytest.raises(LookupError):
        await consumer.apply_contract_signed(_session(None, None), "c-missing")
