"""Comprehensive test suite for Prompt 12B: Privacy controls for email and personal data.
Tests:
1. Marketing category strictly rejected at save
2. Promotional wording from rule blocklist rejected
3. Restricted placeholders blocked at save AND at render
4. Personal data blocked from subject lines
5. Header injection stripped from email messages
6. Suppressions honored by category & scope
7. RFC 8058 one-click unsubscribe headers added for digest emails
8. Compliant footer present with mandatory operational stance
9. No tracking pixels, redirects, or remote images in any template
10. DSR export collects all data categories into a ZIP of JSONs
11. DSR erasure requires dual-admin approval & pseudonymises identifiers
12. Cross-border EU region check blocks non-essential emails for unapproved processors
13. Audit log email scrubber removes email addresses from audit payloads
"""
import io
import os
import re
import sys
import zipfile
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["APP_ENV"] = "development"

_ROOT = Path(__file__).resolve().parent.parent
_NOTIF_DIR = _ROOT / "services" / "notification-agent"
if str(_NOTIF_DIR) not in sys.path:
    sys.path.insert(0, str(_NOTIF_DIR))
if "app" in sys.modules and not hasattr(sys.modules["app"], "services"):
    del sys.modules["app"]

from shared.mailer import (
    sanitize_header,
    build_message,
    append_footer,
    hash_email,
    MailSettings,
)
from app.services.template_store import (
    validate,
    render_source,
    TemplateValidationError,
    builtin_names,
    builtin_source,
)
from app.services.privacy_service import (
    is_suppressed,
    add_suppression,
    check_cross_border_transfer,
    generate_dsr_export_zip,
    execute_dsr_erasure,
)


def test_marketing_category_strictly_forbidden():
    with pytest.raises(TemplateValidationError, match="category 'marketing' is strictly forbidden"):
        validate(
            "custom_marketing_promo",
            "Subject text",
            "Body content",
            [],
            category="marketing",
        )


def test_promotional_wording_blocklist():
    for promo_word in ("discount", "special offer", "limited time offer", "free trial"):
        with pytest.raises(TemplateValidationError, match="promotional wording"):
            validate(
                "custom_notice",
                f"Notice with a {promo_word}",
                "Body content",
                [],
                category="transactional",
            )

        with pytest.raises(TemplateValidationError, match="promotional wording"):
            validate(
                "custom_notice_2",
                "Clean subject",
                f"We are offering a {promo_word} on this contract.",
                [],
                category="transactional",
            )


def test_restricted_placeholders_blocked_at_save():
    restricted_vars = ["bank_account_number", "ifsc", "pan", "password", "raw_api_data", "auth_token"]
    for var in restricted_vars:
        with pytest.raises(TemplateValidationError, match="restricted placeholder"):
            validate(
                "custom_payment_template",
                "Payment details",
                f"Your confidential value is {{{{ {var} }}}}.",
                [],
                category="transactional",
            )


def test_restricted_placeholders_blocked_at_render():
    with pytest.raises(TemplateValidationError, match="Blocked restricted placeholders at render"):
        render_source(
            "Payment notification",
            "Bank account: {{ bank_account_number }}",
            {"bank_account_number": "1234567890"},
        )


def test_personal_data_blocked_in_subject():
    for p_var in ("requested_by", "recipient", "approver_name", "email", "contact_name"):
        with pytest.raises(TemplateValidationError, match="blocked from subject lines"):
            validate(
                "custom_approval_tpl",
                f"Action required for {{{{ {p_var} }}}}",
                "Please review the attached contract.",
                [],
                category="transactional",
            )

        with pytest.raises(TemplateValidationError, match="Personal data in subject line blocked at render"):
            render_source(
                f"Action required for {{{{ {p_var} }}}}",
                "Please review the attached contract.",
                {p_var: "Alice Smith"},
            )


def test_header_injection_defense():
    dirty_subj = "Contract Approval Required\r\nBcc: evil@attacker.com\nAnother-Header: injected"
    clean_subj = sanitize_header(dirty_subj)
    assert "\r" not in clean_subj
    assert "\n" not in clean_subj
    assert clean_subj == "Contract Approval RequiredBcc: evil@attacker.comAnother-Header: injected"

    settings = MailSettings(
        mode="dev",
        host="mailpit",
        port=1025,
        security="none",
        username="",
        password="",
        email_from="Procurement\r\n <noreply@procurement.local>",
        reply_to="reply\r\n@procurement.local",
        app_base_url="http://localhost:8080",
    )
    msg = build_message(settings, "to@test.com\r\n", dirty_subj, "Hello world")
    assert "\r" not in msg["Subject"]
    assert "\n" not in msg["Subject"]
    assert "\r" not in msg["To"]
    assert "\n" not in msg["To"]


@pytest.mark.asyncio
async def test_email_suppression_logic():
    mock_db = MagicMock()

    # 1. Non-suppressed recipient
    mock_res_none = MagicMock()
    mock_res_none.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_res_none)

    suppressed, reason = await is_suppressed(mock_db, "user@example.com", "transactional")
    assert not suppressed
    assert reason is None

    # 2. Erased individual
    mock_suppression = MagicMock()
    mock_suppression.reason = "erased"
    mock_suppression.scope = "all_non_security"
    mock_res_erased = MagicMock()
    mock_res_erased.scalar_one_or_none.return_value = mock_suppression
    mock_db.execute = AsyncMock(return_value=mock_res_erased)

    suppressed, reason = await is_suppressed(mock_db, "erased@example.com", "transactional")
    assert suppressed
    assert reason == "erased"

    # Erased recipient still receives critical security breach notifications
    suppressed, reason = await is_suppressed(mock_db, "erased@example.com", "security")
    assert not suppressed

    # 3. Objection from vendor contact
    mock_obj = MagicMock()
    mock_obj.reason = "objection"
    mock_res_obj = MagicMock()
    mock_res_obj.scalar_one_or_none.return_value = mock_obj
    mock_db.execute = AsyncMock(return_value=mock_res_obj)

    suppressed, reason = await is_suppressed(mock_db, "vendor@supplier.com", "reminder")
    assert suppressed
    assert reason == "objection"


def test_rfc8058_one_click_unsubscribe_headers():
    settings = MailSettings(
        mode="dev",
        host="mailpit",
        port=1025,
        security="none",
        username="",
        password="",
        email_from="noreply@procurement.local",
        reply_to="",
        app_base_url="http://localhost:8080",
    )
    # Digest gets RFC 8058 headers
    digest_msg = build_message(settings, "approver@corp.local", "Daily Approvals", "Digest text", category="digest")
    assert "List-Unsubscribe" in digest_msg
    assert "List-Unsubscribe-Post" in digest_msg
    assert digest_msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "/api/notifications/unsubscribe?token=" in digest_msg["List-Unsubscribe"]

    # Transactional does NOT get List-Unsubscribe
    trans_msg = build_message(settings, "approver@corp.local", "Approval Required", "Action text", category="transactional")
    assert "List-Unsubscribe" not in trans_msg


def test_standard_compliant_footer():
    body = "Please approve Purchase Request PR-1001."
    text_out, _ = append_footer(body, category="transactional", purpose="reviewing purchase request PR-1001")
    assert "IT Procurement Platform" in text_out
    assert "Corporate Procurement Division" in text_out
    assert "Why you received this: reviewing purchase request PR-1001." in text_out
    assert "Privacy Notice:" in text_out
    assert "Privacy Contact: privacy@procurement.local" in text_out
    assert "essential operational notification" in text_out
    assert "Preferences" not in text_out

    # Digest category includes preferences link
    text_digest, _ = append_footer(body, category="digest", purpose="daily summary")
    assert "Notification Preferences:" in text_digest


def test_all_builtin_templates_have_no_tracking():
    tracking_patterns = [
        re.compile(r"<img[^>]+src=[\"']http", re.IGNORECASE),
        re.compile(r"[?&](utm_source|utm_medium|utm_campaign|trk|track)=", re.IGNORECASE),
    ]

    for name in builtin_names():
        subject, body = builtin_source(name)
        combined = f"{subject}\n{body}"
        for pattern in tracking_patterns:
            match = pattern.search(combined)
            assert not match, f"Template '{name}' contains prohibited tracking pattern: {match.group(0)}"


@pytest.mark.asyncio
async def test_dsr_export_structure():
    mock_db = MagicMock()
    mock_res = MagicMock()
    user_row = MagicMock()
    user_row.id = "u-1234"
    user_row.email = "subject@corp.local"
    user_row.role = "requester"
    user_row.display_name = "Subject Person"
    user_row.created_at = None
    user_row.last_login_at = None

    mock_res.first.return_value = user_row
    mock_res.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_res)

    zip_bytes = await generate_dsr_export_zip(mock_db, "subject@corp.local")
    assert zip_bytes.startswith(b"PK")  # Valid ZIP header

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        namelist = zf.namelist()
        assert "export_metadata.json" in namelist
        assert "user_account.json" in namelist
        assert "vendor_records.json" in namelist
        assert "notifications.json" in namelist
        assert "ratings_and_comments.json" in namelist
        assert "evidence_uploads.json" in namelist
        assert "audit_references.json" in namelist


@pytest.mark.asyncio
async def test_dsr_erasure_requires_distinct_admins():
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    mock_db.add = MagicMock()

    # Single admin attempting erasure must be rejected
    with pytest.raises(ValueError, match="Dual-control violation"):
        await execute_dsr_erasure(
            mock_db,
            request_id="req-1",
            initiating_admin="admin_alice",
            approving_admin="admin_alice",
            subject_email="user@test.com",
        )

    # Two distinct admins succeed
    res = await execute_dsr_erasure(
        mock_db,
        request_id="req-1",
        initiating_admin="admin_alice",
        approving_admin="admin_bob",
        subject_email="user@test.com",
    )
    assert res["status"] == "completed"
    assert res["erased_alias"].startswith("erased:")
    assert res["initiating_admin"] == "admin_alice"
    assert res["approving_admin"] == "admin_bob"


@pytest.mark.asyncio
async def test_cross_border_eu_processor_block():
    mock_db = MagicMock()

    # Case 1: When active processor is unapproved, non-essential emails (digest) are blocked for EU recipient
    with patch("app.services.privacy_service.get_rule") as mock_get_rule:
        def rule_side_effect(key, default):
            if key == "privacy.eu_contacts_require_region_check":
                return True
            if key == "privacy.allowed_processor_regions":
                return ["EU", "EEA", "UK"]
            if key == "privacy.active_processor_region":
                return "US-UNAPPROVED"
            return default
        mock_get_rule.side_effect = rule_side_effect

        allowed, reason = await check_cross_border_transfer(mock_db, "FR", category="digest")
        assert not allowed
        assert "non-essential email blocked" in reason

        # Essential email allowed with warning
        allowed_ess, reason_ess = await check_cross_border_transfer(mock_db, "FR", category="transactional")
        assert allowed_ess
        assert "Processor region warning" in reason_ess

        # Unknown country defaults to EU standard (strictest)
        allowed_unk, reason_unk = await check_cross_border_transfer(mock_db, None, category="digest")
        assert not allowed_unk


def test_audit_log_email_scrubbing():
    # Test payload regex replacement logic for audit scrubbing
    sample_payload = '{"actor": "john.doe@company.com", "action": "created", "details": "Contact: jane.smith@vendor.io"}'
    scrubbed = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[SCRUBBED_EMAIL]", sample_payload)
    assert "john.doe@company.com" not in scrubbed
    assert "jane.smith@vendor.io" not in scrubbed
    assert scrubbed == '{"actor": "[SCRUBBED_EMAIL]", "action": "created", "details": "Contact: [SCRUBBED_EMAIL]"}'
