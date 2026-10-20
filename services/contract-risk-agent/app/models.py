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
    country: Mapped[Optional[str]] = mapped_column(String(2))
    activation_exempt_reason: Mapped[Optional[str]] = mapped_column(Text)
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
    score: Mapped[Optional[float]] = mapped_column(Numeric)  # payload's `risk_score` (total_points / 100.0)
    band: Mapped[Optional[str]] = mapped_column(String(10))  # payload's `risk_band` (final_band)
    details: Mapped[Optional[list]] = mapped_column(JSON)  # payload's `top_factors`
    # Added by this service's migration 0001:
    model_version: Mapped[Optional[str]] = mapped_column(String(50))
    scored_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Added by migration 0006 (FR-04): signal coverage and hard overrides.
    signals_used: Mapped[Optional[int]] = mapped_column(Integer)
    signals_total: Mapped[Optional[int]] = mapped_column(Integer)
    overrides: Mapped[Optional[list]] = mapped_column(JSON)

    # Added by migration 0008 (Prompt 9B): deterministic rule-based scorecard
    ruleset_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("risk_rulesets.id"))
    ruleset_version: Mapped[Optional[int]] = mapped_column(Integer)
    total_points: Mapped[Optional[int]] = mapped_column(Integer)
    points_band: Mapped[Optional[str]] = mapped_column(String(20))
    final_band: Mapped[Optional[str]] = mapped_column(String(20))
    override_rule_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    unassessed_potential_points: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    worst_case_points: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    worst_case_band: Mapped[Optional[str]] = mapped_column(String(20))
    is_provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    provisional_reasons: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    effective_tier: Mapped[Optional[str]] = mapped_column(String(20))
    headline: Mapped[Optional[str]] = mapped_column(Text)
    explanation: Mapped[Optional[dict]] = mapped_column(JSON)
    observation_ids: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    snapshot_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    assessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    trigger_type: Mapped[Optional[str]] = mapped_column(String(50))
    trigger_ref: Mapped[Optional[str]] = mapped_column(String(255))
    previous_score_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("risk_scores.id"))
    # Added by migration 0009 (Prompt 9C): clearance, rating status, lower bound, remediation path
    rating_status: Mapped[Optional[str]] = mapped_column(String(20), default="not_rated")
    assessed_share_pct: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    applicable_max_points: Mapped[Optional[int]] = mapped_column(Integer, default=100)
    due_diligence_potential_points: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    history_potential_points: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    points_is_lower_bound: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_by: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    remediation_path: Mapped[Optional[list]] = mapped_column(JSON, default=list)


class RiskRuleset(Base):
    __tablename__ = "risk_rulesets"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # draft, active, retired
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    activated_by: Mapped[Optional[str]] = mapped_column(String(255))
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    change_justification: Mapped[Optional[str]] = mapped_column(Text)
    dry_run_report: Mapped[Optional[dict]] = mapped_column(JSON)


class VendorSignalRawResponse(Base):
    __tablename__ = "vendor_signal_raw_responses"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(Uuid, ForeignKey("vendors.id"), nullable=False)
    signal_key: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    request_method: Mapped[str] = mapped_column(String(10), nullable=False)
    request_url_redacted: Mapped[Optional[str]] = mapped_column(Text)
    request_params_redacted: Mapped[Optional[dict]] = mapped_column(JSON)
    response_status: Mapped[Optional[int]] = mapped_column(Integer)
    response_headers_subset: Mapped[Optional[dict]] = mapped_column(JSON)
    body_text: Mapped[Optional[str]] = mapped_column(Text)
    body_object_key: Mapped[Optional[str]] = mapped_column(String(255))
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    body_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text)
    retention_until: Mapped[date] = mapped_column(Date, nullable=False)


class VendorSignalObservation(Base):
    __tablename__ = "vendor_signal_observations"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(Uuid, ForeignKey("vendors.id"), nullable=False)
    signal_key: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(100))
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)  # ok, error, rate_limited, not_checked, not_applicable
    facts: Mapped[list] = mapped_column(JSON, default=list)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    raw_response_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendor_signal_raw_responses.id"))
    evidence_id: Mapped[Optional[str]] = mapped_column(Uuid)
    record_refs: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(255), default="system")
    manual_correction: Mapped[bool] = mapped_column(Boolean, default=False)
    correction_reason: Mapped[Optional[str]] = mapped_column(Text)
    corrects_observation_id: Mapped[Optional[str]] = mapped_column(Uuid)
    # Added by migration 0009 (Prompt 9C)
    extraction: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    skip_reason: Mapped[Optional[str]] = mapped_column(Text)


class RiskScoreRuleResult(Base):
    __tablename__ = "risk_score_rule_results"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    score_id: Mapped[str] = mapped_column(Uuid, ForeignKey("risk_scores.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_key: Mapped[str] = mapped_column(String(50), nullable=False)
    group_key: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_version_hash: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), nullable=False)  # assessed, assessed_no_finding, not_assessed, not_applicable, review_pending
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    potential_points: Mapped[int] = mapped_column(Integer, nullable=False)
    override_band: Mapped[Optional[str]] = mapped_column(String(20))
    observed_fields: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    facts: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    observation_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendor_signal_observations.id"))
    raw_response_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendor_signal_raw_responses.id"))
    remediation: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    remediable: Mapped[bool] = mapped_column(Boolean, default=True)
    ages_out_on: Mapped[Optional[date]] = mapped_column(Date)
    # Added by migration 0009 (Prompt 9C)
    kind: Mapped[str] = mapped_column(String(20), default="due_diligence")
    coverage_type: Mapped[str] = mapped_column(String(20), default="full")


class VendorDecision(Base):
    __tablename__ = "vendor_decisions"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(Uuid, ForeignKey("vendors.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)  # approve, approve_with_conditions, accept_risk, reject
    decided_by: Mapped[str] = mapped_column(String(255), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    justification: Mapped[Optional[str]] = mapped_column(Text)
    conditions: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    score_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("risk_scores.id"))


class VendorAssessmentDispute(Base):
    __tablename__ = "vendor_assessment_disputes"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    score_id: Mapped[str] = mapped_column(Uuid, ForeignKey("risk_scores.id"), nullable=False)
    rule_result_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("risk_score_rule_results.id"))
    raised_by: Mapped[str] = mapped_column(String(255), nullable=False)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_id: Mapped[Optional[str]] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, upheld, rejected
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(255))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    resulting_observation_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("vendor_signal_observations.id"))
    resulting_score_id: Mapped[Optional[str]] = mapped_column(Uuid, ForeignKey("risk_scores.id"))


class VendorEvidence(Base):
    __tablename__ = "vendor_evidence"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(Uuid, ForeignKey("vendors.id"), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    document_id: Mapped[Optional[str]] = mapped_column(Uuid)
    file_key: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="pending_review")  # pending_review, accepted, rejected, expired
    metadata_json: Mapped[Optional[dict]] = mapped_column("metadata", JSON, default=dict)
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_until: Mapped[Optional[date]] = mapped_column(Date)
    scope_covers_service: Mapped[bool] = mapped_column(Boolean, default=True)
    verified_by: Mapped[Optional[str]] = mapped_column(String(255))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


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


class ProcessedWebhookEvent(Base):
    """Replay protection for the e-sign webhook (POST /webhooks/esign) —
    the provider's event id, checked before acting on a callback a second
    time."""
    __tablename__ = "processed_webhook_events"

    provider_event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    contract_id: Mapped[Optional[str]] = mapped_column(Uuid)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    entity_id: Mapped[Optional[str]] = mapped_column(Uuid)
    entity_type: Mapped[Optional[str]] = mapped_column(String)
    action: Mapped[Optional[str]] = mapped_column(String)
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ModelRoutingLog(Base):
    __tablename__ = "model_routing_log"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    document_id: Mapped[Optional[str]] = mapped_column(Uuid)
    route_name: Mapped[str] = mapped_column(String(50), nullable=False)
    model_used: Mapped[str] = mapped_column(String(50), nullable=False)
    fallback_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_reason: Mapped[Optional[str]] = mapped_column(String(50))
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(4, 3))
    duration_ms: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SanctionsScreening(Base):
    """One sanctions screening of a vendor (FR-14, migration 0007).
    status: clear | potential_match | cleared (finance reviewed a match)."""
    __tablename__ = "vendor_sanctions_screenings"

    id: Mapped[str] = mapped_column(Uuid, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(Uuid, ForeignKey("vendors.id"))
    screened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    list_version: Mapped[Optional[str]] = mapped_column(Text)
    screened_name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    matches: Mapped[list] = mapped_column(JSON, default=list)
    threshold: Mapped[Optional[float]] = mapped_column(Numeric)
    screened_by: Mapped[Optional[str]] = mapped_column(Text)
    justification: Mapped[Optional[str]] = mapped_column(Text)


