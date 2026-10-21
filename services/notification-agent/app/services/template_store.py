"""Notification templates an admin edits from the Control Panel.

Every email starts from a built-in file, app/templates/<name>.j2. An admin
can override its subject, body and extra recipients, or turn it off, and
can create new templates that other services send by name through
notification.send. Overrides live in `notification_templates`
(migrations/0002_notification_templates.sql); deleting the row restores the
built-in.

Edited text is rendered in Jinja's sandbox (it comes from a web form, not
the repo) and is checked when saved: it must parse, and a built-in's
override may only use the placeholders its event actually carries. If an
override still fails at send time, the built-in is used, so a bad edit
never loses an email.
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

logger = logging.getLogger(__name__)

# What each built-in template is for: (event, who gets it).
TEMPLATE_INFO: dict[str, tuple[str, str]] = {
    "approval_requested": ("approval.requested, and approval.decided with levels left",
                           "The people assigned to the approval level"),
    "approval_decided": ("approval.decided", "The requester"),
    "contract_generated": ("contract.generated", "The requester"),
    "contract_signed": ("contract.signed", "The requester"),
    "contract_signed_vendor": ("contract.signed", "The vendor's contact"),
    "contract_ready_for_signature": ("notification.send from contract-risk-agent",
                                     "The signer (sent for signature) and the requester (generated)"),
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
    "reminder_due": ("reminder.due", "Whoever must act: the approvers, signer, finance or reviewers"),
    "email_action_confirmation": ("approval decided by email link", "The approver who clicked"),
    "digest_summary": ("digest flush", "Anyone with queued non-urgent updates"),
    "generic_fallback": ("notification.send with an unknown template", "The requested recipient"),
}

# Placeholders every template may use, filled in by the dispatcher.
COMMON_PLACEHOLDERS = ("portal_url",)

# Preview values for placeholders that aren't plain text.
_SAMPLE_VALUES = {
    "entries": [{"event_type": "goods.received", "context": {"request_id": "PR-1042", "quantity": 3}}],
    "count": 1,
    "context": {"request_id": "PR-1042"},
    "approval_chain": ["approver@procurement.local"],
    "step_index": 0,
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
    extra_recipients: list[str] = field(default_factory=list)
    enabled: bool = True
    is_custom: bool = False
    customised: bool = False
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None


# ------------------------------------------------------------ built-ins

def builtin_names() -> list[str]:
    return sorted(f[:-3] for f in os.listdir(templating.TEMPLATES_DIR) if f.endswith(".j2"))


def builtin_source(name: str) -> tuple[str, str]:
    """(subject, body) source of app/templates/<name>.j2, unrendered."""
    with open(os.path.join(templating.TEMPLATES_DIR, f"{name}.j2"), encoding="utf-8") as f:
        raw = f.read()
    head, _, body = raw.partition("\n---\n")
    subject = head.strip()
    if subject.lower().startswith("subject:"):
        subject = subject.split(":", 1)[1].strip()
    return subject, body.strip("\n")


def placeholders(subject: str, body: str) -> list[str]:
    """Variables a template refers to (loop variables excluded)."""
    found = set()
    for source in (subject, body):
        found |= meta.find_undeclared_variables(_sandbox.parse(source))
    return sorted(found)


def allowed_placeholders(name: str) -> Optional[list[str]]:
    """What a built-in's override may use; None (anything) for custom ones."""
    if name not in builtin_names():
        return None
    return sorted(set(placeholders(*builtin_source(name))) | set(COMMON_PLACEHOLDERS))


# ------------------------------------------------------------ the table

_COLUMNS = "name, description, subject, body, extra_recipients, enabled, is_custom, updated_by, updated_at"


def _from_row(row) -> Template:
    return Template(
        name=row.name, subject=row.subject, body=row.body, description=row.description,
        extra_recipients=parse_recipients(row.extra_recipients), enabled=row.enabled,
        is_custom=row.is_custom, customised=not row.is_custom, updated_by=row.updated_by,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _builtin(name: str) -> Template:
    subject, body = builtin_source(name)
    return Template(name=name, subject=subject, body=body, description=TEMPLATE_INFO.get(name, ("", ""))[0])


async def get(db: AsyncSession, name: str) -> Optional[Template]:
    row = (await db.execute(text(f"SELECT {_COLUMNS} FROM notification_templates WHERE name = :n"),
                            {"n": name})).first()
    if row is not None:
        return _from_row(row)
    if name in builtin_names():
        return _builtin(name)
    return None


async def list_all(db: AsyncSession) -> list[Template]:
    rows = {r.name: _from_row(r) for r in (await db.execute(
        text(f"SELECT {_COLUMNS} FROM notification_templates"))).all()}
    out = [rows.pop(n, None) or _builtin(n) for n in builtin_names()]
    return out + sorted(rows.values(), key=lambda t: t.name)


async def exists(db: AsyncSession, name: str) -> bool:
    return (await get(db, name)) is not None


def parse_recipients(raw: str | list[str] | None) -> list[str]:
    items = raw if isinstance(raw, list) else (raw or "").replace(";", ",").split(",")
    return [r.strip() for r in items if r and r.strip()]


def validate(name: str, subject: str, body: str, extra_recipients: list[str], *, creating: bool = False) -> None:
    if creating:
        if not _NAME.match(name):
            raise TemplateValidationError(
                "name: 3-64 characters, lower-case letters, digits and _ , starting with a letter")
        if name in builtin_names():
            raise TemplateValidationError(f"name: '{name}' is a built-in template; edit it instead")
    if not subject.strip():
        raise TemplateValidationError("subject: can't be empty")
    if "\n" in subject:
        raise TemplateValidationError("subject: must be one line")
    if not body.strip():
        raise TemplateValidationError("body: can't be empty")
    for part, source in (("subject", subject), ("body", body)):
        try:
            _sandbox.parse(source)
        except TemplateSyntaxError as e:
            raise TemplateValidationError(f"{part}: line {e.lineno}: {e.message}") from e
    allowed = allowed_placeholders(name)
    if allowed is not None:
        unknown = sorted(set(placeholders(subject, body)) - set(allowed))
        if unknown:
            raise TemplateValidationError(
                f"unknown placeholder{'s' if len(unknown) > 1 else ''} "
                f"{', '.join('{{ ' + u + ' }}' for u in unknown)}; this email can use: {', '.join(allowed)}")
    bad = [r for r in extra_recipients if not _EMAIL.match(r)]
    if bad:
        raise TemplateValidationError(f"recipients: not an email address: {', '.join(bad)}")


async def save(db: AsyncSession, name: str, *, subject: str, body: str, description: str,
               extra_recipients: list[str], enabled: bool, is_custom: bool, updated_by: str) -> Template:
    await db.execute(text("""
        INSERT INTO notification_templates
            (name, description, subject, body, extra_recipients, enabled, is_custom, updated_by)
        VALUES (:name, :description, :subject, :body, :extra, :enabled, :is_custom, :updated_by)
        ON CONFLICT (name) DO UPDATE SET
            description = EXCLUDED.description, subject = EXCLUDED.subject, body = EXCLUDED.body,
            extra_recipients = EXCLUDED.extra_recipients, enabled = EXCLUDED.enabled,
            updated_by = EXCLUDED.updated_by, updated_at = now()
    """), {"name": name, "description": description, "subject": subject.strip(), "body": body,
           "extra": ", ".join(extra_recipients), "enabled": enabled, "is_custom": is_custom,
           "updated_by": updated_by})
    await db.commit()
    return await get(db, name)


async def delete(db: AsyncSession, name: str) -> bool:
    result = await db.execute(text("DELETE FROM notification_templates WHERE name = :n"), {"n": name})
    await db.commit()
    return result.rowcount > 0


# ------------------------------------------------------------ rendering

def render_source(subject: str, body: str, context: dict, *, strict: bool = True) -> tuple[str, str]:
    env = _sandbox if strict else _preview_sandbox
    return (env.from_string(subject).render(**context).strip(),
            env.from_string(body).render(**context).strip())


def sample_context(names: list[str]) -> dict:
    return {n: _SAMPLE_VALUES.get(n, f"[{n}]") for n in names}


async def is_enabled(db: AsyncSession, name: str) -> bool:
    try:
        row = (await db.execute(text("SELECT enabled FROM notification_templates WHERE name = :n"),
                                {"n": name})).first()
    except Exception:
        return True
    return row is None or bool(row.enabled)


@dataclass
class Rendered:
    subject: str
    body: str
    extra_recipients: list[str]
    enabled: bool


async def render(db: AsyncSession, name: str, context: dict) -> Rendered:
    """The email for `name`: the admin's override when there is one, else
    the built-in file. A failing override falls back to the built-in."""
    try:
        row = (await db.execute(text(f"SELECT {_COLUMNS} FROM notification_templates WHERE name = :n"),
                                {"n": name})).first()
    except Exception as e:  # table missing / DB hiccup: the built-in still goes out
        logger.warning(f"[templates] couldn't read override for {name}, using the built-in: {e}")
        row = None
    if row is not None:
        override = _from_row(row)
        if not override.enabled:
            return Rendered("", "", [], enabled=False)
        try:
            subject, body = render_source(override.subject, override.body, context)
            return Rendered(subject, body, override.extra_recipients, enabled=True)
        except Exception as e:
            if override.is_custom:
                raise
            logger.warning(f"[templates] override of {name} failed to render ({e}); sent the built-in instead")
            subject, body = templating.render_template(name, context)
            return Rendered(subject, body, override.extra_recipients, enabled=True)
    subject, body = templating.render_template(name, context)
    return Rendered(subject, body, [], enabled=True)
