"""1A: refresh token in an httpOnly cookie + double-submit CSRF."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth
from app.database import get_db
from app.security import hash_password
from shared.auth.jwt_tokens import create_access_token, create_refresh_token

USER = SimpleNamespace(id="u1", email="alice@acme.example.com", role="requester", is_active=True,
                       email_verified_at="2026-01-01", token_version=0,
                       hashed_password=hash_password("a-long-enough-pass"))


@pytest.fixture(autouse=True)
def no_lockout_table():
    # The lockout counter is SQL; it's tested in test_account_flows.py.
    with patch.object(auth.lockout, "locked_until", AsyncMock(return_value=None)), \
            patch.object(auth.lockout, "clear", AsyncMock()):
        yield


def _client():
    db = AsyncMock()
    res = MagicMock()
    res.scalars.return_value.first.return_value = USER
    db.execute.return_value = res
    app = FastAPI()
    # Mounted where the browser sees it through nginx, so the cookie's
    # Path=/api/auth applies exactly as in production.
    app.include_router(auth.router, prefix="/api/auth")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, base_url="http://testserver")


def _login(client):
    return client.post("/api/auth/login", json={"email": USER.email, "password": "a-long-enough-pass"})


def _set_cookie_headers(resp):
    return [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]


def test_login_puts_refresh_token_in_httponly_cookie_not_body():
    r = _login(_client())
    assert r.status_code == 200
    body = r.json()["data"]
    assert "access_token" in body and "refresh_token" not in body
    cookies = _set_cookie_headers(r)
    refresh = next(c for c in cookies if c.startswith("refresh_token="))
    csrf = next(c for c in cookies if c.startswith("csrf_token="))
    assert "HttpOnly" in refresh and "SameSite=strict" in refresh and "Path=/api/auth" in refresh
    assert "HttpOnly" not in csrf  # the frontend has to read this one


def test_refresh_needs_matching_csrf_header():
    c = _client()
    _login(c)
    # Cookie present (the browser sends it automatically) but no header —
    # what a cross-site forged request looks like.
    assert c.post("/api/auth/refresh").status_code == 403
    assert c.post("/api/auth/refresh", headers={"X-CSRF-Token": "guess"}).status_code == 403
    r = c.post("/api/auth/refresh", headers={"X-CSRF-Token": c.cookies.get("csrf_token")})
    assert r.status_code == 200 and r.json()["data"]["access_token"]


def test_refresh_token_in_body_no_longer_accepted():
    c = _client()
    token = create_refresh_token(USER.id, USER.email, USER.role)
    c.cookies.set("csrf_token", "x")
    r = c.post("/api/auth/refresh", json={"refresh_token": token}, headers={"X-CSRF-Token": "x"})
    assert r.status_code == 401  # no session cookie


def test_access_token_cannot_be_used_as_refresh_cookie():
    c = _client()
    c.cookies.set("refresh_token", create_access_token(USER.id, USER.email, USER.role))
    c.cookies.set("csrf_token", "x")
    assert c.post("/api/auth/refresh", headers={"X-CSRF-Token": "x"}).status_code == 401


def test_logout_clears_both_cookies_and_needs_csrf():
    c = _client()
    _login(c)
    assert c.post("/api/auth/logout").status_code == 403
    r = c.post("/api/auth/logout", headers={"X-CSRF-Token": c.cookies.get("csrf_token")})
    assert r.status_code == 200
    cleared = _set_cookie_headers(r)
    assert any(h.startswith("refresh_token=") and "Max-Age=0" in h for h in cleared)
    assert any(h.startswith("csrf_token=") and "Max-Age=0" in h for h in cleared)


def test_refresh_cookie_is_not_sent_outside_the_auth_path():
    c = _client()
    _login(c)
    jar = {ck.name: ck.path for ck in c.cookies.jar}
    assert jar["refresh_token"] == "/api/auth" and jar["csrf_token"] == "/"
