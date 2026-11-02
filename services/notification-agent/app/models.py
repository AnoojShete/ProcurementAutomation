"""SQLAlchemy ORM models.

Two kinds of tables here:
  - This service's own tables (notification_log, notification_digest_queue, privacy tables),
    created by migrations/ at startup — see app/database.py's init_db().
  - Thin read-only mappings onto a couple of columns of tables owned by
    other services (purchase_requests, contracts), used only to resolve a
    human recipient.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, Text, Boolean, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Uuid = PG_UUID(as_uuid=False)


class Base(DeclarativeBase):
    pass


class NotificationLog(Base):
    """Audit trail of every notification this service has sent (or attempted)."""
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
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sent | failed | queued_digest | skipped | suppressed
    error: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class NotificationRead(Base):
    __tablename__ = "notification_reads"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    notification_id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class NotificationDigestQueue(Base):
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


class NotificationPlaceholderClass(Base):
    __tablename__ = "notification_placeholder_classes"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    classification: Mapped[str] = mapped_column(String(20), nullable=False)  # public | internal | personal | restricted
    description: Mapped[Optional[str]] = mapped_column(Text)


class PrivacyProcessingRecord(Base):
    """Article 30 GDPR / DPDP Record of Processing Activities (ROPA)."""
    __tablename__ = "privacy_processing_records"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    activity: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    data_categories: Mapped[str] = mapped_column(Text, nullable=False)
    data_subjects: Mapped[str] = mapped_column(String(30), nullable=False)
    lawful_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    retention_rule_key: Mapped[str] = mapped_column(Text, nullable=False)
    recipients_processors: Mapped[str] = mapped_column(Text, nullable=False)
    storage_location: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_on: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class EmailSuppression(Base):
    """Suppression list preventing delivery to bounced, objected, or erased addresses."""
    __tablename__ = "email_suppressions"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    address_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(30), nullable=False)  # non_essential | all_non_security
    reason: Mapped[str] = mapped_column(String(30), nullable=False)  # bounce | complaint | objection | erased
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PrivacyRequest(Base):
    """Data Subject Requests (access, rectification, erasure, restriction, objection)."""
    __tablename__ = "privacy_requests"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_verified_by: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    handler: Mapped[Optional[str]] = mapped_column(String(255))
    outcome: Mapped[Optional[str]] = mapped_column(String(50))
    outcome_reason: Mapped[Optional[str]] = mapped_column(Text)
    second_admin_approver: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class DataProcessor(Base):
    """Sub-processors and external email / service providers register."""
    __tablename__ = "data_processors"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    dpa_reference: Mapped[Optional[str]] = mapped_column(Text)
    transfer_mechanism_note: Mapped[Optional[str]] = mapped_column(Text)
    added_by: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_on: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PrivacyIncident(Base):
    """72-hour GDPR incident register."""
    __tablename__ = "privacy_incidents"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    data_categories: Mapped[Optional[str]] = mapped_column(Text)
    subjects_affected_estimate: Mapped[int] = mapped_column(Integer, default=0)
    contained_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    authority_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    individuals_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)


# --- Read-only refs onto shared tables ---

class PurchaseRequestRef(Base):
    __tablename__ = "purchase_requests"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    requested_by: Mapped[Optional[str]] = mapped_column(String(255))
    requested_by_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class UserRef(Base):
    __tablename__ = "auth_users"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    country: Mapped[Optional[str]] = mapped_column(String(3))


class ContractRef(Base):
    __tablename__ = "contracts"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    purchase_request_id: Mapped[Optional[str]] = mapped_column(Uuid)


class CompanySmtpSettings(Base):
    __tablename__ = "company_smtp_settings"

    comp_id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=587, nullable=False)
    email_from: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(Text, nullable=False)
    enable_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
