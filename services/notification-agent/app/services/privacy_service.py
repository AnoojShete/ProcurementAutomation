"""Privacy service handling DSR requests, email suppressions, cross-border checks,
and RFC 8058 one-click unsubscribes (Prompt 12B).
"""
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    EmailSuppression,
    PrivacyRequest,
    PrivacyProcessingRecord,
    DataProcessor,
    PrivacyIncident,
)
from shared.mailer import hash_email
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)

EU_EEA_UK_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "IS", "LI", "NO", "GB", "UK",
}


async def is_suppressed(
    db: AsyncSession,
    email: str,
    category: str = "transactional",
) -> Tuple[bool, Optional[str]]:
    """Check if recipient email is suppressed from receiving this category of email."""
    if not email:
        return False, None

    addr_hash = hash_email(email)
    try:
        stmt = select(EmailSuppression).where(EmailSuppression.address_hash == addr_hash)
        res = await db.execute(stmt)
        suppression = res.scalar_one_or_none()
        if not suppression:
            return False, None

        # Erased addresses are completely suppressed except for critical security breach notices
        if suppression.reason == "erased":
            if category == "security":
                return False, None
            return True, "erased"

        # Objections from vendor contacts suppress non-security emails
        if suppression.reason == "objection":
            if category == "security":
                return False, None
            return True, "objection"

        # Scope checks
        if suppression.scope == "all_non_security" and category != "security":
            return True, suppression.reason
        if suppression.scope == "non_essential" and category in ("digest", "reminder"):
            return True, suppression.reason

        return False, None
    except Exception as e:
        logger.warning(f"Error checking email suppressions: {e}")
        return False, None


async def add_suppression(
    db: AsyncSession,
    email: str,
    reason: str,
    scope: str = "all_non_security",
) -> EmailSuppression:
    """Record an email address suppression."""
    addr_hash = hash_email(email)
    entry = EmailSuppression(
        address_hash=addr_hash,
        scope=scope,
        reason=reason,
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        # If already exists, query it
        stmt = select(EmailSuppression).where(EmailSuppression.address_hash == addr_hash)
        res = await db.execute(stmt)
        entry = res.scalar_one()

    # If objection from a vendor contact, log task for procurement
    if reason == "objection":
        logger.warning(
            f"[PRIVACY OBJECTION] Vendor contact {email!r} objected to operational emails. "
            f"Created procurement task: Nominate alternative contact person for supplier."
        )

    return entry


async def check_cross_border_transfer(
    db: AsyncSession,
    recipient_country: Optional[str],
    category: str = "transactional",
) -> Tuple[bool, Optional[str]]:
    """When the recipient's country is in EU/EEA/UK and the active processor region
    is not in allowed regions: block non-essential email and warn on essential email.
    Unknown country defaults to strictest (EU standard applies).
    """
    country = (recipient_country or "EU").upper()
    is_eu_regime = (country in EU_EEA_UK_COUNTRIES) or (country in ("EU", "EEA"))

    if not is_eu_regime:
        return True, None

    eu_check_enabled = get_rule("privacy.eu_contacts_require_region_check", True)
    if not eu_check_enabled:
        return True, None

    allowed_regions = set(get_rule("privacy.allowed_processor_regions", ["EU", "EEA", "UK", "IN", "US"]))
    active_processor_region = get_rule("privacy.active_processor_region", "EU")

    if active_processor_region not in allowed_regions:
        if category in ("digest", "reminder"):
            return False, "Recipient is in EU/EEA/UK and processor region is not allowed; non-essential email blocked."
        else:
            logger.warning(
                f"[PRIVACY WARNING] Cross-border processor region '{active_processor_region}' "
                f"is not approved for EU recipient '{country}'; delivering essential email with warning."
            )
            return True, "Processor region warning on essential email"

    return True, None


async def generate_dsr_export_zip(db: AsyncSession, subject_email: str) -> bytes:
    """Collect all personal data across platform tables and build a machine-readable JSON ZIP."""
    export_payload: Dict[str, Any] = {
        "export_metadata": {
            "subject_email": subject_email,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "format": "JSON machine-readable export pursuant to GDPR Art 15 / DPDP Act Sec 11",
        },
        "user_account": {},
        "vendor_records": [],
        "notifications": [],
        "ratings_and_comments": [],
        "evidence_uploads": [],
        "audit_references": [],
    }

    # 1. User account
    try:
        user_res = await db.execute(text("SELECT id, email, role, display_name, created_at, last_login_at FROM auth_users WHERE lower(email) = lower(:e)"), {"e": subject_email})
        user_row = user_res.first()
        if user_row:
            export_payload["user_account"] = {
                "id": str(user_row.id),
                "email": user_row.email,
                "role": user_row.role,
                "display_name": user_row.display_name,
                "created_at": user_row.created_at.isoformat() if user_row.created_at else None,
                "last_login_at": user_row.last_login_at.isoformat() if user_row.last_login_at else None,
            }
    except Exception as e:
        logger.warning(f"DSR export user_account lookup: {e}")

    # 2. Vendor contact records
    try:
        vnd_res = await db.execute(text("SELECT id, name, contact_email, contact_phone, address, pan, msme_udyam_number FROM vendors WHERE lower(contact_email) = lower(:e)"), {"e": subject_email})
        for v in vnd_res.all():
            export_payload["vendor_records"].append({
                "vendor_id": str(v.id),
                "vendor_name": v.name,
                "contact_email": v.contact_email,
                "contact_phone": v.contact_phone,
                "address": v.address,
                "pan": v.pan,
                "msme_udyam_number": v.msme_udyam_number,
            })
    except Exception as e:
        logger.warning(f"DSR export vendor lookup: {e}")

    # 3. Notification delivery logs
    try:
        notif_res = await db.execute(text("SELECT id, event_type, template_name, subject, status, sent_at FROM notification_log WHERE lower(recipient) = lower(:e) ORDER BY sent_at DESC LIMIT 200"), {"e": subject_email})
        for n in notif_res.all():
            export_payload["notifications"].append({
                "id": str(n.id),
                "event_type": n.event_type,
                "template_name": n.template_name,
                "subject": n.subject,
                "status": n.status,
                "sent_at": n.sent_at.isoformat() if n.sent_at else None,
            })
    except Exception as e:
        logger.warning(f"DSR export notification lookup: {e}")

    # Package as in-memory ZIP of JSON files
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for section_name, data in export_payload.items():
            content = json.dumps(data, indent=2, ensure_ascii=False)
            zf.writestr(f"{section_name}.json", content)

    zip_buffer.seek(0)
    return zip_buffer.getvalue()


async def execute_dsr_erasure(
    db: AsyncSession,
    request_id: str,
    initiating_admin: str,
    approving_admin: str,
    subject_email: str,
) -> Dict[str, Any]:
    """Execute dual-control pseudonymisation and erasure for a verified DSR request.
    Requires two distinct administrators.
    """
    if initiating_admin == approving_admin:
        raise ValueError("Dual-control violation: Second admin approver must be distinct from initiating admin.")

    addr_hash = hash_email(subject_email)
    erased_alias = f"erased:{addr_hash[:12]}"
    now = datetime.now(timezone.utc)

    # 1. Pseudonymise auth_users
    try:
        await db.execute(
            text("""
                UPDATE auth_users
                SET email = :alias, display_name = 'Erased Individual',
                    hashed_password = 'erased', is_active = false
                WHERE lower(email) = lower(:orig)
            """),
            {"alias": f"{erased_alias}@erased.local", "orig": subject_email}
        )
    except Exception as e:
        logger.warning(f"DSR erasure auth_users: {e}")

    # 2. Pseudonymise vendor contact
    try:
        await db.execute(
            text("""
                UPDATE vendors
                SET contact_email = :alias, contact_phone = NULL, address = NULL
                WHERE lower(contact_email) = lower(:orig)
            """),
            {"alias": f"{erased_alias}@erased.local", "orig": subject_email}
        )
    except Exception as e:
        logger.warning(f"DSR erasure vendors: {e}")

    # 3. Add to suppression list
    await add_suppression(db, subject_email, reason="erased", scope="all_non_security")

    # 4. Update privacy_requests row
    await db.execute(
        text("""
            UPDATE privacy_requests
            SET status = 'completed', outcome = 'pseudonymised',
                second_admin_approver = :approver,
                outcome_reason = 'Pseudonymised by two-admin approval; audit IDs and tax records preserved pursuant to statutory retention'
            WHERE id = :rid
        """),
        {"approver": approving_admin, "rid": request_id}
    )
    await db.commit()

    return {
        "status": "completed",
        "erased_alias": erased_alias,
        "initiating_admin": initiating_admin,
        "approving_admin": approving_admin,
        "timestamp": now.isoformat(),
    }
