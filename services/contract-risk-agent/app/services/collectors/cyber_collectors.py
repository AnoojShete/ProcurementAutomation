"""Cyber and technical collectors: web, email, breach, certification (Prompt 9B section 4, Prompt 11).
"""
import asyncio
import logging
import ssl
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
import httpx
import dns.resolver
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Vendor, VendorEvidence, VendorWaiver
from app.services.collectors.base import record_observation, record_raw_response
from app.services.breach_catalogue import match_vendor_breaches, clean_domain
from shared.live_mode.checker import is_live_verification_enabled
from shared.rules_engine import get_rule

logger = logging.getLogger(__name__)

DEMO_DOMAINS = (".local", ".test", ".demo", ".internal", ".example", "localhost")


def derive_vendor_domain(vendor: Vendor) -> Optional[str]:
    """The vendor's domain from its website or contact email; None if neither is
    on record. Never guessed from the name: a guessed domain that fails a check
    would charge the vendor for a site that isn't theirs."""
    website = getattr(vendor, "website", None)
    if website and isinstance(website, str) and website.strip():
        clean = clean_domain(website)
        if clean:
            return clean

    email = getattr(vendor, "contact_email", None)
    if email and "@" in email:
        domain = email.split("@")[1].strip().lower()
        if domain and "." in domain:
            return clean_domain(domain)
    return None


async def collect_web(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects web and TLS security posture using direct SSL handshake and HTTP headers probe.
    Prompt 11 Section 3.7: Labelled 'Direct TLS probe'. Never compute or invent an SSL Labs letter grade.
    web.ssl_grade is filled only from a real SSL Labs result; otherwise null.
    """
    domain = derive_vendor_domain(vendor)
    provider = "Direct TLS probe"

    if not domain:
        raw = await record_raw_response(
            db=db,
            vendor_id=vendor.id,
            signal_key="web",
            provider=provider,
            request_method="GET",
            body={"error": "no domain on record"},
            source_id="tls_probe",
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
            fields={"web.reachable": False, "web.ssl_grade": None, "web.cert_valid": None, "na_reason_code": "no_domain"},
            raw_response_id=raw.id,
            ttl_days=7,
            fetched_at=now,
        )
        return obs, raw

    is_demo = any(domain.endswith(ext) for ext in DEMO_DOMAINS)
    live_enabled = await is_live_verification_enabled(db)

    cert_valid = False
    cert_days_left = None
    hsts = False
    cert_issuer = "—"
    cert_problem = "None"
    tls_version = "—"
    web_reachable = False
    ssl_grade = None  # Prompt 11 Section 3.7: ALWAYS None unless actual SSL Labs response
    tls_probe_grade = None

    if is_demo:
        cert_valid = True
        cert_days_left = 180
        hsts = True
        cert_issuer = "DigiCert Global Root G2"
        cert_problem = "None"
        tls_version = "TLSv1.3"
        web_reachable = True
        obs_status = "ok"
        confidence = "simulated"
    elif not live_enabled:
        cert_valid = False
        cert_days_left = None
        hsts = False
        cert_issuer = "—"
        cert_problem = "Live verification disabled"
        tls_version = "—"
        web_reachable = False
        obs_status = "not_checked"
        confidence = "unverified"
    else:
        confidence = "live"
        try:
            # Direct SSL handshake for accurate TLS version & peercert
            ctx = ssl.create_default_context()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(domain, 443, ssl=ctx, server_hostname=domain),
                timeout=6.0,
            )
            ssl_obj = writer.get_extra_info("ssl_object")
            peercert = writer.get_extra_info("peercert") or {}
            tls_version = ssl_obj.version() if ssl_obj else "TLSv1.2"
            not_after_str = peercert.get("notAfter")
            writer.close()
            await writer.wait_closed()

            cert_days_left = None
            cert_valid = False
            cert_problem = "None"
            if not_after_str:
                try:
                    expiry = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                    cert_days_left = (expiry - now).days
                    cert_valid = cert_days_left > 0
                    if not cert_valid:
                        cert_problem = "Certificate expired"
                except Exception as ex:
                    logger.debug("Failed parsing cert expiry %s: %s", not_after_str, ex)

            # Extract issuer name
            cert_issuer = "—"
            issuer_tuples = peercert.get("issuer", ())
            for rdn in issuer_tuples:
                for k, v in rdn:
                    if k in ("organizationName", "commonName"):
                        cert_issuer = v
                        break

            # HTTP headers probe for HSTS
            hsts = False
            async with httpx.AsyncClient(verify=True, timeout=5.0, follow_redirects=True) as client:
                try:
                    resp = await client.get(f"https://{domain}")
                    hsts = "strict-transport-security" in resp.headers
                except Exception:
                    pass

            web_reachable = True
            obs_status = "ok"
        except Exception as e:
            logger.info("Direct TLS probe for %s failed (%s)", domain, e)
            web_reachable = False
            cert_valid = False
            cert_days_left = None
            hsts = False
            cert_issuer = "—"
            cert_problem = f"Connection failed: {e}"
            tls_version = "—"
            obs_status = "error"

    fields = {
        "web.reachable": web_reachable,
        "web.ssl_grade": ssl_grade,  # Prompt 11: None (no fake SSL Labs grade)
        "web.tls_probe_grade": tls_probe_grade,
        "web.cert_valid": cert_valid,
        "web.cert_days_left": cert_days_left,
        "web.hsts": hsts,
        "web.cert_issuer": cert_issuer,
        "web.cert_problem": cert_problem,
        "web.confidence": confidence,
        "web.tls_version": tls_version,
        "web.source_label": "Direct TLS probe",
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="web",
        provider=provider,
        request_method="GET",
        request_url=f"https://{domain}",
        body=fields,
        source_id="tls_probe",
        response_status=200 if web_reachable else (404 if obs_status == "not_checked" else 502),
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200" if web_reachable else ("not_checked" if obs_status == "not_checked" else "502")},
        {"label": "Domain", "value": domain},
        {"label": "TLS Version", "value": tls_version if web_reachable else "—"},
        {"label": "TLS Certificate", "value": "Valid" if cert_valid else ("Not Checked" if obs_status == "not_checked" else "Invalid")},
        {"label": "Certificate Issuer", "value": cert_issuer},
        {"label": "Days to Expiry", "value": str(cert_days_left) if cert_days_left is not None else "—"},
        {"label": "HSTS Enforced", "value": "Yes" if hsts else "No"},
        {"label": "Confidence", "value": confidence},
    ]

    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="web",
        source_name="Web & TLS Security",
        provider=provider,
        status=obs_status,
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
    """Collects email DNS security (SPF and DMARC) via real DNS lookups."""
    domain = derive_vendor_domain(vendor)
    provider = "DNS Resolver (RFC 7208 / RFC 7489)"

    if not domain:
        fields = {
            "email.has_mx": False,
            "email.dmarc_policy": "missing",
            "email.spf_present": False,
            "na_reason_code": "no_email_domain",
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

    is_demo = any(domain.endswith(ext) for ext in DEMO_DOMAINS)
    live_enabled = await is_live_verification_enabled(db)

    if is_demo:
        has_mx = True
        dmarc_policy = "reject"
        spf_present = True
        obs_status = "ok"
        confidence = "simulated"
    elif not live_enabled:
        has_mx = False
        dmarc_policy = "missing"
        spf_present = False
        obs_status = "not_checked"
        confidence = "unverified"
    else:
        confidence = "live"
        obs_status = "ok"
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 4.0

        # Query MX records
        has_mx = False
        try:
            mx_records = await asyncio.to_thread(resolver.resolve, domain, "MX")
            has_mx = len(mx_records) > 0
        except Exception:
            has_mx = False

        # Query SPF
        spf_present = False
        try:
            txt_records = await asyncio.to_thread(resolver.resolve, domain, "TXT")
            for rdata in txt_records:
                txt_val = b"".join(rdata.strings).decode("utf-8", errors="ignore")
                if txt_val.startswith("v=spf1"):
                    spf_present = True
                    break
        except Exception:
            spf_present = False

        # Query DMARC
        dmarc_policy = "missing"
        try:
            dmarc_records = await asyncio.to_thread(resolver.resolve, f"_dmarc.{domain}", "TXT")
            for rdata in dmarc_records:
                txt_val = b"".join(rdata.strings).decode("utf-8", errors="ignore")
                if txt_val.startswith("v=DMARC1"):
                    for part in txt_val.split(";"):
                        part = part.strip()
                        if part.startswith("p="):
                            dmarc_policy = part.split("=", 1)[1].strip().lower()
                    break
        except Exception:
            dmarc_policy = "missing"

        if not has_mx and not spf_present and dmarc_policy == "missing":
            obs_status = "error"

    fields = {
        "email.has_mx": has_mx,
        "email.dmarc_policy": dmarc_policy,
        "email.spf_present": spf_present,
        "email.confidence": confidence,
        "na_reason_code": "no_mx_records" if not has_mx else None,
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
        response_status=200 if obs_status == "ok" else (404 if obs_status == "not_checked" else 502),
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200" if obs_status == "ok" else ("not_checked" if obs_status == "not_checked" else "502")},
        {"label": "Domain", "value": domain},
        {"label": "DMARC Policy", "value": dmarc_policy.upper()},
        {"label": "SPF Record", "value": "Present" if spf_present else "Missing"},
        {"label": "MX Records", "value": "Present" if has_mx else "Missing"},
        {"label": "Confidence", "value": confidence},
    ]

    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="email",
        source_name="Email Security",
        provider=provider,
        status=obs_status,
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
    """Breach disclosure history using local Have I Been Pwned catalogue (Prompt 11 Section 1).
    Phase 0: local database only, zero external network calls.
    """
    domain = derive_vendor_domain(vendor)
    provider = "Have I Been Pwned (HIBP)"

    # Get max age and match pct from rules
    max_age_days = get_rule("risk.breach_catalogue_max_age_days", fallback=30)
    match_pct = get_rule("risk.breach_name_match_pct", fallback=85)

    res = await match_vendor_breaches(
        db=db,
        vendor=vendor,
        vendor_domain=domain,
        now=now,
        max_age_days=int(max_age_days),
        name_match_pct=int(match_pct),
    )

    catalogue_loaded = res.get("catalogue_loaded", False)
    domain_matches = res.get("records_domain_match", [])
    name_candidates = res.get("records_name_candidate", [])

    # Single-record helper placeholders for templates like R-BRC-08
    cand_sample = name_candidates[0] if name_candidates else {}
    record_name = cand_sample.get("title") or cand_sample.get("name") or "—"
    breach_date = cand_sample.get("breach_date") or "—"
    pwn_count = str(cand_sample.get("pwn_count") or 0)
    record_domain = cand_sample.get("domain") or "—"
    vendor_domain_str = domain or "—"

    fields = {
        "breach.source_reachable": catalogue_loaded,
        "breach.catalogue_loaded": catalogue_loaded,
        "breach.domain": domain or "None",
        "breach.count_5y": res.get("count_5y", 0),
                "breach.latest_date": res.get("latest_date", "—"),
        "breach.latest_within_12m": res.get("latest_within_12m", False),
        "breach.latest_breach_name": res.get("latest_breach_name") or "—",
        "breach.remediation_accepted": res.get("remediation_accepted", False),
        "breach.records_domain_match": [r["name"] for r in domain_matches],
        "breach.records_name_candidate": [r["name"] for r in name_candidates],
        "breach.catalogue_version": res.get("catalogue_version", "none"),
        "breach.catalogue_fetched_at": res.get("catalogue_fetched_at", "—"),
        "breach.review_state": res.get("review_state", "none"),
        "breach.not_assessed_reason": res.get("not_assessed_reason", ""),
        # Global placeholders for R-BRC-08 template
        "record_name": record_name,
        "breach_date": breach_date,
        "pwn_count": pwn_count,
        "record_domain": record_domain,
        "vendor_domain": vendor_domain_str,
    }

    obs_status = "ok" if catalogue_loaded else "not_checked"

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="breach",
        provider=provider,
        request_method="INTERNAL",
        body=fields,
        source_id="hibp_catalogue",
        response_status=200 if catalogue_loaded else 404,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Attribution", "value": "Breach data from Have I Been Pwned"},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "Domain", "value": domain or "None"},
        {"label": "Catalogue Version", "value": res.get("catalogue_version", "none")},
        {"label": "Review State", "value": res.get("review_state", "none").title()},
    ]

    # Print every matched record exactly as stored (Prompt 11 Section 1.2)
    for r in domain_matches:
        facts.append({
            "label": f"Domain Match: {r['name']}",
            "value": f"{r['title']} ({r['domain']}, {r['breach_date']}, {r['pwn_count']} accounts) - {r['description'][:100]} | Link: {r['link']}"
        })
    for r in name_candidates:
        facts.append({
            "label": f"Candidate: {r['name']}",
            "value": f"{r['title']} ({r['domain']}, {r['breach_date']}, {r['pwn_count']} accounts) - {r['description'][:100]} | Link: {r['link']}"
        })

    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="breach",
        source_name="Breach History",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        skip_reason=res.get("not_assessed_reason") or None,
        raw_response_id=raw.id,
        ttl_days=7,
        fetched_at=now,
    )
    return obs, raw


async def collect_certification(
    db: AsyncSession, vendor: Vendor, now: datetime, effective_tier: str = "standard"
) -> Tuple[Any, Any]:
    """Collects security certification signals from evidence register and checks waivers (Prompt 11 Section 3.6)."""
    provider = "Evidence Register"

    # 1. Check for active waiver
    waiver_row = (await db.execute(
        text("SELECT rationale, approved_by, valid_until FROM vendor_waivers WHERE vendor_id = :vid AND waiver_type = 'certification' AND active = true AND valid_until >= :now ORDER BY approved_at DESC LIMIT 1"),
        {"vid": vendor.id, "now": now}
    )).first()

    waived = waiver_row is not None
    waiver_justification = waiver_row.rationale if waiver_row else ""
    waiver_expires_on = waiver_row.valid_until.strftime("%d %b %Y") if waiver_row else "—"

    # 2. Check tier requirements from rule
    cert_map = get_rule("risk.required_certifications_by_tier", fallback={
        "critical": ["ISO 27001 or SOC 2 report covering the service"],
        "high": ["ISO 27001 or SOC 2 report covering the service"],
        "moderate": [],
        "low": [],
    })
    req_certs = cert_map.get(effective_tier.lower(), [])
    tier_required = len(req_certs) > 0

    required = tier_required and not waived

    ev_row = (await db.execute(
        select(VendorEvidence).where(
            VendorEvidence.vendor_id == vendor.id,
            VendorEvidence.evidence_type.in_(["security_certificate", "soc2", "iso27001"]),
        ).order_by(VendorEvidence.created_at.desc())
    )).scalars().first()

    status = "none"
    cert_name = "SOC 2 Type II / ISO 27001"
    expires_on = "—"

    if waived:
        status = "waived"
    elif ev_row:
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

    waiver_approver = waiver_row.approved_by if waiver_row else ""
    fields = {
        "cert.required": required,
        "cert.tier_exempt": not tier_required,
        "cert.status": status,
        "cert.name": cert_name,
        "cert.expires_on": expires_on,
        "cert.waived": waived,
        "cert.waiver_approver": waiver_approver,
        "cert.waiver_justification": waiver_justification,
        "cert.waiver_expires_on": waiver_expires_on,
        "justification": waiver_justification,
        "expires_on": waiver_expires_on,
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
    if waived:
        facts.append({"label": "Waiver", "value": f"Waived until {waiver_expires_on}: {waiver_justification}"})

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
