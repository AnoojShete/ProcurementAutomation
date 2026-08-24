"""
SQLAlchemy ORM models mapping to the shared database schema (shared/db/init.sql).

These models must match the actual PostgreSQL table definitions exactly.
The shared schema is the source of truth — never modify init.sql, use
Alembic migrations for any extensions.
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Date, ForeignKey, Text, JSON, Numeric
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Vendor(Base):
    """Vendor/supplier in the procurement system."""
    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(String, primary_key=True)
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

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[Optional[str]] = mapped_column(ForeignKey("documents.id"))
    vendor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vendors.id"))
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    spend_tier: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending_approval")
    approval_chain: Mapped[Optional[list]] = mapped_column(JSON)
    current_approver_index: Mapped[int] = mapped_column(Integer, default=0)
    sla_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    items: Mapped[Optional[list]] = mapped_column(JSON)
    backorder_parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("purchase_requests.id"))
    is_backordered: Mapped[bool] = mapped_column(Boolean, default=False)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    vendor: Mapped[Optional["Vendor"]] = relationship("Vendor", back_populates="purchase_requests")
    approval_history: Mapped[List["ApprovalHistory"]] = relationship(
        "ApprovalHistory", back_populates="purchase_request",
        cascade="all, delete-orphan"
    )


class ApprovalHistory(Base):
    """Record of each approval/rejection decision on a request."""
    __tablename__ = "approval_history"

    # Column names must match init.sql exactly
    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        ForeignKey("purchase_requests.id"), nullable=False
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

    id: Mapped[str] = mapped_column(String, primary_key=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vendors.id"))
    app_name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_per_seat: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
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

    id: Mapped[str] = mapped_column(String, primary_key=True)
    license_id: Mapped[str] = mapped_column(ForeignKey("licenses.id"), nullable=False)
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

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(50))
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    location: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Immutable audit trail for all entity changes."""
    __tablename__ = "audit_log"

    # Column names must match init.sql: performed_by, details, created_at
    id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    performed_by: Mapped[Optional[str]] = mapped_column(String(255))
    details: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Contract(Base):
    """Contract generated by the contract-risk-agent for an approved request.
    
    This service reads this table (read-only) to look up the
    purchase_request_id when handling contract.signed events.
    """
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    purchase_request_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("purchase_requests.id")
    )
    vendor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vendors.id"))
    template: Mapped[Optional[str]] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[Optional[str]] = mapped_column(String(30))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ProcessedEvent(Base):
    """Idempotency guard for Kafka consumer.

    Before processing any inbound Kafka event, the consumer checks
    whether event_id already exists in this table.  If it does, the
    event is skipped (at-least-once redelivery protection).
    """
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
