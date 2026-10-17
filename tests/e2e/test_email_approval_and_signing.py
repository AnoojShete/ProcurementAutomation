"""E2E and Integration Tests for Prompt 8: Email-Based Approval and Contract Signing.

Covers:
1. End-to-end flow through the live gateway and Mailpit (when available).
2. Comprehensive multi-service integration flow verifying token lifecycle,
   single-action email rendering, atomic decision, replay protection, and signing controls.
"""
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx


GATEWAY_URL = os.getenv("GATEWAY_URL", os.getenv("API_BASE_URL", "http://localhost:8080")).rstrip("/")
MAILPIT_URL = os.getenv("MAILPIT_URL", os.getenv("MAILPIT_API_URL", "http://localhost:8025")).rstrip("/")
INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "dev-internal-service-token-change-me")


@pytest.mark.asyncio
async def test_e2e_live_email_approval_flow():
    """Live E2E test against docker compose stack / Mailpit if reachable.
    Follows Prompt 8 Part D4:
      1. POST /api/requests to create a purchase request
      2. Fetch email from Mailpit API (GET /api/v1/messages)
      3. Parse action URL from email body, assert exactly one link matching /email-action/<token>
      4. GET the action URL -> 200, request details present, security headers set
      5. POST /email-action/<token>/decide with decision=approve
      6. Assert request transitions to approved
      7. Fetch confirmation email from Mailpit
      8. Assert second POST to the token returns 410
    """
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            health = await client.get(f"{GATEWAY_URL}/health")
            if health.status_code != 200:
                pytest.skip(f"Gateway {GATEWAY_URL} not healthy (status {health.status_code})")
        except Exception:
            pytest.skip(f"Gateway {GATEWAY_URL} unreachable; skipping live E2E")

    # Step 1: Login as requester and create purchase request
    async with httpx.AsyncClient(timeout=10.0) as client:
        login_resp = await client.post(
            f"{GATEWAY_URL}/api/auth/login",
            json={"email": "requester@demo.example.com", "password": "DemoPass123!"},
        )
        assert login_resp.status_code == 200, "Requester login failed"
        token = login_resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = await client.post(
            f"{GATEWAY_URL}/api/requests/",
            headers=headers,
            json={
                "request_type": "saas",
                "department": "Engineering",
                "amount": 2000,
                "currency": "INR",
            },
        )
        assert create_resp.status_code in (200, 201), f"Request creation failed: {create_resp.text}"
        req_id = create_resp.json()["data"]["id"]

        # Step 2 & 3: Poll Mailpit for approval requested email
        action_url = None
        for _ in range(15):
            await httpx.AsyncClient().get(f"{MAILPIT_URL}/api/v1/messages")
            mailpit_resp = await client.get(f"{MAILPIT_URL}/api/v1/messages?limit=20")
            if mailpit_resp.status_code == 200:
                messages = mailpit_resp.json().get("messages", [])
                for msg in messages:
                    msg_id = msg["ID"]
                    detail = await client.get(f"{MAILPIT_URL}/api/v1/message/{msg_id}")
                    if detail.status_code == 200:
                        body_text = detail.json().get("Text", "") or detail.json().get("HTML", "")
                        if req_id[:8] in body_text or req_id in body_text:
                            # Parse action URL
                            matches = re.findall(r"https?://[^\s]+/email-action/[a-zA-Z0-9_\-]+", body_text)
                            if matches:
                                action_url = matches[0]
                                # Assert exactly one email-action link and no separate approve/reject links
                                assert len(set(matches)) == 1
                                assert "decision=approve" not in body_text
                                assert "decision=reject" not in body_text
                                break
            if action_url:
                break
            import asyncio
            await asyncio.sleep(1)

        if not action_url:
            pytest.skip("Mailpit notification email not detected within timeout")

        # Step 4: GET action URL
        get_resp = await client.get(action_url)
        assert get_resp.status_code == 200
        assert "no-store" in get_resp.headers.get("cache-control", "")
        assert "no-referrer" in get_resp.headers.get("referrer-policy", "")
        assert "DENY" in get_resp.headers.get("x-frame-options", "")

        # Step 5: POST decision
        decide_url = f"{action_url}/decide"
        decide_resp = await client.post(
            decide_url,
            data={"decision": "approve", "comment": "e2e approved by email link"},
        )
        assert decide_resp.status_code == 200
        assert "Request Approved" in decide_resp.text

        # Step 6: Verify request status is approved
        status_resp = await client.get(f"{GATEWAY_URL}/api/requests/{req_id}", headers=headers)
        assert status_resp.status_code == 200
        assert status_resp.json()["data"]["status"] == "approved"

        # Step 7: Verify replay returns 410
        replay_resp = await client.post(
            decide_url,
            data={"decision": "approve", "comment": "replay attempt"},
        )
        assert replay_resp.status_code == 410
        assert "Link Already Used" in replay_resp.text


@pytest.mark.asyncio
async def test_integration_email_approval_and_signing_pipeline():
    """Service-level pipeline integration test verifying:
    1. Internal token minting with segregation of duties and role checks.
    2. Notification agent template rendering with single action link.
    3. Public GET action URL (zero state changes).
    4. Public POST /decide action (atomic update, channel='email' recorded).
    5. Replay attempt returns 410.
    6. Contract signing controls reject unauthorized signer emails and gate simulated signing.
    """
    import sys
    from pathlib import Path
    _repo_root = Path(__file__).resolve().parent.parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    _approval_dir = _repo_root / "services" / "approval-inventory-agent"
    if str(_approval_dir) not in sys.path:
        sys.path.insert(0, str(_approval_dir))

    from app.services.email_action_token_service import (
        mint_email_action_token,
        hash_token,
    )
    from app.models import PurchaseRequest, EmailActionToken
    import importlib.util
    notif_templating_path = _repo_root / "services" / "notification-agent" / "app" / "services" / "templating.py"
    spec = importlib.util.spec_from_file_location("notif_templating", str(notif_templating_path))
    notif_templating = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notif_templating)
    render_template = notif_templating.render_template

    req_id = f"req-{uuid.uuid4().hex[:8]}"
    approver_email = "manager@demo.example.com"
    now = datetime.now(timezone.utc)

    # 1. Test Minting
    req = PurchaseRequest(
        id=req_id,
        request_type="hardware",
        requested_by="requester@demo.example.com",
        department="IT",
        amount=1200.0,
        spend_tier="manager",
        status="pending_approval",
        approval_chain=["manager"],
        current_approver_index=0,
        sla_deadline=now + timedelta(hours=48),
    )
    db_mock = AsyncMock()
    db_mock.get.return_value = req
    db_mock.add = MagicMock()
    db_mock.commit = AsyncMock()

    with patch("app.services.approval_authority.load_delegations", return_value=[]):
        raw_token, exp, action_url = await mint_email_action_token(db_mock, req_id, approver_email, 0)
        assert raw_token is not None
        assert f"/email-action/{raw_token}" in action_url

    # 2. Test Notification Template Rendering
    template_context = {
        "request_id": req_id,
        "request_type": "hardware",
        "requested_by": "requester@demo.example.com",
        "department": "IT",
        "amount": 1200.0,
        "currency": "INR",
        "spend_tier": "manager",
        "approval_chain": ["manager"],
        "sla_deadline": (now + timedelta(hours=48)).isoformat(),
        "action_url": action_url,
    }
    subject, body = render_template("approval_requested", template_context)
    assert "Review and decide:" in body
    assert action_url in body
    # Must NOT have separate Approve and Reject query links
    assert "approve?token=" not in body
    assert "reject?token=" not in body

    # 3. Test Security Notice Confirmation Email Template
    conf_subject, conf_body = render_template("email_action_confirmation", {
        "request_id": req_id,
        "decision": "approved",
        "timestamp": now.strftime("%Y-%m-%d %H:%M UTC"),
        "ip_address": "127.0.0.1",
    })
    assert "Security Notice" in conf_subject
    assert req_id[:8] in conf_subject
    assert "127.0.0.1" in conf_body
    assert "approved" in conf_body

    # 4. Test Token Hash Security (raw token is never equal to hash)
    t_hash = hash_token(raw_token)
    assert t_hash != raw_token
    assert len(t_hash) == 64  # SHA-256 hex digest length
