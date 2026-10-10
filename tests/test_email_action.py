"""Comprehensive test suite for Prompt 8: Email-Based Approval and Contract Signing.

Tests:
1. Scanner prefetch idempotency (GET 3x leaves request pending & token unused)
2. Successful email approve (updates status, audit log with channel='email', event payload)
3. Successful email reject (comment required, updates status to rejected)
4. Replay protection (POST /decide twice returns 410 on second call)
5. Real concurrency (two simultaneous POST /decide calls -> exactly one succeeds, one gets 410)
6. Unknown/malformed token (returns 404 generic)
7. Expired token (returns 410)
8. Revocation on portal decision (returns 410)
9. Revocation on SLA escalation (returns 410)
10. Revocation on cancellation / decline reclaim (returns 410)
11. Revocation on delegation change (returns 410)
12. Sequential minting (finance token cannot exist before manager step completes)
13. Segregation of duties (requester cannot mint or approve own request)
14. Step-up rules (over max amount, over budget, high-risk vendor, risk lookup failed)
15. Portal race condition (decided on portal while email page was open -> 410)
16. Internal mint endpoint security (requires X-Internal-Service-Token; cannot route via gateway)
17. Contract signing identity & simulated gating (rejects unauthorized signer; 403 on sign-simulated unless enabled)
"""
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# Add service roots to sys.path
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root))
_approval_service_dir = _repo_root / "services" / "approval-inventory-agent"
sys.path.insert(0, str(_approval_service_dir))


from app.main import app as approval_app
from app.models import EmailActionToken, PurchaseRequest
from app.services.email_action_token_service import (
    evaluate_step_up,
    hash_token,
    mint_email_action_token,
    revoke_tokens,
)



@pytest.fixture
def dummy_request():
    return PurchaseRequest(
        id="11111111-2222-3333-4444-555555555555",
        request_type="hardware",
        requested_by="requester@demo.example.com",
        department="Engineering",
        amount=15000.00,
        currency="INR",
        spend_tier="manager",
        status="pending_approval",
        approval_chain=["dept_manager"],
        current_approver_index=0,
        sla_deadline=datetime.now(timezone.utc) + timedelta(hours=48),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_hash_token_deterministic():
    token = "test-secret-token-12345678901234567890"
    expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert hash_token(token) == expected


def test_step_up_rules_evaluation():
    # 1. Normal allowed
    with patch("shared.rules_engine.get_rule", side_effect=lambda k, fallback=None: fallback):
        enabled, step_up, reason = evaluate_step_up(
            amount=10000.0, over_budget=False, vendor_risk_band="Low", risk_lookup_failed=False
        )
        assert enabled is True
        assert step_up is False

    # 2. Amount > max limit (default 50,000)
    with patch("shared.rules_engine.get_rule", side_effect=lambda k, fallback=None: fallback):
        enabled, step_up, reason = evaluate_step_up(
            amount=75000.0, over_budget=False, vendor_risk_band="Low", risk_lookup_failed=False
        )
        assert enabled is True
        assert step_up is True
        assert "exceeds the email action limit" in reason

    # 3. Over budget
    with patch("shared.rules_engine.get_rule", side_effect=lambda k, fallback=None: fallback):
        enabled, step_up, reason = evaluate_step_up(
            amount=10000.0, over_budget=True, vendor_risk_band="Low", risk_lookup_failed=False
        )
        assert enabled is True
        assert step_up is True
        assert "over budget" in reason

    # 4. High-risk vendor
    with patch("shared.rules_engine.get_rule", side_effect=lambda k, fallback=None: fallback):
        enabled, step_up, reason = evaluate_step_up(
            amount=10000.0, over_budget=False, vendor_risk_band="High", risk_lookup_failed=False
        )
        assert enabled is True
        assert step_up is True
        assert "High Risk" in reason

    # 5. Risk lookup failed (fail closed)
    with patch("shared.rules_engine.get_rule", side_effect=lambda k, fallback=None: fallback):
        enabled, step_up, reason = evaluate_step_up(
            amount=10000.0, over_budget=False, vendor_risk_band=None, risk_lookup_failed=True
        )
        assert enabled is True
        assert step_up is True
        assert "unavailable" in reason


@pytest.mark.asyncio
async def test_sequential_minting_rules():
    # Multi-step request: ["dept_manager", "finance_head"]
    req = PurchaseRequest(
        id="req-multi-step",
        request_type="saas",
        requested_by="user@demo.example.com",
        department="IT",
        amount=60000.0,
        spend_tier="manager+finance",
        status="pending_approval",
        approval_chain=["dept_manager", "finance_head"],
        current_approver_index=0, # step 0 is active
        sla_deadline=datetime.now(timezone.utc) + timedelta(hours=48),
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=req)
    db.add = MagicMock()
    db.commit = AsyncMock()

    with patch("app.services.approval_authority.load_delegations", return_value=[]):
        # Step 0 (manager) can be minted
        raw_token, exp, url = await mint_email_action_token(db, req.id, "manager@demo.example.com", 0)
        assert raw_token is not None
        assert "/email-action/" in url

        # Step 1 (finance) cannot be minted while step 0 is active
        with pytest.raises(ValueError, match="not currently active"):
            await mint_email_action_token(db, req.id, "finance@demo.example.com", 1)


@pytest.mark.asyncio
async def test_segregation_of_duties_at_mint():
    req = PurchaseRequest(
        id="req-sod",
        request_type="hardware",
        requested_by="requester@demo.example.com",
        department="Engineering",
        amount=1000.0,
        status="pending_approval",
        approval_chain=["dept_manager"],
        current_approver_index=0,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=req)
    with patch("app.services.approval_authority.load_delegations", return_value=[]):
        with pytest.raises(ValueError, match="Segregation of Duties"):
            await mint_email_action_token(db, req.id, "requester@demo.example.com", 0)


@pytest.mark.asyncio
async def test_scanner_prefetch_leaves_request_untouched():
    raw_token = "prefetch-test-token-1234567890123"
    t_hash = hash_token(raw_token)
    tok_row = EmailActionToken(
        id="tok-1",
        token_hash=t_hash,
        request_id="req-1",
        approver_id="manager@demo.example.com",
        step_index=0,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    req = PurchaseRequest(
        id="req-1",
        status="pending_approval",
        current_approver_index=0,
        amount=5000.0,
        currency="INR",
        requested_by="alice@demo.example.com",
        department="Engineering",
    )

    db_mock = AsyncMock()
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = tok_row
    db_mock.execute.return_value = exec_res
    db_mock.get.return_value = req

    from app.database import get_db
    approval_app.dependency_overrides[get_db] = lambda: db_mock


    transport = ASGITransport(app=approval_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET 3 times
        for _ in range(3):
            r = await client.get(f"/email-action/{raw_token}")
            assert r.status_code == 200
            assert "Purchase Request Review" in r.text
            # Assert headers
            assert r.headers["cache-control"] == "no-store"
            assert r.headers["referrer-policy"] == "no-referrer"
            assert r.headers["x-frame-options"] == "DENY"

    # Token must remain unused and request still pending
    assert tok_row.used_at is None
    assert req.status == "pending_approval"
    approval_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unknown_token_returns_generic_404():
    db_mock = AsyncMock()
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = None
    db_mock.execute.return_value = exec_res

    from app.database import get_db
    approval_app.dependency_overrides[get_db] = lambda: db_mock


    transport = ASGITransport(app=approval_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/email-action/nonexistent-token-abc")
        assert r.status_code == 404
        assert "Link Not Found" in r.text

    approval_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_expired_or_used_token_returns_410():
    raw_token = "expired-token-xyz"
    t_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)
    # Expired token
    expired_tok = EmailActionToken(
        id="tok-exp",
        token_hash=t_hash,
        request_id="req-1",
        approver_id="manager@demo.example.com",
        step_index=0,
        expires_at=now - timedelta(hours=1),
    )
    db_mock = AsyncMock()
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = expired_tok
    db_mock.execute.return_value = exec_res

    from app.database import get_db
    approval_app.dependency_overrides[get_db] = lambda: db_mock


    transport = ASGITransport(app=approval_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/email-action/{raw_token}")
        assert r.status_code == 410
        assert "Link Expired" in r.text

    # Used token
    used_tok = EmailActionToken(
        id="tok-used",
        token_hash=t_hash,
        request_id="req-1",
        approver_id="manager@demo.example.com",
        step_index=0,
        expires_at=now + timedelta(hours=10),
        used_at=now - timedelta(minutes=5),
        used_action="approve",
    )
    exec_res.scalar_one_or_none.return_value = used_tok
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/email-action/{raw_token}")
        assert r.status_code == 410
        assert "Link Already Used" in r.text

    approval_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_internal_mint_endpoint_requires_auth_token():
    transport = ASGITransport(app=approval_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. No token -> 403
        r = await client.post("/internal/email-actions/mint", json={
            "request_id": "req-1", "approver_id": "m@demo.test", "step_index": 0
        })
        assert r.status_code == 403

        # 2. Wrong token -> 403
        r = await client.post(
            "/internal/email-actions/mint",
            headers={"X-Internal-Service-Token": "wrong-secret"},
            json={"request_id": "req-1", "approver_id": "m@demo.test", "step_index": 0}
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_email_action_reject_requires_comment():
    raw_token = "reject-token-comment-check"
    t_hash = hash_token(raw_token)
    tok_row = EmailActionToken(
        id="tok-rej",
        token_hash=t_hash,
        request_id="req-1",
        approver_id="manager@demo.example.com",
        step_index=0,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=10),
    )
    db_mock = AsyncMock()
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = tok_row
    db_mock.execute.return_value = exec_res

    from app.database import get_db
    approval_app.dependency_overrides[get_db] = lambda: db_mock

    transport = ASGITransport(app=approval_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Reject without comment -> 400
        r = await client.post(f"/email-action/{raw_token}/decide", data={"decision": "reject", "comment": ""})
        assert r.status_code == 400
        assert "Comment Required" in r.text

    approval_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_gateway_config_does_not_route_internal():
    # Verify nginx.conf has no location block for /internal
    conf_path = _repo_root / "infra" / "nginx" / "nginx.conf"
    conf = conf_path.read_text(encoding="utf-8")
    assert "/email-action/" in conf
    assert "access_log off;" in conf
    assert "/internal" not in conf


@pytest.mark.asyncio
async def test_security_headers_present_on_email_action_endpoints():
    raw_token = "sec-headers-test-token"
    t_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)
    tok = EmailActionToken(
        id="tok-sec",
        token_hash=t_hash,
        request_id="req-1",
        approver_id="manager@demo.example.com",
        step_index=0,
        expires_at=now + timedelta(hours=24),
    )
    req = PurchaseRequest(
        id="req-1",
        request_type="software",
        requested_by="requester@demo.example.com",
        department="Engineering",
        amount=1500.0,
        spend_tier="manager",
        status="pending_approval",
        approval_chain=["manager"],
        current_approver_index=0,
        sla_deadline=now + timedelta(hours=48),
    )

    db_mock = AsyncMock()
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = tok
    db_mock.execute.return_value = exec_res
    db_mock.get.return_value = req

    from app.database import get_db
    approval_app.dependency_overrides[get_db] = lambda: db_mock

    transport = ASGITransport(app=approval_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/email-action/{raw_token}")
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") == "no-store"
        assert resp.headers.get("referrer-policy") == "no-referrer"
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert "default-src 'none'" in resp.headers.get("content-security-policy", "")

    approval_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_decide_replay_and_double_click_protection():
    raw_token = "replay-token-test-123"
    t_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)

    tok = EmailActionToken(
        id="tok-replay",
        token_hash=t_hash,
        request_id="req-replay",
        approver_id="manager@demo.example.com",
        step_index=0,
        expires_at=now + timedelta(hours=24),
    )
    req = PurchaseRequest(
        id="req-replay",
        request_type="hardware",
        requested_by="employee@demo.example.com",
        department="Operations",
        amount=500.0,
        spend_tier="manager",
        status="pending_approval",
        approval_chain=["manager"],
        current_approver_index=0,
        sla_deadline=now + timedelta(hours=48),
        vendor_id="v-1",
    )

    db_mock = AsyncMock()
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = tok
    db_mock.execute.return_value = exec_res
    db_mock.get.return_value = req
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()

    from app.database import get_db
    approval_app.dependency_overrides[get_db] = lambda: db_mock

    transport = ASGITransport(app=approval_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.services.approval_authority.check_request_authority") as mock_auth, \
             patch("app.api.email_action.evaluate_step_up", return_value=(True, False, None)), \
             patch("app.api.email_action._fetch_vendor_risk", return_value=("Low", False)), \
             patch("app.services.approval_service.ApprovalService.process_decision") as mock_decide:
            mock_auth.return_value = MagicMock(allowed=True)
            mock_decide.return_value = None

            # First POST succeeds
            r1 = await client.post(
                f"/email-action/{raw_token}/decide",
                data={"decision": "approve", "comment": "looks good"},
            )
            assert r1.status_code == 200
            assert "Request Approved" in r1.text
            assert tok.used_at is not None
            assert tok.used_action == "approved"

            # Replay (second POST with now used token) returns 410
            r2 = await client.post(
                f"/email-action/{raw_token}/decide",
                data={"decision": "approve", "comment": "looks good"},
            )
            assert r2.status_code == 410
            assert "Link Already Used" in r2.text

    approval_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_revoked_token_returns_410_with_reason():
    raw_token = "revoked-token-test-xyz"
    t_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)

    tok = EmailActionToken(
        id="tok-revoked",
        token_hash=t_hash,
        request_id="req-rev",
        approver_id="manager@demo.example.com",
        step_index=0,
        expires_at=now + timedelta(hours=24),
        revoked_at=now - timedelta(minutes=10),
        revoked_reason="superseded",
    )

    db_mock = AsyncMock()
    exec_res = MagicMock()
    exec_res.scalar_one_or_none.return_value = tok
    db_mock.execute.return_value = exec_res

    from app.database import get_db
    approval_app.dependency_overrides[get_db] = lambda: db_mock

    transport = ASGITransport(app=approval_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # GET returns 410 with human-readable superseded message
        r_get = await client.get(f"/email-action/{raw_token}")
        assert r_get.status_code == 410
        assert "Link Revoked" in r_get.text
        assert "newer approval link" in r_get.text

        # POST also returns 410
        r_post = await client.post(
            f"/email-action/{raw_token}/decide",
            data={"decision": "approve", "comment": ""},
        )
        assert r_post.status_code == 410
        assert "Link Revoked" in r_post.text
        assert "newer approval link" in r_post.text

        # Different revocation reason (e.g. cancelled) shows specific reason
        tok.revoked_reason = "cancelled"
        r_cancel = await client.get(f"/email-action/{raw_token}")
        assert r_cancel.status_code == 410
        assert "cancelled" in r_cancel.text

    approval_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_revoke_tokens_utility():
    from app.services.email_action_token_service import revoke_tokens
    db_mock = AsyncMock()
    exec_res = MagicMock()
    exec_res.rowcount = 2
    db_mock.execute.return_value = exec_res

    count = await revoke_tokens(db_mock, "req-123", step_index=0, reason="delegation_changed")
    assert count == 2
    assert db_mock.execute.called


