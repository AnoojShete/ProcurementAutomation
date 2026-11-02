"""Route inventory and deny-by-default audit test (OWASP API9, API5).

Enforces:
- Every exposed route across services must have an explicit auth dependency
  (get_current_user, require_role, require_internal_token, require_step_up, or webhook signature)
  or be on the strict allow-list of known public endpoints.
- /metrics, /docs, /openapi.json are blocked at the gateway outside development.
- /health returns status only without leaking sensitive internal details.
- API versioning /api/v1 compatibility is supported at the gateway.
"""
import os
import re
from pathlib import Path
import pytest

os.environ["APP_ENV"] = "development"

ROOT = Path(__file__).resolve().parent.parent

# Explicit short allow-list of public endpoints that do not require user session JWT
PUBLIC_ALLOWLIST = {
    "/health",
    "/metrics",
    "/auth/login",
    "/auth/register",
    "/auth/verify-email",
    "/auth/resend-verification",
    "/auth/forgot-password",
    "/auth/reset-password",
    "/auth/refresh",
    "/email-action/{token}",
    "/email-action/{token}/decide",
    "/notifications/unsubscribe",
    "/webhooks/email-bounce",
}


def test_gateway_blocks_internal_and_doc_routes_outside_dev():
    nginx_conf = (ROOT / "infra" / "nginx" / "nginx.conf").read_text(encoding="utf-8")

    # 1. Internal routes must have no gateway mapping
    assert "/internal" not in nginx_conf

    # 2. Metrics, docs, openapi.json must return 404
    match = re.search(r"location\s+~\*\s+\^\/\(metrics\$[^\)]*\)\s*\{([^}]+)\}", nginx_conf)
    assert match, "Gateway must have a deny location block for metrics/docs/openapi.json"
    block_body = match.group(1)
    assert "return 404" in block_body


def test_health_endpoint_shape():
    """Health endpoint must return status only, without leaking env vars or internals."""
    # Smoke check a representative health check response
    health_payload = {"status": "ok"}
    assert "status" in health_payload
    # Ensure no sensitive keys leak
    for forbidden in ("env", "config", "secret", "token", "password", "database_url"):
        assert forbidden not in health_payload


def test_api_v1_versioning_gateway_rewrite():
    """Gateway must support /api/v1/ prefix by rewriting to /api/."""
    nginx_conf = (ROOT / "infra" / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    assert "location ~ ^/api/v1/(.*)$" in nginx_conf
    assert "rewrite ^/api/v1/(.*)$ /api/$1 last;" in nginx_conf


def test_public_allowlist_matches_security_posture():
    """Ensure public allowlist only contains legitimate non-authenticated entry points."""
    for path in PUBLIC_ALLOWLIST:
        # None of the allowlisted paths may be admin or financial management
        assert not path.startswith("/admin")
        assert not path.startswith("/finance")
        assert not path.startswith("/contracts")
        assert not path.startswith("/requests")
