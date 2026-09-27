"""Refresh token in an httpOnly cookie, with double-submit CSRF protection.

Two cookies are set at login:

  refresh_token  httpOnly — JavaScript can't read it, so a script injected
                 into the page (XSS) can't steal the long-lived login.
                 SameSite=Strict and scoped to /api/auth, so the browser
                 only sends it to the auth endpoints, and never on a
                 request started by another site.
  csrf_token     readable by JavaScript. The frontend copies it into an
                 X-CSRF-Token header; /auth/refresh and /auth/logout accept
                 the request only if header and cookie match. Another site
                 can make the browser send cookies but can't read them, so
                 it can't produce the matching header ("double-submit").

The short-lived access token is still returned in the response body and
kept in memory only.
"""
import hmac
import os
import secrets

from fastapi import HTTPException, Request, Response

from shared.auth.config import JWT_REFRESH_EXPIRY_DAYS
from shared.runtime_env import is_development

REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
# The path the browser sees (through the nginx gateway).
REFRESH_COOKIE_PATH = os.environ.get("AUTH_COOKIE_PATH", "/api/auth")


def _secure() -> bool:
    # Browsers only send Secure cookies over HTTPS (or to localhost).
    # Development defaults to off so the demo also works on http://<LAN IP>.
    default = "false" if is_development() else "true"
    return os.environ.get("AUTH_COOKIE_SECURE", default).lower() == "true"


def set_session_cookies(response: Response, refresh_token: str) -> None:
    max_age = JWT_REFRESH_EXPIRY_DAYS * 24 * 3600
    response.set_cookie(
        REFRESH_COOKIE, refresh_token, max_age=max_age, path=REFRESH_COOKIE_PATH,
        httponly=True, secure=_secure(), samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE, secrets.token_urlsafe(32), max_age=max_age, path="/",
        httponly=False, secure=_secure(), samesite="strict",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, secure=_secure(), httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=_secure(), samesite="strict")


def require_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="missing or invalid CSRF token")


def refresh_token_from(request: Request) -> str:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="no session")
    return token
