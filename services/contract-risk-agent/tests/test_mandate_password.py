"""Signing-mandate password re-check (MANDATE-1). The check must reach
auth-service's /auth/verify-password on its real address with the caller's
own token, refuse a wrong password, and never fall back to fixed passwords
when auth-service can't be reached."""
import httpx
import pytest
from fastapi import HTTPException

from app.api import mandates

TOKEN = "Bearer user-jwt"


@pytest.fixture
def auth_service(monkeypatch):
    """Routes the module's httpx client to a fake auth-service."""
    calls = []
    answer = {"status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if answer["status"] == "down":
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(answer["status"], json={})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(mandates.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.delenv("AUTH_SERVICE_URL", raising=False)
    return calls, answer


@pytest.mark.asyncio
async def test_right_password_calls_auth_service_on_8005(auth_service):
    calls, _ = auth_service
    await mandates.verify_password_with_auth(TOKEN, "the real password")
    [req] = calls
    assert str(req.url) == "http://auth-service:8005/auth/verify-password"
    assert req.headers["authorization"] == TOKEN
    assert b"the real password" in req.content


@pytest.mark.asyncio
async def test_wrong_password_is_refused(auth_service):
    _, answer = auth_service
    answer["status"] = 400
    with pytest.raises(HTTPException) as e:
        await mandates.verify_password_with_auth(TOKEN, "wrong")
    assert e.value.status_code == 400 and e.value.detail["code"] == "wrong_password"


@pytest.mark.asyncio
async def test_locked_account_is_429(auth_service):
    _, answer = auth_service
    answer["status"] = 429
    with pytest.raises(HTTPException) as e:
        await mandates.verify_password_with_auth(TOKEN, "wrong")
    assert e.value.status_code == 429


@pytest.mark.parametrize("password", ["password123", "FinancePass123!", "AdminPass123!"])
@pytest.mark.asyncio
async def test_no_fixed_passwords_when_auth_service_is_down(auth_service, password):
    _, answer = auth_service
    answer["status"] = "down"
    with pytest.raises(HTTPException) as e:
        await mandates.verify_password_with_auth(TOKEN, password)
    assert e.value.status_code == 503
