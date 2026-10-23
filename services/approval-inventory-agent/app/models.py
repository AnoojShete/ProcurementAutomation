"""
SQLAlchemy ORM models mapping to the shared database schema (shared/db/init.sql).

These models must match the actual PostgreSQL table definitions exactly.
The shared schema is the source of truth — never modify init.sql, use
Alembic migrations for any extensions.
"""
import uuid
from datetime import datetime, date, timezone
from typing import Optional, List
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Date, ForeignKey, Text, JSON, Numeric
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates

from shared.lifecycle import check_transition

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


class Contract(Base):
    """Read-only stub: used for contract.signed event processing."""
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    purchase_request_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("purchase_requests.id"))
    # Mapped because the contract.signed handler falls back to it when
    # deciding which licenses to activate.
    vendor_id: Mapped[Optional[str]] = mapped_column(Uuid)


class ProcessedEvent(Base):
    """Idempotency tracking for Kafka consumer."""
    __tablename__ = "processed_kafka_events"

    # The table has a DB-side default, but SQLAlchemy needs a Python-side one
    # too or it refuses to flush a row with a NULL identity — which rolled back
    # the invoice_received status update along with it.
    id: Mapped[str] = mapped_column(Uuid, primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(Uuid, unique=True, nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

class Vendor(Base):
    """Vendor/supplier in the procurement system."""
    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[Optional[str]] = mapped_column(String(255))
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50))
    address: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="onboarding")
    inherent_tier: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    swift_bic: Mapped[Optional[str]] = mapped_column(String(11), nullable=True)
    bank_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    website: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    purchase_requests: Mapped[List["PurchaseRequest"]] = relationship(
        "PurchaseRequest", back_populates="vendor"
    )
    licenses: Mapped[List["License"]] = relationship(
        "License", back_populates="vendor"
    )


class Budget(Base):
    """Money set aside for one department, IT category and fiscal period.
    Usage is computed from the requests that point at it, not stored."""
    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True, default=lambda: str(uuid.uuid4()))
    fiscal_year: Mapped[str] = mapped_column(String(7), nullable=False)
    period: Mapped[str] = mapped_column(String(2), nullable=False)
    department: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_inr: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


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
    # Budget check at creation (app/services/budget_service.py): which budget
    # the request draws on, the result, and the figures it was based on.
    budget_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("budgets.id"))
    budget_status: Mapped[Optional[str]] = mapped_column(String(12))
    budget_check: Mapped[Optional[dict]] = mapped_column(JSON)
    # Phase 3: advisory notes for the request page (e.g. "above the RFQ
    # threshold with no RFQ or catalog price"), and the RFQ it was awarded from.
    sourcing_flags: Mapped[Optional[list]] = mapped_column(JSON)
    rfq_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("rfq_events.id"))

    @property
    def is_over_budget(self) -> bool:
        """Read by the e-mail approval page (rule approval.email_action_allowed_over_budget)."""
        return self.budget_status == "over"

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

    @validates("status")
    def _validate_status(self, _key, new_status):
        # Every status write — API, Temporal activity, Kafka handler,
        # reconciler — must be a legal transition (shared/lifecycle.py).
        check_transition(self.status, new_status)
        return new_status


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
    assigned_seats: Mapped[int] = mapped_column(Integer, default=0)
    cost_per_seat: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    period_start: Mapped[Optional[date]] = mapped_column(Date)
    period_end: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")
    reclaim_cooldown_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_scored_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    anomaly_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    top_factors: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    vendor: Mapped[Optional["Vendor"]] = relationship("Vendor", back_populates="licenses")
    usages: Mapped[List["LicenseUsage"]] = relationship("LicenseUsage", back_populates="license")
    reclaim_history: Mapped[List["LicenseReclaimHistory"]] = relationship("LicenseReclaimHistory", back_populates="license")


class LicenseReclaimHistory(Base):
    """Audit and timeline of reclaim events for a license."""
    __tablename__ = "license_reclaim_history"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    license_id: Mapped[str] = mapped_column(Uuid, ForeignKey("licenses.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    by_user: Mapped[Optional[str]] = mapped_column(String(255))
    cooldown_set_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    license: Mapped["License"] = relationship("License", back_populates="reclaim_history")


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
    # BR-5: None = rule default (see services/reorder.py)
    reorder_point: Mapped[Optional[int]] = mapped_column(Integer)
    reorder_quantity: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class CatalogItem(Base):
    """Phase 3: an approved IT item with its agreed price (catalog_service.py)."""
    __tablename__ = "catalog_items"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True, default=lambda: str(uuid.uuid4()))
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    vendor_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendors.id"))
    contract_id: Mapped[Optional[str]] = mapped_column(Uuid)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    inventory_sku: Mapped[Optional[str]] = mapped_column(String(100))
    license_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("licenses.id"))
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer)
    warranty_months: Mapped[Optional[int]] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_until: Mapped[Optional[date]] = mapped_column(Date)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RfqEvent(Base):
    """Phase 3: a request for quotation (sourcing_service.py)."""
    __tablename__ = "rfq_events"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True, default=lambda: str(uuid.uuid4()))
    reference: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str] = mapped_column(String(255), nullable=False)
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    items: Mapped[list] = mapped_column(JSON, default=list)
    criteria: Mapped[dict] = mapped_column(JSON, nullable=False)
    sealed: Mapped[bool] = mapped_column(Boolean, default=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="open")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    awarded_vendor_id: Mapped[Optional[str]] = mapped_column(Uuid)
    awarded_response_id: Mapped[Optional[str]] = mapped_column(Uuid)
    awarded_request_id: Mapped[Optional[str]] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class RfqInvitation(Base):
    __tablename__ = "rfq_invitations"

    rfq_id: Mapped[str] = mapped_column(Uuid, ForeignKey("rfq_events.id"), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(Uuid, ForeignKey("vendors.id"), primary_key=True)
    round: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    declined_reason: Mapped[Optional[str]] = mapped_column(Text)


class RfqResponse(Base):
    __tablename__ = "rfq_responses"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True, default=lambda: str(uuid.uuid4()))
    rfq_id: Mapped[str] = mapped_column(Uuid, ForeignKey("rfq_events.id"), nullable=False)
    vendor_id: Mapped[str] = mapped_column(Uuid, ForeignKey("vendors.id"), nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_id: Mapped[Optional[str]] = mapped_column(Uuid)
    total_inr: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer)
    warranty_months: Mapped[Optional[int]] = mapped_column(Integer)
    support_rating: Mapped[Optional[int]] = mapped_column(Integer)
    support_terms: Mapped[Optional[str]] = mapped_column(Text)
    line_items: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(10), default="manual")
    submitted_by: Mapped[Optional[str]] = mapped_column(String(255))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class GoodsReceipt(Base):
    """Phase 3: one delivery against a request (receipt_service.py)."""
    __tablename__ = "goods_receipts"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id: Mapped[str] = mapped_column(Uuid, ForeignKey("purchase_requests.id"), nullable=False)
    lines: Mapped[list] = mapped_column(JSON, nullable=False)
    received_by: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    notes: Mapped[Optional[str]] = mapped_column(Text)


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


class EmailActionToken(Base):
    """Single-action token for approval/rejection via email link (Prompt 8 Part A)."""
    __tablename__ = "email_action_tokens"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(Uuid, ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False)
    approver_id: Mapped[str] = mapped_column(String(255), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    used_action: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    used_ip: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    used_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    purchase_request: Mapped["PurchaseRequest"] = relationship("PurchaseRequest")
