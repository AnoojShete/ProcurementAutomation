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
    req.status = "ordered"
    req.status = "fulfilled"
    assert req.status == "fulfilled"


def test_signing_no_longer_skips_delivery():
    req = PurchaseRequest(id="r1", request_type="saas", requested_by="a", department="IT", amount=1, status="approved")
    with pytest.raises(IllegalTransition):
        req.status = "fulfilled"


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


def _req(status, request_type="saas"):
    return PurchaseRequest(id="r1", request_type=request_type, requested_by="a", department="IT", amount=1, status=status)


CONTRACT = SimpleNamespace(id="c1", purchase_request_id="r1", vendor_id=None)


@pytest.mark.asyncio
async def test_contract_signed_orders_approved_request_without_fulfilling(monkeypatch):
    activate = AsyncMock(return_value=True)
    monkeypatch.setattr(consumer, "_activate_license_for_request", activate)
    req = _req("approved")
    session = _session(CONTRACT, req)
    assert await consumer.apply_contract_signed(session, "c1") == "ordered"
    assert req.status == "ordered"
    activate.assert_not_called()   # nothing delivered yet
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_redelivered_contract_signed_does_nothing_twice():
    req = _req("ordered")
    assert await consumer.apply_contract_signed(_session(CONTRACT, req), "c1") == "already_ordered"
    assert req.status == "ordered"


@pytest.mark.asyncio
async def test_contract_signed_after_invoice_keeps_status():
    req = _req("invoice_received")
    assert await consumer.apply_contract_signed(_session(CONTRACT, req), "c1") == "already_invoice_received"
    assert req.status == "invoice_received"  # never moves backwards


@pytest.mark.asyncio
async def test_contract_signed_for_rejected_request_is_dead_lettered_not_applied():
    req = _req("rejected")
    with pytest.raises(PermanentEventError):
        await consumer.apply_contract_signed(_session(CONTRACT, req), "c1")
    assert req.status == "rejected"


@pytest.mark.asyncio
async def test_missing_contract_is_retryable():
    with pytest.raises(LookupError):
        await consumer.apply_contract_signed(_session(None, None), "c-missing")


class TestReceived:
    @pytest.mark.asyncio
    async def test_receiving_an_ordered_request_fulfils_it(self, monkeypatch):
        activate = AsyncMock(return_value=True)
        monkeypatch.setattr(consumer, "_activate_license_for_request", activate)
        req = _req("ordered")
        session = _session(CONTRACT, req)
        assert await consumer.apply_received(session, req, "alice@acme.test") == "fulfilled+fulfilment_applied"
        assert req.status == "fulfilled"
        activate.assert_awaited_once()
        added = [c.args[0] for c in session.add.call_args_list]
        marker = next(x for x in added if getattr(x, "action", None) == consumer.FULFILMENT_MARKER)
        assert marker.performed_by == "alice@acme.test"
        # Also recorded as goods_received (read by the risk rescore after deliveries).
        assert any(getattr(x, "action", None) == "goods_received" for x in added)

    @pytest.mark.asyncio
    async def test_invoice_before_delivery_keeps_status_but_still_fulfils(self, monkeypatch):
        activate = AsyncMock(return_value=True)
        monkeypatch.setattr(consumer, "_activate_license_for_request", activate)
        req = _req("invoice_received")
        assert await consumer.apply_received(_session(CONTRACT, req), req, "a") == "fulfilment_applied"
        assert req.status == "invoice_received"
        activate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cannot_receive_before_the_contract_is_signed(self):
        req = _req("approved")
        with pytest.raises(consumer.NotReceivable):
            await consumer.apply_received(_session(CONTRACT, req), req, "a")
        assert req.status == "approved"

    @pytest.mark.asyncio
    async def test_cannot_receive_twice(self, monkeypatch):
        activate = AsyncMock(return_value=True)
        monkeypatch.setattr(consumer, "_activate_license_for_request", activate)
        req = _req("fulfilled")
        with pytest.raises(consumer.NotReceivable):
            await consumer.apply_received(_session(CONTRACT, req, fulfilled_before=True), req, "a")
        activate.assert_not_called()
