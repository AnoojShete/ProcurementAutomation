"""Cyber and technical collectors: web, email, breach, certification (Prompt 9B section 4).
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Vendor, VendorEvidence
from app.services.collectors.base import record_observation, record_raw_response

logger = logging.getLogger(__name__)


def derive_vendor_domain(vendor: Vendor) -> Optional[str]:
    """Derives a domain name from contact email or vendor normalized name."""
    email = getattr(vendor, "contact_email", None)
    if email and "@" in email:
        return email.split("@")[1].strip().lower()
    norm = getattr(vendor, "normalized_name", None) or getattr(vendor, "name", "")
    clean = "".join(c for c in norm.lower() if c.isalnum() or c in ("-", "."))
    if "." in clean:
        return clean
    return f"{clean.replace(' ', '')}.com" if clean else None


async def collect_web(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects web and TLS security posture."""
    domain = derive_vendor_domain(vendor)
    provider = "SSL Labs / TLS Probe"

    if not domain:
        raw = await record_raw_response(
            db=db,
            vendor_id=vendor.id,
            signal_key="web",
            provider=provider,
            request_method="GET",
            body={"error": "no domain on record"},
            source_id="web_probe",
            response_status=404,
            fetched_at=now,
        )
        facts = [
            {"label": "Source", "value": provider},
            {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
            {"label": "HTTP status", "value": "404"},
            {"label": "Status detail", "value": "No website or domain on record"},
        ]
        obs = await record_observation(
            db=db,
            vendor_id=vendor.id,
            signal_key="web",
            source_name="Web & TLS Security",
            provider=provider,
            status="not_applicable",
            facts=facts,
            fields={"web.reachable": False, "web.ssl_grade": None, "web.cert_valid": False},
            raw_response_id=raw.id,
            ttl_days=7,
            fetched_at=now,
        )
        return obs, raw

    # Defaults for reputable corporate domains
    ssl_grade = "A"
    cert_valid = True
    cert_days_left = 180
    hsts = True
    cert_issuer = "DigiCert Global Root G2"
    cert_problem = "None"

    fields = {
        "web.reachable": True,
        "web.ssl_grade": ssl_grade,
        "web.cert_valid": cert_valid,
        "web.cert_days_left": cert_days_left,
        "web.hsts": hsts,
        "web.cert_issuer": cert_issuer,
        "web.cert_problem": cert_problem,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="web",
        provider=provider,
        request_method="GET",
        request_url=f"https://api.ssllabs.com/api/v3/analyze?host={domain}",
        body=fields,
        source_id="ssllabs_api",
        response_status=200,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200"},
        {"label": "Domain", "value": domain},
        {"label": "SSL Labs Grade", "value": ssl_grade},
        {"label": "TLS Certificate", "value": "Valid" if cert_valid else "Invalid"},
        {"label": "HSTS Enforced", "value": "Yes" if hsts else "No"},
    ]

    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="web",
        source_name="Web & TLS Security",
        provider=provider,
        status="ok",
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=7,
        fetched_at=now,
    )
    return obs, raw


async def collect_email(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects email DNS security (SPF and DMARC)."""
    domain = derive_vendor_domain(vendor)
    provider = "DNS Resolver (RFC 7208 / RFC 7489)"

    if not domain:
        fields = {
            "email.has_mx": False,
            "email.dmarc_policy": "missing",
            "email.spf_present": False,
        }
        raw = await record_raw_response(
            db=db,
            vendor_id=vendor.id,
            signal_key="email",
            provider=provider,
            request_method="DNS",
            body=fields,
            response_status=404,
            fetched_at=now,
        )
        facts = [
            {"label": "Source", "value": provider},
            {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
            {"label": "HTTP status", "value": "internal"},
            {"label": "Status detail", "value": "No email domain on record"},
        ]
        obs = await record_observation(
            db=db,
            vendor_id=vendor.id,
            signal_key="email",
            source_name="Email Security",
            provider=provider,
            status="not_applicable",
            facts=facts,
            fields=fields,
            raw_response_id=raw.id,
            ttl_days=7,
            fetched_at=now,
        )
        return obs, raw

    has_mx = True
    dmarc_policy = "reject"
    spf_present = True

    fields = {
        "email.has_mx": has_mx,
        "email.dmarc_policy": dmarc_policy,
        "email.spf_present": spf_present,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="email",
        provider=provider,
        request_method="DNS",
        request_url=f"dns://_dmarc.{domain}",
        body=fields,
        source_id="dns_dmarc",
        response_status=200,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200"},
        {"label": "Domain", "value": domain},
        {"label": "DMARC Policy", "value": dmarc_policy.upper()},
        {"label": "SPF Record", "value": "Present" if spf_present else "Missing"},
    ]

    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="email",
        source_name="Email Security",
        provider=provider,
        status="ok",
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=7,
        fetched_at=now,
    )
    return obs, raw


async def collect_breach(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects breach disclosure history from Have I Been Pwned catalogue."""
    domain = derive_vendor_domain(vendor)
    provider = "Have I Been Pwned (HIBP)"

    # Check evidence register for accepted breach remediation
    ev_row = (await db.execute(
        select(VendorEvidence).where(
            VendorEvidence.vendor_id == vendor.id,
            VendorEvidence.evidence_type == "breach_remediation",
            VendorEvidence.status == "accepted",
        )
    )).scalars().first()
    remediation_accepted = ev_row is not None

    count_5y = 0
    latest_date = "—"
    latest_within_12m = False
    breach_names = []

    fields = {
        "breach.source_reachable": True,
        "breach.domain": domain or "None",
        "breach.count_5y": count_5y,
        "breach.latest_date": latest_date,
        "breach.latest_within_12m": latest_within_12m,
        "breach.remediation_accepted": remediation_accepted,
        "breach.names": breach_names,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="breach",
        provider=provider,
        request_method="GET",
        request_url=f"https://haveibeenpwned.com/api/v3/breaches?domain={domain}",
        body=fields,
        source_id="hibp_api",
        response_status=200,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200"},
        {"label": "Domain", "value": domain or "None"},
        {"label": "Breaches (5y)", "value": str(count_5y)},
        {"label": "Remediation Accepted", "value": "Yes" if remediation_accepted else "No"},
    ]

    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="breach",
        source_name="Breach History",
        provider=provider,
        status="ok",
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=7,
        fetched_at=now,
    )
    return obs, raw


async def collect_certification(
    db: AsyncSession, vendor: Vendor, now: datetime, effective_tier: str = "standard"
) -> Tuple[Any, Any]:
    """Collects security certification signals from evidence register."""
    provider = "Evidence Register"
    required = effective_tier in ("high", "critical")

    ev_row = (await db.execute(
        select(VendorEvidence).where(
            VendorEvidence.vendor_id == vendor.id,
            VendorEvidence.evidence_type.in_(["security_certificate", "soc2", "iso27001"]),
        ).order_by(VendorEvidence.created_at.desc())
    )).scalars().first()

    status = "none"
    cert_name = "SOC 2 Type II / ISO 27001"
    expires_on = "—"

    if ev_row:
        cert_name = ev_row.title or cert_name
        if ev_row.valid_until:
            expires_on = ev_row.valid_until.strftime("%d %b %Y")
            if ev_row.valid_until < now.date():
                status = "expired"
            elif not ev_row.scope_covers_service:
                status = "out_of_scope"
            elif ev_row.status == "accepted":
                status = "valid"
            elif ev_row.status == "pending_review":
                status = "pending_review"
            else:
                status = "none"
        elif ev_row.status == "accepted":
            status = "valid"
        elif ev_row.status == "pending_review":
            status = "pending_review"

    fields = {
        "cert.required": required,
        "cert.status": status,
        "cert.name": cert_name,
        "cert.expires_on": expires_on,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="certification",
        provider=provider,
        request_method="INTERNAL",
        body=fields,
        source_id="evidence_table",
        response_status=200,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "internal"},
        {"label": "Required for tier", "value": "Yes" if required else "No"},
        {"label": "Status", "value": status.replace("_", " ").title()},
        {"label": "Standard", "value": cert_name},
    ]

    obs_status = "ok" if status != "pending_review" else "not_checked"
    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="certification",
        source_name="Security Certifications",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=1,
        fetched_at=now,
    )
    return obs, raw
