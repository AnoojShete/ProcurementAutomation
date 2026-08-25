"""SQLAlchemy ORM models mapping to the shared database schema
(shared/db/init.sql), extended by this service's own migration
(migrations/0001_schema_extensions.sql, applied idempotently at startup —
see app/database.py). Never edit init.sql directly.
"""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Date, ForeignKey, Text, JSON, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# init.sql declares every id/FK column as native Postgres UUID, not text —
# without this, asyncpg/Postgres reject `uuid_column = $1::varchar` with
# "operator does not exist: uuid = character varying". as_uuid=False keeps
# Python-side values as plain str (matching every service's `str(uuid4())`
# id-generation convention) while binding params with the correct type.
Uuid = PG_UUID(as_uuid=False)


class Base(DeclarativeBase):
    pass


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")
    bank_account_number: Mapped[Optional[str]] = mapped_column(Text)
    routing_code: Mapped[Optional[str]] = mapped_column(Text)
    payment_beneficiary_name: Mapped[Optional[str]] = mapped_column(Text)
    payment_details_pending_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class VendorPaymentChangeRequest(Base):
    """Dual-control queue for bank/payment-detail changes on an EXISTING
    vendor (BEC-fraud control). Never applied automatically — only
    POST /vendors/{id}/verify-payment-change, submitted by someone other
    than submitted_by, moves this to 'verified' and copies new_* onto the
    live Vendor row."""
    __tablename__ = "vendor_payment_change_requests"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(Uuid, ForeignKey("vendors.id"), nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    document_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("documents.id"))
    previous_bank_account_number: Mapped[Optional[str]] = mapped_column(Text)
    previous_routing_code: Mapped[Optional[str]] = mapped_column(Text)
    previous_beneficiary_name: Mapped[Optional[str]] = mapped_column(Text)
    new_bank_account_number: Mapped[Optional[str]] = mapped_column(Text)
    new_routing_code: Mapped[Optional[str]] = mapped_column(Text)
    new_beneficiary_name: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    verified_by: Mapped[Optional[str]] = mapped_column(String(255))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    verification_channel: Mapped[Optional[str]] = mapped_column(String(50))
    verification_notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendors.id"))
    document_type: Mapped[Optional[str]] = mapped_column(String(20))  # po | invoice | quote
    extracted: Mapped[Optional[dict]] = mapped_column(JSON)  # extracted_fields payload
    confidence: Mapped[Optional[dict]] = mapped_column(JSON)  # confidence_scores payload
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|processing|classified|failed
    file_type: Mapped[Optional[str]] = mapped_column(String(10))  # pdf | image
    minio_path: Mapped[Optional[str]] = mapped_column(Text)
    original_filename: Mapped[Optional[str]] = mapped_column(Text)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(255))
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    vendor_name_raw: Mapped[Optional[str]] = mapped_column(Text)
    document_number: Mapped[Optional[str]] = mapped_column(String(100))
    document_date: Mapped[Optional[date]] = mapped_column(Date)
    total: Mapped[Optional[float]] = mapped_column(Numeric(14, 2))
    currency: Mapped[Optional[str]] = mapped_column(String(10))
    overall_confidence: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    is_likely_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_document_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("documents.id"))
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(255))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    entity_id: Mapped[Optional[str]] = mapped_column(Uuid)
    entity_type: Mapped[Optional[str]] = mapped_column(String)
    action: Mapped[Optional[str]] = mapped_column(String)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
