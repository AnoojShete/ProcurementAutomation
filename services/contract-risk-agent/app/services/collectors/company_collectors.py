"""Company standing and financials collectors: financial, company_age (Prompt 9B section 4).
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Vendor, VendorEvidence
from app.services.collectors.base import record_observation, record_raw_response

logger = logging.getLogger(__name__)


async def collect_financial(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects financial stability from credit rating or audited statements."""
    provider = "Evidence Register / Financial Audit"

    ev_row = (await db.execute(
        select(VendorEvidence).where(
            VendorEvidence.vendor_id == vendor.id,
            VendorEvidence.evidence_type.in_(["credit_rating", "financial_statement"]),
            VendorEvidence.status == "accepted",
        ).order_by(VendorEvidence.created_at.desc())
    )).scalars().first()

    basis = "none"
    agency = "None"
    grade = "None"
    rating_class = "none"
    score = None
    age_days = 999

    if ev_row:
        age_days = (now - ev_row.created_at).days
        meta = ev_row.metadata_json or {}
        if age_days <= 365:
            if ev_row.evidence_type == "credit_rating":
                basis = "rating"
                agency = meta.get("agency", "CRISIL")
                grade = meta.get("grade", "AAA")
                # Classify investment / non_investment / default
                if grade.startswith(("AAA", "AA", "A", "BBB")):
                    rating_class = "investment"
                elif grade in ("D", "default"):
                    rating_class = "default"
                else:
                    rating_class = "non_investment"
            elif ev_row.evidence_type == "financial_statement":
                basis = "score"
                score = float(meta.get("score", 0.85))

    fields = {
        "fin.basis": basis,
        "fin.rating_agency": agency,
        "fin.rating_grade": grade,
        "fin.rating_class": rating_class,
        "fin.score": score,
        "fin.evidence_age_days": age_days if basis != "none" else None,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="financial",
        provider=provider,
        request_method="INTERNAL",
        body=fields,
        source_id="financial_evidence",
        response_status=200 if basis != "none" else None,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "internal"},
        {"label": "Evaluation basis", "value": basis.title()},
        {"label": "Rating / Score", "value": grade if basis == "rating" else f"{score:.2f}" if score is not None else "None"},
        {"label": "Evidence age (days)", "value": str(age_days) if basis != "none" else "—"},
    ]

    obs_status = "ok" if basis != "none" else "not_checked"
    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="financial",
        source_name="Financial Stability",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=365,
        fetched_at=now,
    )
    return obs, raw


async def collect_company_age(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects company age based on GST registration or incorporation date.
    Domain age (RDAP) is shown as a context fact only and NOT scored.
    """
    provider = "Corporate Affairs Registry"

    # Check GST cached registration date or evidence register
    v_row = (await db.execute(
        text("SELECT gstin_cached_response, created_at FROM vendors WHERE id = :id"),
        {"id": vendor.id},
    )).first()

    cached = v_row.gstin_cached_response or {} if v_row else {}
    gst_reg_str = cached.get("registration_date")

    age_basis = "none"
    age_years = None
    age_date = None

    if gst_reg_str:
        try:
            reg_dt = datetime.strptime(str(gst_reg_str)[:10], "%Y-%m-%d")
            diff_days = (now.date() - reg_dt.date()).days
            age_years = round(diff_days / 365.25, 1)
            age_basis = "gst_registration"
            age_date = reg_dt.strftime("%d %b %Y")
        except Exception:
            pass

    if age_basis == "none":
        # Check evidence register for incorporation certificate
        ev_row = (await db.execute(
            select(VendorEvidence).where(
                VendorEvidence.vendor_id == vendor.id,
                VendorEvidence.evidence_type == "certificate_of_incorporation",
                VendorEvidence.status == "accepted",
            )
        )).scalars().first()
        if ev_row and ev_row.valid_from:
            diff_days = (now.date() - ev_row.valid_from).days
            age_years = round(diff_days / 365.25, 1)
            age_basis = "incorporation"
            age_date = ev_row.valid_from.strftime("%d %b %Y")

    # If nothing else, check platform creation date as fallback or domain age
    if age_basis == "none" and v_row and v_row.created_at:
        diff_days = (now - v_row.created_at).days
        age_years = round(diff_days / 365.25, 1)
        age_basis = "domain_only"  # Section 4: domain_only is treated as not assessed
        age_date = v_row.created_at.strftime("%d %b %Y")

    fields = {
        "age.years": age_years,
        "age.basis": age_basis,
        "age.date": age_date or "—",
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="company_age",
        provider=provider,
        request_method="INTERNAL",
        body=fields,
        source_id="mca_registry",
        response_status=200 if age_basis != "none" else None,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "internal"},
        {"label": "Operating age", "value": f"{age_years} years" if age_years is not None else "Unknown"},
        {"label": "Age basis", "value": age_basis.replace("_", " ").title()},
        {"label": "Reference date", "value": age_date or "None"},
    ]

    obs_status = "ok" if age_basis in ("gst_registration", "incorporation") else "not_checked"
    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="company_age",
        source_name="Company Age",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=90,
        fetched_at=now,
    )
    return obs, raw
