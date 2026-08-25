"""SQLAlchemy ORM models.

Two kinds of tables here:
  - This service's own tables (notification_log, notification_digest_queue),
    created by migrations/0001_notification_tables.sql at startup — see
    app/database.py's init_db().
  - Thin read-only mappings onto a couple of columns of tables owned by
    other services (purchase_requests, contracts), used only to resolve a
    human recipient for events whose payload (per shared/schemas/events.md)
    doesn't carry one directly — e.g. contract.signed only has contract_id,
    not the requester's contact. We never write through these.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Text, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Every UUID column in Postgres must be typed as PG_UUID(as_uuid=False), not
# String, or asyncpg rejects `uuid_column = $1::varchar` comparisons. See
# services/contract-risk-agent/app/models.py for the same pattern.
Uuid = PG_UUID(as_uuid=False)


class Base(DeclarativeBase):
    pass


class NotificationLog(Base):
    """Audit trail of every notification this service has sent (or
    attempted). Backs GET /notifications/log."""
    __tablename__ = "notification_log"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="email")
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    template_name: Mapped[Optional[str]] = mapped_column(String(100))
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    body: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[Optional[str]] = mapped_column(String(20))
    related_entity_id: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sent | failed | queued_digest
    error: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class NotificationDigestQueue(Base):
    """Non-urgent events queued here instead of sent immediately; a
    periodic background task batches each recipient's queued rows into one
    email (see app/services/digest_service.py)."""
    __tablename__ = "notification_digest_queue"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    template_name: Mapped[Optional[str]] = mapped_column(String(100))
    template_context: Mapped[Optional[dict]] = mapped_column(JSON)
    related_entity_id: Mapped[Optional[str]] = mapped_column(String(255))
    flushed: Mapped[bool] = mapped_column(Boolean, default=False)
    flushed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# --- Read-only refs onto shared tables (see module docstring) ---

class PurchaseRequestRef(Base):
    __tablename__ = "purchase_requests"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    requested_by: Mapped[Optional[str]] = mapped_column(String(255))


class ContractRef(Base):
    __tablename__ = "contracts"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    purchase_request_id: Mapped[Optional[str]] = mapped_column(Uuid)
