"""Email intake (BR-1): documents emailed to the intake address enter the
same path as an upload — virus scan, MinIO, document.ingested, pipeline.

The mailbox is read over POP3 or IMAP and never changed: each message is
handled once, tracked by its Message-ID in `email_intake` (which also keeps
why an attachment was rejected). Only mail addressed to
`email_intake_address` is considered, so a shared development mailbox
(Mailpit, which also receives every notification) is safe to read.

Emailed documents get uploaded_by = EMAIL_INTAKE_UPLOADER and the sender in
documents.source_sender; they follow the normal reviewed flow.
"""
import asyncio
import email
import email.policy
import hashlib
import imaplib
import json
import logging
import os
import poplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from sqlalchemy import text

from app.config import settings
from app.services.upload_service import (
    InvalidUploadError, MalwareDetectedError, ScanUnavailableError, StorageUnavailableError,
    scan_upload, store_and_record_upload,
)
from shared.drop_folder import EMAIL_INTAKE_UPLOADER

logger = logging.getLogger(__name__)

ACCEPTED = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp"}


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class Email:
    message_id: str
    sender: str
    recipients: list[str]
    subject: str
    received_at: datetime | None
    attachments: list[Attachment] = field(default_factory=list)


def parse(raw: bytes) -> Email:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    recipients = [a.lower() for _, a in getaddresses(msg.get_all("To", []) + msg.get_all("Cc", []) +
                                                     msg.get_all("Delivered-To", []))]
    try:
        received = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
    except (TypeError, ValueError):
        received = None
    attachments = [
        Attachment(part.get_filename() or "attachment", part.get_content_type(), part.get_payload(decode=True) or b"")
        for part in msg.iter_attachments()
    ]
    return Email(
        # No Message-ID: a digest of the message, stable across restarts
        # (hash() is randomised per process and would re-ingest it).
        message_id=(msg["Message-ID"] or "").strip() or f"<sha256-{hashlib.sha256(raw).hexdigest()}>",
        sender=parseaddr(msg["From"] or "")[1].lower(),
        recipients=recipients,
        subject=str(msg["Subject"] or ""),
        received_at=received,
        attachments=attachments,
    )


def is_for_intake(mail: Email, address: str) -> bool:
    return address.lower() in mail.recipients


def rejection_reason(att: Attachment) -> str | None:
    """Why an attachment can't be a document, before anything is stored.
    (Content is checked again from the bytes when it's stored.)"""
    if os.path.splitext(att.filename.lower())[1] not in ACCEPTED:
        return f"not a PDF, PNG, JPEG or WebP ({att.filename})"
    if not att.data:
        return f"empty attachment ({att.filename})"
    if len(att.data) > settings.max_upload_bytes:
        return f"larger than {settings.max_upload_bytes // (1024 * 1024)} MB ({att.filename})"
    return None


# ── mailbox access (blocking; run in a thread) ─────────────────────────────

def fetch_all() -> list[bytes]:
    """Every message in the mailbox, read-only."""
    host, user, password = settings.email_intake_host, settings.email_intake_user, settings.email_intake_password
    if settings.email_intake_protocol == "imap":
        port = settings.email_intake_port or (993 if settings.email_intake_ssl else 143)
        box = (imaplib.IMAP4_SSL if settings.email_intake_ssl else imaplib.IMAP4)(host, port)
        try:
            box.login(user, password)
            box.select("INBOX", readonly=True)
            _, ids = box.search(None, "ALL")
            out = []
            for num in ids[0].split():
                _, data = box.fetch(num, "(BODY.PEEK[])")  # PEEK: don't mark as seen
                out.extend(part[1] for part in data if isinstance(part, tuple))
            return out
        finally:
            try:
                box.logout()
            except Exception:
                pass
    port = settings.email_intake_port or (995 if settings.email_intake_ssl else 1110)
    box = (poplib.POP3_SSL if settings.email_intake_ssl else poplib.POP3)(host, port, timeout=20)
    try:
        box.user(user)
        box.pass_(password)
        count, _ = box.stat()
        return [b"\r\n".join(box.retr(i)[1]) for i in range(1, count + 1)]
    finally:
        box.quit()  # no DELE was issued, so nothing is removed


# ── processing ────────────────────────────────────────────────────────────

async def already_handled(session, message_id: str) -> bool:
    return (await session.execute(
        text("SELECT 1 FROM email_intake WHERE message_id = :m"), {"m": message_id}
    )).first() is not None


async def process_email(session_factory, kafka_producer, mail: Email) -> dict | None:
    """Ingest one email's attachments. Returns the intake record, or None
    when it isn't for the intake address or was handled before."""
    if not is_for_intake(mail, settings.email_intake_address):
        return None
    async with session_factory() as session:
        if await already_handled(session, mail.message_id):
            return None

    document_ids, rejections, retry = [], [], False
    if not mail.attachments:
        rejections.append({"filename": None, "reason": "no attachments"})
    for att in mail.attachments:
        reason = rejection_reason(att)
        if reason:
            rejections.append({"filename": att.filename, "reason": reason})
            continue
        async with session_factory() as db:
            try:
                await scan_upload(att.data, db, att.filename)
                doc = await store_and_record_upload(
                    db, kafka_producer, att.data, att.filename, ACCEPTED[os.path.splitext(att.filename.lower())[1]],
                    EMAIL_INTAKE_UPLOADER, source="email", source_sender=mail.sender,
                )
                document_ids.append(doc.id)
            except MalwareDetectedError as e:
                await db.commit()  # keep the scan's audit row
                rejections.append({"filename": att.filename, "reason": f"malware detected ({e.signature})"})
            except InvalidUploadError as e:
                await db.rollback()
                rejections.append({"filename": att.filename, "reason": str(e)})
            except (ScanUnavailableError, StorageUnavailableError) as e:
                await db.rollback()
                logger.warning(f"[email-intake] {mail.message_id}: {e}; will retry the whole email")
                retry = True
                break
    if retry and not document_ids:
        return None  # not recorded, so the next poll tries again

    status = "processed" if document_ids and not rejections else "partial" if document_ids else "rejected"
    record = {"message_id": mail.message_id, "sender": mail.sender, "subject": mail.subject[:500],
              "received_at": mail.received_at, "status": status,
              "document_ids": json.dumps(document_ids), "rejections": json.dumps(rejections)}
    async with session_factory() as session:
        await session.execute(text(
            "INSERT INTO email_intake (message_id, sender, subject, received_at, status, document_ids, rejections) "
            "VALUES (:message_id, :sender, :subject, :received_at, :status, CAST(:document_ids AS jsonb), "
            "CAST(:rejections AS jsonb)) ON CONFLICT (message_id) DO NOTHING"
        ), record)
        await session.commit()
    logger.info(f"[email-intake] {mail.message_id} from {mail.sender}: {status}, "
                f"{len(document_ids)} document(s), {len(rejections)} rejected")
    return {**record, "document_ids": document_ids, "rejections": rejections}


async def poll_once(session_factory, kafka_producer) -> int:
    raws = await asyncio.to_thread(fetch_all)
    handled = 0
    for raw in raws:
        try:
            if await process_email(session_factory, kafka_producer, parse(raw)):
                handled += 1
        except Exception as e:
            logger.error(f"[email-intake] a message failed, will retry next poll: {e}", exc_info=True)
    return handled


async def run_email_intake(session_factory, kafka_producer) -> None:
    logger.info(f"[email-intake] reading {settings.email_intake_protocol}://{settings.email_intake_host} for mail to "
                f"{settings.email_intake_address} every {settings.email_intake_poll_seconds}s")
    while True:
        try:
            await poll_once(session_factory, kafka_producer)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"[email-intake] mailbox unavailable: {e}")
        await asyncio.sleep(settings.email_intake_poll_seconds)
