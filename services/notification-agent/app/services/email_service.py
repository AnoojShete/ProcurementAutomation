"""Email delivery via shared/mailer.py.

Switchable between:
  - dev: local Mailpit catcher (host `mailpit`, port 1025)
  - smtp: real SMTP provider (Gmail, Brevo, Resend, SendGrid, Amazon SES, etc.)
Configured via standard EMAIL_MODE, SMTP_*, EMAIL_FROM environment variables.
"""
import logging
from shared.mailer import send_email as shared_send_email

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str) -> None:
    await shared_send_email(to=to, subject=subject, text=body)
    logger.info("Sent email to=%s subject=%r", to, subject)
