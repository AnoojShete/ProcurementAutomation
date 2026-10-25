"""GET /internal/vendors/{id}/clearance: the vendor clearance check for
other services (bulk and email approval), which have no user login. It needs
the X-Internal-Service-Token header and returns exactly what
clearance.evaluate decides, so there is still one source of clearance."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import internal as internal_api
from app.database import get_db
from shared.http.error_handlers import register_error_handlers

VENDOR_ID = "11111111-2222-3333-4444-555555555555"
URL = f"/internal/vendors/{VENDOR_ID}/clearance"
SANCTIONED = {"cleared": False, "final_band": "Critical", "reasons": ["R-SAN-01"]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-internal-token")
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(internal_api.router, prefix="/internal")
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Service-Token": "wrong"}])
def test_missing_or_wrong_token_is_refused(client, headers):
    with patch.object(internal_api.clearance, "evaluate", AsyncMock(return_value=SANCTIONED)) as evaluate:
        resp = client.get(URL, headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
    evaluate.assert_not_called()


def test_returns_the_clearance_decision(client):
    with patch.object(internal_api.clearance, "evaluate", AsyncMock(return_value=SANCTIONED)) as evaluate:
        resp = client.get(URL, params={"purpose": "purchase", "spend_amount": 5000},
                          headers={"X-Internal-Service-Token": "test-internal-token"})
    assert resp.status_code == 200
    assert resp.json()["data"] == SANCTIONED
    assert evaluate.await_args.kwargs == {"purpose": "purchase", "spend_amount": 5000.0}


def test_unknown_vendor_is_404(client):
    with patch.object(internal_api.clearance, "evaluate", AsyncMock(return_value=None)):
        resp = client.get(URL, headers={"X-Internal-Service-Token": "test-internal-token"})
    assert resp.status_code == 404

