"""Cyber and technical collectors: web, email, breach, certification (Prompt 9B section 4).
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
from app.models import Vendor, VendorEvidence
from app.services.collectors.base import record_observation, record_raw_response
from shared.live_mode.checker import is_live_verification_enabled

logger = logging.getLogger(__name__)

DEMO_DOMAINS = (".local", ".test", ".demo", ".internal", ".example", "localhost")


def derive_vendor_domain(vendor: Vendor) -> Optional[str]:
    """Derives a domain name from website, contact email, or vendor normalized name."""
    website = getattr(vendor, "website", None)
    if website and isinstance(website, str) and website.strip():
        clean = website.strip().lower()
        if "://" in clean:
            clean = clean.split("://", 1)[1]
        clean = clean.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0].strip()
        if clean:
            return clean

    email = getattr(vendor, "contact_email", None)
    if email and "@" in email:
        domain = email.split("@")[1].strip().lower()
        if domain and "." in domain:
            return domain

    norm = getattr(vendor, "normalized_name", None) or getattr(vendor, "name", "")
    clean = "".join(c for c in norm.lower() if c.isalnum() or c in ("-", "."))
    if "." in clean:
        return clean
    return f"{clean.replace(' ', '')}.com" if clean else None


async def collect_web(
    db: AsyncSession, vendor: Vendor, now: datetime
) -> Tuple[Any, Any]:
    """Collects web and TLS security posture using direct SSL handshake and HTTP headers probe."""
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

    is_demo = any(domain.endswith(ext) for ext in DEMO_DOMAINS)
    live_enabled = await is_live_verification_enabled(db)

    if is_demo:
        # Prompt 10 section 6.1: simulated pass values permitted ONLY for demo domains
        ssl_grade = "A"
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
        # Live verification disabled: do not invent pass grades
        ssl_grade = None
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
            # 1. Dual-probe: direct SSL handshake for accurate TLS version & peercert
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

            # 2. HTTP headers probe via httpx
            hsts = False
            async with httpx.AsyncClient(verify=True, timeout=5.0, follow_redirects=True) as client:
                try:
                    resp = await client.get(f"https://{domain}")
                    hsts = "strict-transport-security" in resp.headers
                except Exception:
                    pass

            # Calculate SSL grade
            if not cert_valid or tls_version in ("SSLv2", "SSLv3", "TLSv1", "TLSv1.1"):
                ssl_grade = "F"
            elif hsts and tls_version in ("TLSv1.3", "TLSv1.2"):
                ssl_grade = "A"
            elif tls_version in ("TLSv1.3", "TLSv1.2"):
                ssl_grade = "B"
            else:
                ssl_grade = "C"

            web_reachable = True
            obs_status = "ok"
        except Exception as e:
            logger.info("Live TLS probe for %s failed (%s)", domain, e)
            web_reachable = False
            ssl_grade = None
            cert_valid = False
            cert_days_left = None
            hsts = False
            cert_issuer = "—"
            cert_problem = f"Connection failed: {e}"
            tls_version = "—"
            obs_status = "error"

    fields = {
        "web.reachable": web_reachable,
        "web.ssl_grade": ssl_grade,
        "web.cert_valid": cert_valid,
        "web.cert_days_left": cert_days_left,
        "web.hsts": hsts,
        "web.cert_issuer": cert_issuer,
        "web.cert_problem": cert_problem,
        "web.confidence": confidence,
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
        {"label": "SSL Labs Grade", "value": ssl_grade if ssl_grade else "N/A"},
        {"label": "TLS Certificate", "value": "Valid" if cert_valid else ("Not Checked" if obs_status == "not_checked" else "Invalid")},
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
        # Prompt 10 section 6.1: simulated pass values permitted ONLY for demo domains
        has_mx = True
        dmarc_policy = "reject"
        spf_present = True
        obs_status = "ok"
        confidence = "simulated"
    elif not live_enabled:
        # Live verification disabled: record not_checked and do not invent reject policy
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

        # 1. Query MX records
        has_mx = False
        try:
            mx_records = await asyncio.to_thread(resolver.resolve, domain, "MX")
            has_mx = len(mx_records) > 0
        except Exception:
            has_mx = False

        # 2. Query SPF (TXT records on root domain)
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

        # 3. Query DMARC (TXT records on _dmarc.{domain})
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
    """Breach disclosure history. No live Have I Been Pwned lookup is wired
    in, so this records "not checked" rather than a clean result: a reported
    breach (e.g. ADDA / adda.io) must not be shown as "no breach listed"
    before someone has verified the record and the entity match."""
    domain = derive_vendor_domain(vendor)
    provider = "Have I Been Pwned (HIBP)"
    detail = "No live breach lookup in this deployment; verify any reported breach and its entity match by hand."
    fields = {"breach.source_reachable": False, "breach.domain": domain or "None"}

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="breach",
        provider=provider,
        request_method="NONE",
        body={"skip_reason": "no_live_source", "detail": detail, "domain": domain},
        source_id="hibp_api",
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "Status", "value": "not_checked"},
        {"label": "Domain", "value": domain or "None"},
        {"label": "Detail", "value": detail},
    ]

    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="breach",
        source_name="Breach History",
        provider=provider,
        status="not_checked",
        facts=facts,
        fields=fields,
        skip_reason="no_live_source",
        raw_response_id=raw.id,
        ttl_days=1,
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
