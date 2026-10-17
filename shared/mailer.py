"""Sending email, switchable between a local catcher and a real provider.

EMAIL_MODE picks where mail goes:

  dev   (default) Mailpit, the local mail catcher in docker-compose. Nothing
        leaves the machine; open http://localhost:8025 to read what was sent.
  smtp  A real SMTP server: Gmail (app password), Brevo, Resend, SendGrid,
        Amazon SES... All of them accept plain SMTP, so switching provider
        means changing environment variables, not code.

Settings (see .env.example):

  SMTP_HOST, SMTP_PORT
  SMTP_SECURITY   starttls (port 587) | ssl (port 465) | none (Mailpit only)
  SMTP_USERNAME, SMTP_PASSWORD
  EMAIL_FROM      "Display Name <address>". With Gmail this must be the Gmail
                  address you log in with, or Gmail rewrites it.
  EMAIL_REPLY_TO  where replies go (optional)
  APP_BASE_URL    public address of the web app, used to build links

Every message has a plain-text body and an HTML alternative, so it reads
properly in any mail client. Outside development EMAIL_MODE must be smtp —
a production system quietly sending account emails into a mail catcher
would lock every new user out.

The send itself uses the standard library (smtplib) in a worker thread, so
a slow mail server doesn't block other requests.
"""
import asyncio
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass, replace
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from shared.runtime_env import InsecureConfigError, is_development

logger = logging.getLogger(__name__)

MODES = ("dev", "smtp")
SECURITY = ("starttls", "ssl", "none")


class MailConfigError(RuntimeError):
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
    # docker-compose passes unset variables as "", which means "default".
    value = os.environ.get(name, "").strip()
    return value or default


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
        # Gmail shows app passwords in groups of four; the spaces aren't
        # part of the password.
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


def build_message(settings: MailSettings, to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    if settings.reply_to:
        msg["Reply-To"] = settings.reply_to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    domain = parseaddr(settings.email_from)[1].rsplit("@", 1)[-1]
    msg["Message-ID"] = make_msgid(domain=domain)
    # Tells mail servers and auto-responders this is a system message
    # (RFC 3834), so out-of-office replies don't bounce back to it.
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
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


async def send_email(to: str, subject: str, text: str, html: str | None = None,
                     settings: MailSettings | None = None) -> None:
    """Sends one message; raises on failure (callers decide whether to retry
    or just log). Never logs the body — it can hold one-time links."""
    settings = settings or load_settings()
    msg = build_message(settings, to, subject, text, html)
    await asyncio.to_thread(_send_blocking, settings, msg)
    logger.info(f"email sent ({settings.mode}) to @{to.rsplit('@', 1)[-1]}: {subject!r}")
