"""Company SMTP Settings API (admin-only).

Ported from C# projectmanagement.Controllers.SmtpSettingsController:
- GET /GetSettings: Returns current SMTP configuration (password masked).
- POST /SaveSettings: Saves SMTP configuration with AES-256-GCM encrypted password.
- POST /TestConnection: Validates SMTP credentials by sending a test email to the admin.
Dual-compatible with both raw response JSON and ApiEnvelope (`{"data": ...}`).
"""
import asyncio
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
import logging
import smtplib
import ssl
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CompanySmtpSettings
from shared.auth import CurrentUser
from shared.auth.middleware import require_role
from shared.security.encryption import default_encryption_service

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_role("admin"))])


class SmtpSettingsDto(BaseModel):
    host: str = Field(..., max_length=255)
    port: int = Field(587, ge=1, le=65535)
    emailFrom: str = Field(..., max_length=255)
    username: str = Field(..., max_length=255)
    password: Optional[str] = Field(None, max_length=1000)
    enableSsl: bool = True
    companyId: Optional[int] = 1


def _send_test_email_sync(
    host: str,
    port: int,
    username: str,
    password: str,
    email_from: str,
    to_email: str,
    enable_ssl: bool,
    timeout: float = 15.0,
) -> None:
    """Synchronous SMTP connection and test message delivery."""
    host = host.strip() if host else ""
    username = username.strip() if username else ""
    email_from = email_from.strip() if email_from else ""
    if password:
        password = password.strip()
        if host.endswith("gmail.com") or host == "smtp.gmail.com":
            password = password.replace(" ", "")

    msg = EmailMessage()
    msg["From"] = email_from
    msg["To"] = to_email
    msg["Subject"] = "PMS Test Connection"
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    domain = parseaddr(email_from)[1].rsplit("@", 1)[-1] or "procurement.local"
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content("Success! Your SMTP settings are configured correctly.")
    msg.add_alternative(
        "<h1>Success!</h1><p>Your SMTP settings are configured correctly.</p>",
        subtype="html",
    )

    context = ssl.create_default_context()
    if enable_ssl and port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)

    with server:
        if enable_ssl and port != 465:
            server.starttls(context=context)
        if username and password:
            server.login(username, password)
        server.send_message(msg)


@router.get("/GetSettings")
@router.get("")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    company_id = 1
    stmt = select(CompanySmtpSettings).where(CompanySmtpSettings.comp_id == company_id)
    res = await db.execute(stmt)
    settings = res.scalar_one_or_none()

    if settings and settings.host:
        payload = {
            "host": settings.host,
            "port": settings.port,
            "emailFrom": settings.email_from,
            "username": settings.username,
            "enableSsl": settings.enable_ssl,
            "hasPassword": bool(settings.password),
        }
        return {**payload, "data": payload}

    payload = {"hasPassword": False, "host": "", "port": 587, "emailFrom": "", "username": "", "enableSsl": True}
    return {**payload, "data": payload}


@router.post("/SaveSettings")
@router.post("")
async def save_settings(
    request: SmtpSettingsDto,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    company_id = request.companyId or 1
    if company_id <= 0:
        raise HTTPException(status_code=400, detail="Invalid Company ID")

    stmt = select(CompanySmtpSettings).where(CompanySmtpSettings.comp_id == company_id)
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()

    password_to_save: Optional[str] = None
    if not request.password:
        if existing and existing.password:
            password_to_save = existing.password
    else:
        pwd = request.password.strip()
        if request.host and (request.host.strip().endswith("gmail.com") or request.host.strip() == "smtp.gmail.com"):
            pwd = pwd.replace(" ", "")
        password_to_save = default_encryption_service.encrypt(pwd)

    now = datetime.now(timezone.utc)
    if existing:
        existing.host = request.host
        existing.port = request.port
        existing.email_from = request.emailFrom
        existing.username = request.username
        existing.enable_ssl = request.enableSsl
        existing.is_active = 1
        existing.updated_at = now
        if password_to_save is not None:
            existing.password = password_to_save
    else:
        new_settings = CompanySmtpSettings(
            comp_id=company_id,
            host=request.host,
            port=request.port,
            email_from=request.emailFrom,
            username=request.username,
            password=password_to_save or "",
            enable_ssl=request.enableSsl,
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        db.add(new_settings)

    await db.commit()
    logger.info("Admin %s updated company SMTP settings for company %d", user.email, company_id)
    payload = {"message": "Settings saved successfully", "success": True}
    return {**payload, "data": payload}


@router.post("/TestConnection")
@router.post("/test")
async def test_connection(
    request: SmtpSettingsDto,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_role("admin")),
):
    try:
        company_id = request.companyId or 1
        password_to_use = request.password

        if not password_to_use:
            stmt = select(CompanySmtpSettings.password).where(CompanySmtpSettings.comp_id == company_id)
            res = await db.execute(stmt)
            existing_encrypted = res.scalar_one_or_none()
            if not existing_encrypted:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "success": False,
                        "message": "Password is required for testing (or save settings first).",
                        "error": {"code": "bad_request", "message": "Password is required for testing (or save settings first)."},
                    },
                )
            password_to_use = default_encryption_service.decrypt(existing_encrypted)
            if not password_to_use:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "success": False,
                        "message": "Failed to decrypt stored password.",
                        "error": {"code": "decrypt_failed", "message": "Failed to decrypt stored password."},
                    },
                )

        if not request.host:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "message": "Host is required",
                    "error": {"code": "bad_request", "message": "Host is required"},
                },
            )

        user_email = user.email or request.emailFrom

        await asyncio.to_thread(
            _send_test_email_sync,
            host=request.host,
            port=request.port,
            username=request.username,
            password=password_to_use,
            email_from=request.emailFrom,
            to_email=user_email,
            enable_ssl=request.enableSsl,
        )

        payload = {"success": True, "message": f"Test email sent to {user_email}!"}
        return {**payload, "data": payload}

    except smtplib.SMTPException as smtp_ex:
        error_msg = f"SMTP Error: {smtp_ex}"
        if "Connection unexpectedly closed" in str(smtp_ex) and ("gmail" in (request.host or "").lower()):
            error_msg += " (Google rejected the connection. This occurs when 2-Step Verification is off or you used your regular Google account password instead of a 16-character App Password from myaccount.google.com/apppasswords)."
        logger.warning("SMTP test connection failed: %s", error_msg)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False,
                "message": error_msg,
                "error": {"code": "smtp_error", "message": error_msg},
            },
        )
    except Exception as ex:
        logger.error("Error testing SMTP connection: %s", ex, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False,
                "message": f"Error: {ex}",
                "error": {"code": "connection_error", "message": str(ex)},
            },
        )
