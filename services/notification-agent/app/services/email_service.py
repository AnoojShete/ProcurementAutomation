"""SMTP delivery to the shared Mailpit instance (hostname `mailpit`, SMTP
port 1025 — see docker-compose.yml). Mailpit accepts any recipient/sender
without auth, so this stays a plain, unauthenticated send — good enough
for dev/demo, which is all this platform targets."""
import logging

import aiosmtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        use_tls=settings.smtp_use_tls,
    )
    logger.info(f"Sent email to={to} subject={subject!r}")
