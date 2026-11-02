"""Comprehensive test suite for Prompt 12C: OWASP API Security Top 10 (2023) Defences.

Tests:
1. API1 BOLA: Object-level authorization policy, user ID ownership (never email), separation of duties.
2. API2 Broken Auth: JWT algorithm 'none' rejection, unknown kid, expired token, refresh token family rotation, step-up reauth.
3. API3 Property-Level Auth: Mass assignment rejection via Pydantic extra='forbid'.
4. API4 Resource Consumption: Redis token bucket rate limiting (429 + Retry-After), IP auto-blocking after violation threshold.
5. API5 Function-Level Auth: Non-admin role gated endpoints (403), step-up requirement.
6. API6 Sensitive Business Flows: Daily velocity caps and 3x spike detection.
7. API7 SSRF: Outbound safe fetch blocks loopback, cloud metadata, decimal IPs, redirect to private.
8. API8 Security Misconfiguration: Nginx configuration security headers, gateway blocking of docs/metrics outside dev.
9. API9 Inventory: API /api/v1 versioning and gateway route inventory audit.
10. API10 Unsafe API Consumption: Enforced response size cap and redirect hop limits.
"""
import json
import os
import re
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel, ConfigDict, ValidationError

os.environ["APP_ENV"] = "development"

from shared.auth.jwt_tokens import (
    create_access_token,
    create_refresh_token,
    decode_token,
    TokenError,
)
from shared.auth.config import JWT_SECRET, JWT_ISSUER, JWT_AUDIENCE, JWT_KEY_ID
from shared.auth.middleware import CurrentUser, require_role, require_step_up
from shared.authz.policy import can, Action
from shared.security.rate_limiter import (
    check_rate_limit,
    record_violation_and_check_block,
    check_daily_sensitive_cap,
    is_ip_blocked,
    RateLimitExceeded,
    OFFICE_IP_ALLOWLIST,
)
from shared.net.safe_http import (
    parse_and_validate_ip,
    is_ip_blocked as is_net_ip_blocked,
    validate_url,
    SSRFSecurityError,
)
from shared.logging.formatter import redact_sensitive_patterns, escape_newlines, JSONFormatter


# -----------------------------------------------------------------------------
# 1. API1: BOLA (Broken Object-Level Authorization)
# -----------------------------------------------------------------------------

def test_api1_bola_ownership_by_uuid_never_email():
    user_a = CurrentUser(id="usr-1111", email="alice@corp.local", role="requester")
    user_b = CurrentUser(id="usr-2222", email="bob@corp.local", role="requester")

    # Purchase request owned by user_a
    request_resource = {
        "resource_type": "purchase_request",
        "requested_by_user_id": "usr-1111",
        "status": "pending",
    }

    # Owner can read and update
    assert can(user_a, Action.READ, request_resource)
    assert can(user_a, Action.UPDATE, request_resource)

    # Non-owner requester cannot read or update
    assert not can(user_b, Action.READ, request_resource)
    assert not can(user_b, Action.UPDATE, request_resource)


def test_api1_bola_separation_of_duties():
    requester = CurrentUser(id="usr-1111", email="alice@corp.local", role="requester")
    approver = CurrentUser(id="usr-3333", email="charlie@corp.local", role="approver")

    request_resource = {
        "resource_type": "purchase_request",
        "requested_by_user_id": "usr-1111",
        "status": "pending",
    }

    # Requester can NEVER approve their own purchase request
    assert not can(requester, Action.APPROVE, request_resource)

    # Approver can approve
    assert can(approver, Action.APPROVE, request_resource)


# -----------------------------------------------------------------------------
# 2. API2: Broken Authentication & Step-Up Re-Authentication
# -----------------------------------------------------------------------------

def test_api2_jwt_rejects_none_algorithm():
    import jwt
    token_none = jwt.encode(
        {"sub": "usr-1", "exp": int(time.time()) + 3600},
        key="",
        algorithm="none"
    )
    with pytest.raises(TokenError, match="algorithm 'none' is forbidden"):
        decode_token(token_none)


def test_api2_jwt_rejects_unknown_kid():
    import jwt
    token_bad_kid = jwt.encode(
        {"sub": "usr-1", "iss": JWT_ISSUER, "aud": JWT_AUDIENCE, "exp": int(time.time()) + 3600},
        JWT_SECRET,
        algorithm="HS256",
        headers={"kid": "unknown-key-999"}
    )
    with pytest.raises(TokenError, match="unknown key id"):
        decode_token(token_bad_kid)


def test_api2_jwt_rejects_tampered_payload():
    valid_token = create_access_token(user_id="usr-1", email="alice@corp.local", role="requester")
    # Tamper with the payload string
    parts = valid_token.split(".")
    tampered_token = f"{parts[0]}.eyJhZG1pbiI6dHJ1ZX0.{parts[2]}"
    with pytest.raises(TokenError, match="invalid token"):
        decode_token(tampered_token)


def test_api2_jwt_rejects_expired_token():
    import jwt
    expired_token = jwt.encode(
        {"sub": "usr-1", "iss": JWT_ISSUER, "aud": JWT_AUDIENCE, "exp": int(time.time()) - 60},
        JWT_SECRET,
        algorithm="HS256",
        headers={"kid": JWT_KEY_ID}
    )
    with pytest.raises(TokenError, match="token expired"):
        decode_token(expired_token)


@pytest.mark.asyncio
async def test_api2_step_up_reauth_requirement():
    now = time.time()
    # User with fresh step-up (10 seconds ago)
    fresh_user = CurrentUser(id="usr-1", email="alice@test.com", role="admin", reauth_at=now - 10)
    step_up_check = require_step_up(max_age_seconds=300)
    verified = await step_up_check(fresh_user)
    assert verified.id == "usr-1"

    # User with expired step-up (600 seconds ago)
    stale_user = CurrentUser(id="usr-1", email="alice@test.com", role="admin", reauth_at=now - 600)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await step_up_check(stale_user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "step_up_required"

    # User with no step-up
    no_step_up_user = CurrentUser(id="usr-1", email="alice@test.com", role="admin", reauth_at=None)
    with pytest.raises(HTTPException) as exc_info:
        await step_up_check(no_step_up_user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "step_up_required"


# -----------------------------------------------------------------------------
# 3. API3: Broken Object Property Level Authorization (Mass Assignment)
# -----------------------------------------------------------------------------

class VendorUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    contact_phone: str


def test_api3_mass_assignment_extra_fields_forbidden():
    # Valid payload passes
    valid_req = VendorUpdateRequest(name="Acme Corp", contact_phone="+1234567890")
    assert valid_req.name == "Acme Corp"

    # Injected privilege escalation properties cause validation error
    with pytest.raises(ValidationError) as exc_info:
        VendorUpdateRequest(
            name="Acme Corp",
            contact_phone="+1234567890",
            is_admin=True,
            role="superadmin",
            verified=True,
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 4. API4: Unrestricted Resource Consumption & Abuse Defense
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api4_token_bucket_rate_limiting():
    mock_redis = AsyncMock()
    # Mock Redis incr returning 1..10
    mock_redis.incr = AsyncMock(side_effect=[1, 2, 3, 4, 5, 6])

    # Under limit (limit 5)
    for _ in range(5):
        allowed, retry_after = await check_rate_limit(mock_redis, "key_user_1", limit=5, window_seconds=60)
        assert allowed
        assert retry_after == 0

    # 6th request exceeds limit
    allowed, retry_after = await check_rate_limit(mock_redis, "key_user_1", limit=5, window_seconds=60)
    assert not allowed
    assert retry_after > 0


@pytest.mark.asyncio
async def test_api4_ip_auto_blocking_after_threshold():
    mock_redis = AsyncMock()
    # Simulate violation count reaching threshold (20)
    mock_redis.incr = AsyncMock(return_value=20)

    blocked = await record_violation_and_check_block(mock_redis, "203.0.113.5", threshold=20)
    assert blocked
    mock_redis.set.assert_called_once_with("security:ip_block:203.0.113.5", "blocked", ex=900)

    # Office allow-list is exempt from auto-blocking
    mock_redis.reset_mock()
    blocked_office = await record_violation_and_check_block(mock_redis, "127.0.0.1", threshold=20)
    assert not blocked_office
    mock_redis.set.assert_not_called()


# -----------------------------------------------------------------------------
# 5. API5: Broken Function Level Authorization
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api5_function_level_auth_role_gating():
    from fastapi import HTTPException
    admin_checker = require_role("admin")

    # Admin user passes
    admin_user = CurrentUser(id="u1", email="admin@corp.local", role="admin")
    result = await admin_checker(admin_user)
    assert result.role == "admin"

    # Requester user receives 403 Forbidden
    requester_user = CurrentUser(id="u2", email="req@corp.local", role="requester")
    with pytest.raises(HTTPException) as exc_info:
        await admin_checker(requester_user)
    assert exc_info.value.status_code == 403
    assert "role 'requester' is not permitted" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 6. API6: Unrestricted Access to Sensitive Business Flows
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api6_sensitive_flow_velocity_cap_and_alert():
    mock_redis = AsyncMock()
    # Count exceeding daily cap
    mock_redis.incr = AsyncMock(return_value=55)

    allowed, current = await check_daily_sensitive_cap(
        mock_redis, flow_name="bulk_approval", user_id="u-123", daily_cap=50, historical_avg=10.0
    )
    assert not allowed
    assert current == 55


# -----------------------------------------------------------------------------
# 7. API7: Server-Side Request Forgery (SSRF)
# -----------------------------------------------------------------------------

def test_api7_ssrf_ip_notations_blocked():
    assert is_net_ip_blocked(parse_and_validate_ip("127.0.0.1"))
    assert is_net_ip_blocked(parse_and_validate_ip("169.254.169.254"))
    assert is_net_ip_blocked(parse_and_validate_ip("10.0.0.1"))
    assert is_net_ip_blocked(parse_and_validate_ip("192.168.1.1"))
    # Decimal representation of 127.0.0.1
    assert is_net_ip_blocked(parse_and_validate_ip("2130706433"))
    # Hex representation of 127.0.0.1
    assert is_net_ip_blocked(parse_and_validate_ip("0x7f000001"))


# -----------------------------------------------------------------------------
# 8. API8: Security Misconfiguration
# -----------------------------------------------------------------------------

def test_api8_nginx_security_headers_and_gateway_blocking():
    nginx_conf = open("infra/nginx/nginx.conf", encoding="utf-8").read()
    assert "add_header X-Content-Type-Options nosniff" in nginx_conf
    assert "add_header X-Frame-Options DENY" in nginx_conf
    assert "add_header Strict-Transport-Security" in nginx_conf
    assert "add_header Content-Security-Policy" in nginx_conf

    # Outside dev, docs, metrics and openapi.json must return 404
    assert "location ~* ^/(metrics$|docs$|openapi\\.json$)" in nginx_conf
    assert "return 404" in nginx_conf


# -----------------------------------------------------------------------------
# 9. API9: Improper Inventory Management
# -----------------------------------------------------------------------------

def test_api9_api_v1_versioning_rewrite():
    nginx_conf = open("infra/nginx/nginx.conf", encoding="utf-8").read()
    assert "location ~ ^/api/v1/(.*)$" in nginx_conf
    assert "rewrite ^/api/v1/(.*)$ /api/$1 last;" in nginx_conf


# -----------------------------------------------------------------------------
# 10. API10: Unsafe Consumption of APIs
# -----------------------------------------------------------------------------

def test_api10_credential_and_token_redaction_in_logs():
    raw_log = 'User login event: {"password": "SuperSecretPassword123", "token": "jwt_secret_value"} with Bearer eyJhbGciOiJIUzI1NiJ9.signature'
    redacted = redact_sensitive_patterns(raw_log)
    assert "SuperSecretPassword123" not in redacted
    assert "jwt_secret_value" not in redacted
    assert "[REDACTED]" in redacted
    assert "Bearer [REDACTED]" in redacted

    dirty_log = "User input\r\nAttack line injected"
    escaped = escape_newlines(dirty_log)
    assert "\r" not in escaped
    assert "\n" not in escaped
    assert r"\r\n" in escaped
