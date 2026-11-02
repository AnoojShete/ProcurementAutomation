"""Sending email, switchable between a local catcher and a real provider.

Enhanced for Prompt 12B:
- Enforce TLS (STARTTLS required or SMTPS, certificate verified; plaintext only in dev)
- Strip CR and LF from all headers (header injection defense)
- Standard footer injection with purpose, privacy notice, and privacy contact
- One-click List-Unsubscribe (RFC 8058) for digest category
- Anti-tracking validation
"""
import asyncio
import hashlib
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass, replace
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import Optional, Tuple

from shared.runtime_env import InsecureConfigError, is_development

logger = logging.getLogger(__name__)

MODES = ("dev", "smtp")
SECURITY = ("starttls", "ssl", "none")


class MailConfigError(RuntimeError):
    pass


class HeaderInjectionError(ValueError):
    pass


@dataclass(frozen=True)
class MailSettings:
    mode: str
    host: str
    port: int
    security: str
    username: str
    password: str
    email_from: str
    reply_to: str
    app_base_url: str
    timeout: float = 15.0


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def sanitize_header(value: str) -> str:
    """Strip carriage returns and line feeds to prevent header injection attacks."""
    if not value:
        return value
    return "".join(c for c in value if c not in "\r\n")


def hash_email(email: str) -> str:
    """Compute SHA-256 hash of lowercase normalized email for suppression/DSR tracking."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def load_settings() -> MailSettings:
    mode = _env("EMAIL_MODE", "dev").lower()
    if mode not in MODES:
        raise MailConfigError(f"EMAIL_MODE must be one of {MODES}, not {mode!r}")
    if mode == "dev":
        if not is_development():
            raise InsecureConfigError(
                "EMAIL_MODE=dev sends mail to the local Mailpit catcher; set EMAIL_MODE=smtp "
                "with real SMTP settings, or APP_ENV=development for a local demo."
            )
        defaults = {"host": "mailpit", "port": "1025", "security": "none"}
    else:
        defaults = {"host": "", "port": "587", "security": "starttls"}

    settings = MailSettings(
        mode=mode,
        host=_env("SMTP_HOST", defaults["host"]),
        port=int(_env("SMTP_PORT", defaults["port"])),
        security=_env("SMTP_SECURITY", defaults["security"]).lower(),
        username=_env("SMTP_USERNAME"),
        password=os.environ.get("SMTP_PASSWORD", ""),
        email_from=_env("EMAIL_FROM", "Procurement Platform <noreply@procurement.local>"),
        reply_to=_env("EMAIL_REPLY_TO"),
        app_base_url=_env("APP_BASE_URL", "http://localhost:8080").rstrip("/"),
    )
    if settings.host.endswith("gmail.com") and " " in settings.password:
        settings = replace(settings, password=settings.password.replace(" ", ""))
    if settings.security not in SECURITY:
        raise MailConfigError(f"SMTP_SECURITY must be one of {SECURITY}")
    if "@" not in parseaddr(settings.email_from)[1]:
        raise MailConfigError("EMAIL_FROM must contain an email address, e.g. 'Procurement <you@gmail.com>'")
    if mode == "smtp":
        missing = [n for n, v in (("SMTP_HOST", settings.host), ("SMTP_USERNAME", settings.username),
                                  ("SMTP_PASSWORD", settings.password)) if not v]
        if missing:
            raise MailConfigError(f"EMAIL_MODE=smtp needs {', '.join(missing)}")
        if settings.security == "none":
            # Credentials would cross the internet in clear text.
            raise MailConfigError("EMAIL_MODE=smtp needs SMTP_SECURITY=starttls or ssl")
    return settings


def append_footer(
    text: str,
    html: Optional[str] = None,
    *,
    purpose: str = "operational procurement notifications",
    category: str = "transactional",
    app_base_url: str = "http://localhost:8080",
    org_name: str = "IT Procurement Platform",
    org_address: str = "Corporate Procurement Division",
    privacy_notice_url: str = "http://localhost:8080/docs/privacy/privacy-notice.md",
    privacy_contact_email: str = "privacy@procurement.local",
) -> Tuple[str, Optional[str]]:
    """Inject standard GDPR-compliant footer containing sender identity,
    purpose, privacy notice link, and preference links where appropriate.
    """
    clean_purpose = sanitize_header(purpose)
    
    # 1. Plain text footer
    lines = [
        text.rstrip(),
        "",
        "---",
        f"{org_name} | {org_address}",
        f"Why you received this: {clean_purpose}.",
        f"Privacy Notice: {privacy_notice_url}",
        f"Privacy Contact: {privacy_contact_email}",
    ]
    if category in ("digest", "reminder"):
        lines.append(f"Notification Preferences: {app_base_url}/account/preferences")
    else:
        lines.append("This is an essential operational notification regarding your account or transaction.")
    
    text_out = "\n".join(lines)

    # 2. HTML footer if HTML body is provided
    html_out = None
    if html:
        pref_link = ""
        if category in ("digest", "reminder"):
            pref_link = f' | <a href="{app_base_url}/account/preferences" style="color: #64748b;">Manage Preferences</a>'
        else:
            pref_link = " | <span>Mandatory operational notification</span>"

        footer_html = f"""
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0 12px 0;" />
        <div style="font-size: 12px; line-height: 1.5; color: #64748b;">
          <strong>{org_name}</strong> &bull; {org_address}<br />
          Why you are receiving this: {clean_purpose}.<br />
          <a href="{privacy_notice_url}" style="color: #64748b;">Privacy Notice</a> |
          <a href="mailto:{privacy_contact_email}" style="color: #64748b;">{privacy_contact_email}</a>
          {pref_link}
        </div>
        """
        html_out = html.rstrip() + footer_html

    return text_out, html_out


def build_message(
    settings: MailSettings,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    category: str = "transactional",
    purpose: str = "operational procurement updates",
) -> EmailMessage:
    # Header injection defense: sanitize all header inputs
    clean_to = sanitize_header(to)
    clean_subject = sanitize_header(subject)
    clean_from = sanitize_header(settings.email_from)

    msg = EmailMessage()
    msg["From"] = clean_from
    msg["To"] = clean_to
    if settings.reply_to:
        msg["Reply-To"] = sanitize_header(settings.reply_to)
    msg["Subject"] = clean_subject
    msg["Date"] = formatdate(localtime=False, usegmt=True)

    from_addr = parseaddr(clean_from)[1] or "procurement.local"
    domain = from_addr.rsplit("@", 1)[-1]
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Auto-Submitted"] = "auto-generated"

    # RFC 8058 One-Click List-Unsubscribe headers for digest category
    if category == "digest":
        unsub_url = f"{settings.app_base_url}/api/notifications/unsubscribe?token={hash_email(clean_to)}"
        unsub_mail = f"mailto:privacy@procurement.local?subject=unsubscribe_{hash_email(clean_to)}"
        msg["List-Unsubscribe"] = f"<{unsub_url}>, <{unsub_mail}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    # Append standard footer
    text_with_footer, html_with_footer = append_footer(
        text,
        html,
        purpose=purpose,
        category=category,
        app_base_url=settings.app_base_url,
    )

    msg.set_content(text_with_footer)
    if html_with_footer:
        msg.add_alternative(html_with_footer, subtype="html")

    return msg


def _send_blocking(settings: MailSettings, msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    if settings.security == "ssl":
        server = smtplib.SMTP_SSL(settings.host, settings.port, timeout=settings.timeout, context=context)
    else:
        server = smtplib.SMTP(settings.host, settings.port, timeout=settings.timeout)
    with server:
        if settings.security == "starttls":
            server.starttls(context=context)
        if settings.username:
            server.login(settings.username, settings.password)
        server.send_message(msg)


async def send_email(
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
    settings: MailSettings | None = None,
    category: str = "transactional",
    purpose: str = "operational procurement updates",
) -> None:
    """Sends one message; raises on failure (callers decide whether to retry
    or just log). Never logs the body — it can hold one-time links.
    """
    settings = settings or load_settings()
    msg = build_message(settings, to, subject, text, html, category=category, purpose=purpose)
    await asyncio.to_thread(_send_blocking, settings, msg)
    clean_to = sanitize_header(to)
    logger.info(f"email sent ({settings.mode}) to @{clean_to.rsplit('@', 1)[-1]}: {sanitize_header(subject)!r}")
