"""SQLAlchemy ORM models mapping to the shared database schema
(shared/db/init.sql), extended by this service's own Alembic migrations
under migrations/versions/ (never edit init.sql directly).
"""
from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import (
    String, Integer, Boolean, DateTime, Date, ForeignKey, Text, JSON, Numeric
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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
    # Added by this service's migration 0001:
    status: Mapped[str] = mapped_column(String(20), default="active")
    portal_access_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    data_retention_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    offboarded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    offboarded_by: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    risk_features: Mapped[Optional["VendorRiskFeatures"]] = relationship(
        "VendorRiskFeatures", back_populates="vendor", uselist=False
    )


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    requested_by: Mapped[Optional[str]] = mapped_column(String(255))
    department: Mapped[Optional[str]] = mapped_column(String(255))
    amount: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    status: Mapped[Optional[str]] = mapped_column(String(20))
    # Added by this service's migration 0001 (needed to link a contract to a vendor + line items):
    vendor_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendors.id"))
    items: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    purchase_request_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("purchase_requests.id"))
    vendor_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendors.id"))
    template: Mapped[Optional[str]] = mapped_column(String(100))  # maps to payload's `template_used`
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # Added by this service's migration 0001:
    contract_text: Mapped[Optional[str]] = mapped_column(Text)
    renewal_type: Mapped[Optional[str]] = mapped_column(String(20))
    notice_period_days: Mapped[Optional[int]] = mapped_column(Integer)
    contract_end_date: Mapped[Optional[date]] = mapped_column(Date)
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    signed_by: Mapped[Optional[str]] = mapped_column(String(255))
    esign_provider_ref: Mapped[Optional[str]] = mapped_column(String(255))
    reconciliation_status: Mapped[Optional[str]] = mapped_column(String(30))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RiskScore(Base):
    __tablename__ = "risk_scores"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendors.id"))
    score: Mapped[Optional[float]] = mapped_column(Numeric)  # payload's `risk_score`
    band: Mapped[Optional[str]] = mapped_column(String(10))  # payload's `risk_band`
    details: Mapped[Optional[list]] = mapped_column(JSON)  # payload's `top_factors`
    # Added by this service's migration 0001:
    model_version: Mapped[Optional[str]] = mapped_column(String(50))
    scored_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class VendorRiskFeatures(Base):
    """Feature inputs to the risk model, one row per vendor. Added by this
    service's migration 0001 — kept separate from `vendors` so other
    services' reads/writes to that shared table are unaffected."""
    __tablename__ = "vendor_risk_features"

    vendor_id: Mapped[str] = mapped_column(Uuid, ForeignKey("vendors.id"), primary_key=True)
    vendor_tenure_months: Mapped[Optional[int]] = mapped_column(Integer)
    on_time_delivery_rate: Mapped[Optional[float]] = mapped_column(Numeric)
    financial_stability_score: Mapped[Optional[float]] = mapped_column(Numeric)
    breach_disclosure_count: Mapped[Optional[int]] = mapped_column(Integer)
    security_cert_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    geo_risk_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    vendor: Mapped["Vendor"] = relationship("Vendor", back_populates="risk_features")


class RiskScoreOutcome(Base):
    """Feedback dataset for drift monitoring: did a vendor we scored
    actually have an incident? Logged manually by an admin."""
    __tablename__ = "risk_score_outcomes"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    vendor_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendors.id"))
    risk_score_at_time: Mapped[Optional[float]] = mapped_column(Numeric)
    risk_band_at_time: Mapped[Optional[str]] = mapped_column(String(10))
    actual_incident_occurred: Mapped[Optional[bool]] = mapped_column(Boolean)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    logged_by: Mapped[Optional[str]] = mapped_column(String(255))
    logged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    entity_id: Mapped[Optional[str]] = mapped_column(Uuid)
    entity_type: Mapped[Optional[str]] = mapped_column(String)
    action: Mapped[Optional[str]] = mapped_column(String)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
