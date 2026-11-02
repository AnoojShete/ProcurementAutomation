"""Notification templates an admin edits from the Control Panel.

Enhanced for Prompt 12B:
- Template governance: category, audience, lawful_basis, contains_personal_data
- Strict rejection of category 'marketing'
- Promotional wording blocklist validation
- Placeholder classification: public, internal, personal, restricted
- RESTRICTED placeholders blocked at save AND at render
- Personal data blocked from SUBJECT lines (privacy.no_personal_data_in_subject)
"""
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from jinja2 import StrictUndefined, TemplateSyntaxError, meta
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import templating
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = ("transactional", "security", "reminder", "digest")
ALLOWED_AUDIENCES = ("internal", "requester", "approver", "vendor")
ALLOWED_LAWFUL_BASES = ("contract", "legitimate_interest", "legal_obligation", "consent")

RESTRICTED_PLACEHOLDERS = {
    "bank_account_number",
    "ifsc",
    "pan",
    "password",
    "raw_api_data",
    "auth_token",
}

PERSONAL_PLACEHOLDERS = {
    "requested_by",
    "recipient",
    "approver_name",
    "email",
    "contact_name",
}

DEFAULT_PROMOTIONAL_WORDS = [
    "discount", "deal", "promo", "special offer", "newsletter", "marketing",
    "free trial", "subscribe now", "buy now", "limited time offer"
]

TEMPLATE_INFO: dict[str, tuple[str, str]] = {
    "approval_requested": ("approval.requested, and approval.decided with levels left", "The people assigned to the approval level"),
    "approval_decided": ("approval.decided", "The requester"),
    "approval_decided_vendor": ("approval.decided (final or rejected)", "The vendor's contact"),
    "request_submitted": ("approval.requested (initial submission)", "The requester"),
    "contract_generated": ("contract.generated", "The requester"),
    "contract_signed": ("contract.signed", "The requester"),
    "contract_signed_vendor": ("contract.signed", "The vendor's contact"),
    "contract_ready_for_signature": ("notification.send from contract-risk-agent", "The signer and the requester"),
    "contract_renewal_due": ("contract.renewal.due", "The contract owner"),
    "contract_obligation_due": ("contract.obligation.due", "The obligation owner"),
    "document_classified": ("document.classified", "Procurement (documents that need review)"),
    "license_usage_updated": ("license.usage.updated", "Procurement"),
    "risk_score_updated": ("risk.score.updated", "Procurement"),
    "vendor_offboarded": ("vendor.offboarded", "Procurement"),
    "vendor_payment_details_flagged": ("vendor.payment_details_flagged", "Finance"),
    "budget_threshold_crossed": ("budget.threshold_crossed", "The budget owner"),
    "rfq_invitation": ("rfq.issued", "Each invited vendor"),
    "rfq_awarded": ("rfq.awarded", "The winning vendor"),
    "rfq_not_selected": ("rfq.awarded", "Vendors not selected"),
    "goods_received": ("goods.received", "The requester"),
    "reminder_due": ("reminder.due", "Whoever must act"),
    "email_action_confirmation": ("approval decided by email link", "The approver who clicked"),
    "bulk_approval_digest": ("notification.send daily digest", "Approvers eligible for batch approval"),
    "digest_summary": ("digest flush", "Anyone with queued non-urgent updates"),
    "generic_fallback": ("notification.send with an unknown template", "The requested recipient"),
}

COMMON_PLACEHOLDERS = ("portal_url", "privacy_notice_url", "org_name")

_SAMPLE_VALUES = {
    "entries": [{"event_type": "goods.received", "context": {"request_id": "PR-1042", "quantity": 3}}],
    "count": 1,
    "context": {"request_id": "PR-1042"},
    "approval_chain": ["approver@procurement.local"],
    "step_index": 0,
    "decision": "approved",
    "vendor_name": "Acme Supplier Inc",
    "decided_at": "23 Oct 2026, 12:00 UTC",
}

_NAME = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_EMAIL = re.compile(r"^[^@\s,]+@[^@\s,]+$")

_sandbox = SandboxedEnvironment(trim_blocks=True, lstrip_blocks=True, undefined=StrictUndefined)
_preview_sandbox = SandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)


class TemplateValidationError(ValueError):
    pass


@dataclass
class Template:
    name: str
    subject: str
    body: str
    description: str = ""
    recipient: Optional[str] = None
    extra_recipients: list[str] = field(default_factory=list)
    enabled: bool = True
    is_custom: bool = False
    customised: bool = False
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None
    category: str = "transactional"
    audience: str = "internal"
    lawful_basis: str = "contract"
    contains_personal_data: bool = False


# ------------------------------------------------------------ built-ins

def builtin_names() -> list[str]:
    return sorted(f[:-3] for f in os.listdir(templating.TEMPLATES_DIR) if f.endswith(".j2"))


def builtin_source(name: str) -> tuple[str, str]:
    with open(os.path.join(templating.TEMPLATES_DIR, f"{name}.j2"), encoding="utf-8") as f:
        raw = f.read()
    head, _, body = raw.partition("\n---\n")
    subject = head.strip()
    if subject.lower().startswith("subject:"):
        subject = subject.split(":", 1)[1].strip()
    return subject, body.strip("\n")


def placeholders(subject: str, body: str, recipient: str = "") -> list[str]:
    found = set()
    for source in (subject, body, recipient):
        if source and source.strip():
            found |= meta.find_undeclared_variables(_sandbox.parse(source))
    return sorted(found)


def allowed_placeholders(name: str) -> Optional[list[str]]:
    if name not in builtin_names():
        return None
    return sorted(set(placeholders(*builtin_source(name))) | set(COMMON_PLACEHOLDERS))


# ------------------------------------------------------------ database operations

_COLUMNS = "name, description, subject, body, extra_recipients, enabled, is_custom, updated_by, updated_at, recipient, category, audience, lawful_basis, contains_personal_data"
_COLUMNS_LEGACY = "name, description, subject, body, extra_recipients, enabled, is_custom, updated_by, updated_at, recipient"


def _from_row(row) -> Template:
    recip = getattr(row, "recipient", None)
    return Template(
        name=row.name,
        subject=row.subject,
        body=row.body,
        description=row.description,
        recipient=recip if recip else None,
        extra_recipients=parse_recipients(row.extra_recipients),
        enabled=row.enabled,
        is_custom=row.is_custom,
        customised=not row.is_custom,
        updated_by=row.updated_by,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
        category=getattr(row, "category", "transactional") or "transactional",
        audience=getattr(row, "audience", "internal") or "internal",
        lawful_basis=getattr(row, "lawful_basis", "contract") or "contract",
        contains_personal_data=bool(getattr(row, "contains_personal_data", False)),
    )


def _builtin(name: str) -> Template:
    subject, body = builtin_source(name)
    desc, aud = TEMPLATE_INFO.get(name, ("", "internal"))
    cat = "digest" if "digest" in name else ("reminder" if "due" in name or "reminder" in name else "transactional")
    return Template(
        name=name,
        subject=subject,
        body=body,
        description=desc,
        recipient=aud,
        category=cat,
        audience="vendor" if "vendor" in name else "internal",
        lawful_basis="contract",
        contains_personal_data=bool(set(placeholders(subject, body)) & PERSONAL_PLACEHOLDERS),
    )


async def get(db: AsyncSession, name: str) -> Optional[Template]:
    try:
        row = (await db.execute(text(f"SELECT {_COLUMNS} FROM notification_templates WHERE name = :n"), {"n": name})).first()
    except Exception:
        row = (await db.execute(text(f"SELECT {_COLUMNS_LEGACY} FROM notification_templates WHERE name = :n"), {"n": name})).first()
    if row is not None:
        return _from_row(row)
    if name in builtin_names():
        return _builtin(name)
    return None


async def list_all(db: AsyncSession) -> list[Template]:
    try:
        raw_rows = (await db.execute(text(f"SELECT {_COLUMNS} FROM notification_templates"))).all()
    except Exception:
        raw_rows = (await db.execute(text(f"SELECT {_COLUMNS_LEGACY} FROM notification_templates"))).all()
    rows = {r.name: _from_row(r) for r in raw_rows}
    out = [rows.pop(n, None) or _builtin(n) for n in builtin_names()]
    return out + sorted(rows.values(), key=lambda t: t.name)


def parse_recipients(raw: str | list[str] | None) -> list[str]:
    items = raw if isinstance(raw, list) else (raw or "").replace(";", ",").split(",")
    return [r.strip() for r in items if r and r.strip()]


# ------------------------------------------------------------ validation & governance

def validate(
    name: str,
    subject: str,
    body: str,
    extra_recipients: list[str],
    recipient: Optional[str] = None,
    *,
    creating: bool = False,
    category: str = "transactional",
    audience: str = "internal",
    lawful_basis: str = "contract",
) -> None:
    # 1. Category governance: marketing is prohibited!
    if category.lower() == "marketing":
        raise TemplateValidationError("category 'marketing' is strictly forbidden; system only sends operational emails")
    if category not in ALLOWED_CATEGORIES:
        raise TemplateValidationError(f"category must be one of {ALLOWED_CATEGORIES}, not {category!r}")
    if audience not in ALLOWED_AUDIENCES:
        raise TemplateValidationError(f"audience must be one of {ALLOWED_AUDIENCES}, not {audience!r}")
    if lawful_basis not in ALLOWED_LAWFUL_BASES:
        raise TemplateValidationError(f"lawful_basis must be one of {ALLOWED_LAWFUL_BASES}, not {lawful_basis!r}")

    # 2. Promotional words blocklist check
    promo_blocklist = get_rule("privacy.promotional_words_blocklist", DEFAULT_PROMOTIONAL_WORDS)
    content_lower = f"{subject} {body}".lower()
    for word in promo_blocklist:
        pattern = r"\b" + re.escape(word.lower()) + r"\b"
        if re.search(pattern, content_lower):
            raise TemplateValidationError(
                f"promotional wording {word!r} is forbidden in operational email templates"
            )

    # 3. Restricted placeholders check (blocked from both subject and body)
    all_vars = set(placeholders(subject, body, recipient or ""))
    restricted_found = all_vars & RESTRICTED_PLACEHOLDERS
    if restricted_found:
        raise TemplateValidationError(
            f"restricted placeholder{'s' if len(restricted_found) > 1 else ''} "
            f"{', '.join('{{ ' + r + ' }}' for r in sorted(restricted_found))} "
            f"are blocked from email templates; use a secure portal link instead"
        )

    # 4. Personal data in subject lines check
    no_personal_in_subject = get_rule("privacy.no_personal_data_in_subject", True)
    if no_personal_in_subject:
        subject_vars = set(placeholders(subject, "", ""))
        personal_in_subject = subject_vars & PERSONAL_PLACEHOLDERS
        if personal_in_subject:
            raise TemplateValidationError(
                f"personal data placeholder{'s' if len(personal_in_subject) > 1 else ''} "
                f"{', '.join('{{ ' + p + ' }}' for p in sorted(personal_in_subject))} "
                f"are blocked from subject lines (privacy.no_personal_data_in_subject)"
            )

    # 5. Name and syntax rules
    if creating:
        if not _NAME.match(name):
            raise TemplateValidationError(
                "name: 3-64 characters, lower-case letters, digits and _ , starting with a letter")
        if name in builtin_names():
            raise TemplateValidationError(f"name: '{name}' is a built-in template; edit it instead")
    if not subject.strip():
        raise TemplateValidationError("subject: can't be empty")
    if "\n" in subject or "\r" in subject:
        raise TemplateValidationError("subject: must be one line without carriage returns")
    if not body.strip():
        raise TemplateValidationError("body: can't be empty")

    sources = [("subject", subject), ("body", body)]
    if recipient and recipient.strip():
        sources.append(("recipient", recipient.strip()))
    for part, source in sources:
        try:
            _sandbox.parse(source)
        except TemplateSyntaxError as e:
            raise TemplateValidationError(f"{part}: line {e.lineno}: {e.message}") from e

    allowed = allowed_placeholders(name)
    if allowed is not None:
        unknown = sorted(all_vars - set(allowed))
        if unknown:
            raise TemplateValidationError(
                f"unknown placeholder{'s' if len(unknown) > 1 else ''} "
                f"{', '.join('{{ ' + u + ' }}' for u in unknown)}; this email can use: {', '.join(allowed)}")

    bad = [r for r in extra_recipients if not _EMAIL.match(r)]
    if bad:
        raise TemplateValidationError(f"recipients: not an email address: {', '.join(bad)}")


async def save(
    db: AsyncSession,
    name: str,
    *,
    subject: str,
    body: str,
    description: str,
    extra_recipients: list[str],
    enabled: bool,
    is_custom: bool,
    updated_by: str,
    recipient: Optional[str] = None,
    category: str = "transactional",
    audience: str = "internal",
    lawful_basis: str = "contract",
) -> Template:
    contains_pdata = bool(set(placeholders(subject, body)) & PERSONAL_PLACEHOLDERS)
    
    validate(
        name,
        subject,
        body,
        extra_recipients,
        recipient,
        category=category,
        audience=audience,
        lawful_basis=lawful_basis,
    )

    try:
        await db.execute(text("""
            INSERT INTO notification_templates
                (name, description, subject, body, extra_recipients, enabled, is_custom, updated_by, recipient,
                 category, audience, lawful_basis, contains_personal_data)
            VALUES (:name, :description, :subject, :body, :extra, :enabled, :is_custom, :updated_by, :recipient,
                    :category, :audience, :lawful_basis, :contains_pdata)
            ON CONFLICT (name) DO UPDATE SET
                description = EXCLUDED.description, subject = EXCLUDED.subject, body = EXCLUDED.body,
                extra_recipients = EXCLUDED.extra_recipients, enabled = EXCLUDED.enabled,
                updated_by = EXCLUDED.updated_by, recipient = EXCLUDED.recipient,
                category = EXCLUDED.category, audience = EXCLUDED.audience,
                lawful_basis = EXCLUDED.lawful_basis, contains_personal_data = EXCLUDED.contains_personal_data,
                updated_at = now()
        """), {
            "name": name, "description": description, "subject": subject.strip(), "body": body,
            "extra": ", ".join(extra_recipients), "enabled": enabled, "is_custom": is_custom,
            "updated_by": updated_by, "recipient": recipient.strip() if recipient else None,
            "category": category, "audience": audience, "lawful_basis": lawful_basis,
            "contains_pdata": contains_pdata,
        })
    except Exception:
        # Fallback if migration 0005 not yet applied
        await db.execute(text("""
            INSERT INTO notification_templates
                (name, description, subject, body, extra_recipients, enabled, is_custom, updated_by, recipient)
            VALUES (:name, :description, :subject, :body, :extra, :enabled, :is_custom, :updated_by, :recipient)
            ON CONFLICT (name) DO UPDATE SET
                description = EXCLUDED.description, subject = EXCLUDED.subject, body = EXCLUDED.body,
                extra_recipients = EXCLUDED.extra_recipients, enabled = EXCLUDED.enabled,
                updated_by = EXCLUDED.updated_by, recipient = EXCLUDED.recipient, updated_at = now()
        """), {
            "name": name, "description": description, "subject": subject.strip(), "body": body,
            "extra": ", ".join(extra_recipients), "enabled": enabled, "is_custom": is_custom,
            "updated_by": updated_by, "recipient": recipient.strip() if recipient else None,
        })
    await db.commit()
    return await get(db, name)


async def delete(db: AsyncSession, name: str) -> bool:
    result = await db.execute(text("DELETE FROM notification_templates WHERE name = :n"), {"n": name})
    await db.commit()
    return result.rowcount > 0


# ------------------------------------------------------------ rendering

def render_source(subject: str, body: str, context: dict, *, strict: bool = True) -> tuple[str, str]:
    # Enforce restricted placeholder blocking at render time
    all_vars = set(placeholders(subject, body))
    restricted = all_vars & RESTRICTED_PLACEHOLDERS
    if restricted:
        raise TemplateValidationError(
            f"Blocked restricted placeholders at render: {', '.join(restricted)}"
        )

    # Enforce personal data block in subject at render time
    if get_rule("privacy.no_personal_data_in_subject", True):
        subj_vars = set(placeholders(subject, "", ""))
        personal_subj = subj_vars & PERSONAL_PLACEHOLDERS
        if personal_subj:
            raise TemplateValidationError(
                f"Personal data in subject line blocked at render: {', '.join(personal_subj)}"
            )

    env = _sandbox if strict else _preview_sandbox
    return (env.from_string(subject).render(**context).strip(),
            env.from_string(body).render(**context).strip())


def render_recipient_source(recipient: Optional[str], context: dict, *, strict: bool = True) -> Optional[str]:
    if not recipient or not recipient.strip():
        return None
    env = _sandbox if strict else _preview_sandbox
    try:
        rendered = env.from_string(recipient.strip()).render(**context).strip()
        return rendered or None
    except Exception:
        return recipient.strip()


@dataclass
class Rendered:
    subject: str
    body: str
    extra_recipients: list[str]
    enabled: bool
    recipient: Optional[str] = None
    category: str = "transactional"
    audience: str = "internal"


async def is_enabled(db: AsyncSession, name: str) -> bool:
    try:
        row = (await db.execute(text("SELECT enabled FROM notification_templates WHERE name = :n"), {"n": name})).first()
    except Exception:
        return True
    return row is None or bool(row.enabled)


async def render(db: AsyncSession, name: str, context: dict) -> Rendered:
    """Renders the email for `name`, enforcing restricted placeholder blocking
    and subject privacy rules."""
    tpl = await get(db, name)
    if tpl is None:
        subject, body = templating.render_template(name, context)
        return Rendered(subject, body, [], enabled=True, recipient=None)

    if not tpl.enabled:
        return Rendered("", "", [], enabled=False)

    recip = render_recipient_source(tpl.recipient, context)
    try:
        subject, body = render_source(tpl.subject, tpl.body, context)
        return Rendered(
            subject, body, tpl.extra_recipients, enabled=True, recipient=recip,
            category=tpl.category, audience=tpl.audience,
        )
    except Exception as e:
        if tpl.is_custom:
            raise
        logger.warning(f"[templates] override of {name} failed to render ({e}); sending built-in instead")
        subject, body = templating.render_template(name, context)
        return Rendered(
            subject, body, tpl.extra_recipients, enabled=True, recipient=recip,
            category=tpl.category, audience=tpl.audience,
        )
