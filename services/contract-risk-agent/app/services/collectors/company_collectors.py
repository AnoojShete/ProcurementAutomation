"""Company standing and financials collectors: financial, company_age (Prompt 9B section 4).
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Vendor, VendorEvidence
from app.services.collectors.base import record_observation, record_raw_response
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)

# Figures finance enters from a vendor's latest audited statements (any one
# currency unit, e.g. Rs crore). See docs/business-rules.md, "Financial
# statement score".
STATEMENT_FIGURES = ("total_equity", "profit_after_tax", "current_assets",
                     "current_liabilities", "total_borrowings")


def financial_statement_score(meta: Dict[str, Any]) -> Tuple[Optional[float], list, list]:
    """Score audited statements from 0 to 1: the share of five checks passed.

    Returns (score, checks, missing). score is None when a figure or the
    audit opinion is missing (financial is then not assessed). A going-concern
    doubt in the audit report scores 0 whatever the figures say.
    """
    missing = [k for k in STATEMENT_FIGURES if meta.get(k) is None]
    if not meta.get("audit_opinion"):
        missing.append("audit_opinion")
    if missing:
        return None, [], missing
    f = {k: float(meta[k]) for k in STATEMENT_FIGURES}
    min_current_ratio = float(get_rule("risk.financial_min_current_ratio", fallback=1.2))
    max_debt_to_equity = float(get_rule("risk.financial_max_debt_to_equity", fallback=1.0))
    current_ratio = f["current_assets"] / f["current_liabilities"] if f["current_liabilities"] > 0 else float("inf")
    debt_to_equity = f["total_borrowings"] / f["total_equity"] if f["total_equity"] > 0 else float("inf")
    checks = [
        ("Positive net worth", f["total_equity"] > 0, f"equity {f['total_equity']:,.2f}"),
        ("Profitable year", f["profit_after_tax"] > 0, f"profit after tax {f['profit_after_tax']:,.2f}"),
        (f"Current ratio at least {min_current_ratio:g}", current_ratio >= min_current_ratio,
         f"current ratio {current_ratio:.2f}"),
        (f"Debt to equity at most {max_debt_to_equity:g}", debt_to_equity <= max_debt_to_equity,
         f"debt to equity {debt_to_equity:.2f}"),
        ("Unmodified audit opinion", str(meta["audit_opinion"]).lower() == "unmodified",
         f"opinion {meta['audit_opinion']}"),
    ]
    score = sum(passed for _, passed, _ in checks) / len(checks)
    if meta.get("going_concern_doubt"):
        checks.append(("No going-concern doubt", False, "auditor reports a material uncertainty"))
        score = 0.0
    return round(score, 2), checks, []


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
    checks: list = []
    missing: list = []

    if ev_row:
        age_days = (now - ev_row.created_at).days
        meta = ev_row.metadata_json or {}
        if ev_row.evidence_type == "financial_statement" and ev_row.valid_from:
            # Statements age from the end of the period they cover, not the upload.
            age_days = (now.date() - ev_row.valid_from).days
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
                score, checks, missing = financial_statement_score(meta)
                if score is not None:
                    basis = "score"

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
    facts += [{"label": name, "value": f"{'pass' if passed else 'fail'} ({detail})"} for name, passed, detail in checks]
    if missing:
        facts.append({"label": "Statement incomplete", "value": "missing " + ", ".join(missing)})

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
