"""Bulk and email approval ask contract-risk-agent for vendor clearance.

Until Oct 25 they called the public GET /vendors/{id}/clearance without a
login, got 401, and treated every request with a vendor as not cleared:
never bulk-approvable, and email approval always sent the approver to the
portal. They now call /internal/vendors/{id}/clearance with the internal
service token. A failed call still counts as not cleared.
"""
from unittest.mock import patch

import httpx
import pytest

from app.api import email_action
from app.services import bulk_service

VENDOR_ID = "11111111-2222-3333-4444-555555555555"


def _fake_contract_risk_agent(seen):
    """contract-risk-agent's routing: /internal/ wants the token, /vendors/ a JWT."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == f"/internal/vendors/{VENDOR_ID}/clearance":
            if request.headers.get("X-Internal-Service-Token") != "test-internal-token":
                return httpx.Response(403, json={"error": {"code": "forbidden", "message": "no"}})
            return httpx.Response(200, json={"data": {"cleared": True, "final_band": "Low", "reasons": []}})
        return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "login"}})
    real_client = httpx.AsyncClient
    return lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)


@pytest.mark.asyncio
async def test_bulk_clearance_uses_internal_route_and_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-internal-token")
    seen = []
    with patch.object(bulk_service.httpx, "AsyncClient", _fake_contract_risk_agent(seen)):
        data, failed = await bulk_service.fetch_vendor_clearance(VENDOR_ID, 5000.0)
    assert (failed, data["cleared"]) == (False, True)
    assert seen[0].url.params["purpose"] == "purchase"
    assert seen[0].url.params["spend_amount"] == "5000.0"


@pytest.mark.asyncio
async def test_email_clearance_uses_the_same_call(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-internal-token")
    with patch.object(bulk_service.httpx, "AsyncClient", _fake_contract_risk_agent([])):
        band, failed = await email_action._fetch_vendor_risk(VENDOR_ID)
    assert (band, failed) == ("Low", False)


@pytest.mark.asyncio
async def test_wrong_token_fails_closed(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "some-other-token")
    with patch.object(bulk_service.httpx, "AsyncClient", _fake_contract_risk_agent([])):
        data, failed = await bulk_service.fetch_vendor_clearance(VENDOR_ID)
        band, email_failed = await email_action._fetch_vendor_risk(VENDOR_ID)
    assert failed and data["cleared"] is False and data["reasons"] == ["clearance_endpoint_error"]
    assert email_failed and band == "Unrated"
