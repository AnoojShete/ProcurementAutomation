"""
SQLAlchemy ORM models mapping to the shared database schema (shared/db/init.sql).

These models must match the actual PostgreSQL table definitions exactly.
The shared schema is the source of truth — never modify init.sql, use
Alembic migrations for any extensions.
"""
from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Date, ForeignKey, Text, JSON, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# init.sql declares every id/FK column as native Postgres UUID, not text —
# without this, Postgres rejects `uuid_column = $1::varchar` with
# "operator does not exist: uuid = character varying". as_uuid=False keeps
# Python-side values as plain str.
Uuid = PG_UUID(as_uuid=False)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Document(Base):
    """Read-only stub: `documents` belongs to document-vendor-agent's
    domain, not this service's. It's declared minimally here only so
    SQLAlchemy can resolve PurchaseRequest.document_id's ForeignKey
    against a table it knows about — this service never queries or
    writes it directly."""
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)


class Vendor(Base):
    """Vendor/supplier in the procurement system."""
    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_normalized: Mapped[Optional[str]] = mapped_column(String(255))
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50))
    address: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    purchase_requests: Mapped[List["PurchaseRequest"]] = relationship(
        "PurchaseRequest", back_populates="vendor"
    )
    licenses: Mapped[List["License"]] = relationship(
        "License", back_populates="vendor"
    )


class PurchaseRequest(Base):
    """A purchase or license-reclaim request flowing through approval."""
    __tablename__ = "purchase_requests"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    document_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("documents.id"))
    vendor_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendors.id"))
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    spend_tier: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending_approval")
    approval_chain: Mapped[Optional[list]] = mapped_column(JSON)
    current_approver_index: Mapped[int] = mapped_column(Integer, default=0)
    sla_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    items: Mapped[Optional[list]] = mapped_column(JSON)
    backorder_parent_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("purchase_requests.id"))
    is_backordered: Mapped[bool] = mapped_column(Boolean, default=False)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    vendor: Mapped[Optional["Vendor"]] = relationship("Vendor", back_populates="purchase_requests")
    # lazy="selectin": responses are serialized (via Pydantic
    # model_validate) after the async session's implicit transaction
    # context ends, so a lazy="select" (the default) relationship access
    # there fails with "MissingGreenlet" — eager-load it instead.
    approval_history: Mapped[List["ApprovalHistory"]] = relationship(
        "ApprovalHistory", back_populates="purchase_request",
        cascade="all, delete-orphan", lazy="selectin"
    )


class ApprovalHistory(Base):
    """Record of each approval/rejection decision on a request."""
    __tablename__ = "approval_history"

    # Column names must match init.sql exactly
    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        Uuid, ForeignKey("purchase_requests.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_level: Mapped[Optional[str]] = mapped_column(String(50))
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationship — note the FK column is 'request_id'
    purchase_request: Mapped["PurchaseRequest"] = relationship(
        "PurchaseRequest", back_populates="approval_history",
        foreign_keys=[request_id]
    )


class License(Base):
    """Software license tracked for utilisation analysis."""
    __tablename__ = "licenses"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendors.id"))
    app_name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_per_seat: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    period_start: Mapped[Optional[date]] = mapped_column(Date)
    period_end: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    vendor: Mapped[Optional["Vendor"]] = relationship("Vendor", back_populates="licenses")
    usages: Mapped[List["LicenseUsage"]] = relationship("LicenseUsage", back_populates="license")


class LicenseUsage(Base):
    """Per-user usage tracking for a license (matches init.sql exactly)."""
    __tablename__ = "license_usage"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    license_id: Mapped[str] = mapped_column(Uuid, ForeignKey("licenses.id"), nullable=False)
    user_email: Mapped[str] = mapped_column(String(255), nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    login_count_30d: Mapped[int] = mapped_column(Integer, default=0)
    login_count_60d: Mapped[int] = mapped_column(Integer, default=0)
    login_count_90d: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationship
    license: Mapped["License"] = relationship("License", back_populates="usages")


class Inventory(Base):
    """Hardware inventory items with stock tracking."""
    __tablename__ = "inventory"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50))
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    location: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Immutable audit trail for all entity changes."""
    __tablename__ = "audit_log"

    # Column names must match init.sql: performed_by, details, created_at
    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    performed_by: Mapped[Optional[str]] = mapped_column(String(255))
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
