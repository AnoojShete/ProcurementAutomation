"""Email delivery via shared/mailer.py with Custom Company SMTP support.

Logic ported from C# projectmanagement.Services.EmailService:
- First checks for active custom company SMTP settings in database (comp_id=1).
- If present and active, decrypts the AES-256-GCM password and sends via custom SMTP.
- If not configured or inactive, falls back to default system mailer (Mailpit in dev, env in prod).
"""
import logging
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import CompanySmtpSettings
from shared.mailer import MailSettings, send_email as shared_send_email
from shared.security.encryption import default_encryption_service

logger = logging.getLogger(__name__)


async def get_custom_smtp_settings(db: Optional[AsyncSession] = None) -> Optional[MailSettings]:
    """Retrieve active company SMTP settings from database and decrypt password."""
    try:
        async def _query(session: AsyncSession):
            stmt = select(CompanySmtpSettings).where(
                CompanySmtpSettings.comp_id == 1,
                CompanySmtpSettings.is_active == 1,
            )
            res = await session.execute(stmt)
            return res.scalar_one_or_none()

        if db:
            row = await _query(db)
        else:
            async with async_session_factory() as session:
                row = await _query(session)

        if not row or not row.host:
            return None

        decrypted_password = default_encryption_service.decrypt(row.password) or ""
        security = "ssl" if (row.enable_ssl and row.port == 465) else ("starttls" if row.enable_ssl else "none")

        return MailSettings(
            mode="smtp",
            host=row.host,
            port=row.port,
            security=security,
            username=row.username,
            password=decrypted_password,
            email_from=row.email_from,
            reply_to="",
            app_base_url=os.environ.get("APP_BASE_URL", "http://localhost:8080").rstrip("/"),
        )
    except Exception as ex:
        logger.warning("Could not load custom SMTP settings from DB: %s (falling back to default)", ex)
        return None


async def send_email(to: str, subject: str, body: str, db: Optional[AsyncSession] = None) -> None:
    """Send an email using custom SMTP if configured, or default mailer as fallback."""
    custom_settings = await get_custom_smtp_settings(db)
    if custom_settings:
        logger.info("[EMAIL] Using Custom SMTP for company (%s:%d)", custom_settings.host, custom_settings.port)
        await shared_send_email(to=to, subject=subject, text=body, settings=custom_settings)
    else:
        logger.info("[EMAIL] Using System Default mailer")
        await shared_send_email(to=to, subject=subject, text=body)
    logger.info("Sent email to=%s subject=%r", to, subject)
