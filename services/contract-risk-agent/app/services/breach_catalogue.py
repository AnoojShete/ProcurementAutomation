"""Breach catalogue management and deterministic entity matching (Prompt 11 Section 1).
"""
import asyncio
import gzip
import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import httpx
from rapidfuzz import fuzz
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import BreachCatalogue, BreachCatalogueMeta, BreachVendorReview, Vendor

logger = logging.getLogger(__name__)

HIBP_URL = "https://haveibeenpwned.com/api/v3/breaches"
USER_AGENT = "ProcurementIntelligence/1.0 (academic project; contact admin@procure.internal)"

COMMON_DICTIONARY_WORDS = {
    "tech", "soft", "info", "data", "link", "plus", "star", "blue", "fast", "best",
    "core", "corp", "team", "flow", "work", "shop", "club", "home", "care", "line",
    "life", "city", "bank", "gold", "auto", "open", "free", "view", "mail", "host",
}


def clean_domain(domain: Optional[str]) -> Optional[str]:
    """Strips protocol, www., paths, query params and port, lowercased."""
    if not domain or not isinstance(domain, str):
        return None
    d = domain.strip().lower()
    if "://" in d:
        d = d.split("://", 1)[1]
    d = d.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0].strip()
    if d.startswith("www."):
        d = d[4:]
    return d or None


def is_short_or_common(term: str) -> bool:
    """Checks if a term is 4 characters or fewer, or a common dictionary word."""
    t = term.strip().lower()
    return len(t) <= 4 or t in COMMON_DICTIONARY_WORDS


async def get_latest_catalogue_meta(db: AsyncSession) -> Optional[BreachCatalogueMeta]:
    """Returns the most recent catalogue metadata record."""
    stmt = select(BreachCatalogueMeta).order_by(BreachCatalogueMeta.fetched_at.desc()).limit(1)
    res = await db.execute(stmt)
    return res.scalars().first()


async def download_and_store_catalogue(
    db: AsyncSession,
    source: str = "download",
    uploaded_by: Optional[str] = None,
    raw_json_str: Optional[str] = None,
) -> Tuple[bool, str, int]:
    """Downloads or imports HIBP breach catalogue.
    Only keeps records where is_verified=true, is_fabricated=false, is_spam_list=false, is_retired=false.
    Returns (success, message, record_count).
    """
    body_text = raw_json_str
    if body_text is None:
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(HIBP_URL, headers={"User-Agent": USER_AGENT})
                if resp.status_code != 200:
                    logger.warning("HIBP catalogue fetch returned HTTP %s", resp.status_code)
                    return False, f"HIBP returned HTTP {resp.status_code}", 0
                body_text = resp.text
        except Exception as e:
            logger.warning("HIBP catalogue download failed: %s", e)
            return False, f"Network error: {e}", 0

    body_bytes = body_text.encode("utf-8")
    version_sha256 = hashlib.sha256(body_bytes).hexdigest()
    now = datetime.now(timezone.utc)

    try:
        raw_entries = json.loads(body_text)
        if not isinstance(raw_entries, list):
            return False, "Invalid catalogue JSON: expected a list of breach objects", 0
    except Exception as e:
        return False, f"JSON parse error: {e}", 0

    # Filter per Prompt 11 Section 1.1:
    # Use only records with is_verified=true and is_fabricated=false and is_spam_list=false and is_retired=false
    valid_entries = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        is_verified = bool(item.get("IsVerified", False))
        is_fabricated = bool(item.get("IsFabricated", False))
        is_spam_list = bool(item.get("IsSpamList", False))
        is_retired = bool(item.get("IsRetired", False))
        if is_verified and not is_fabricated and not is_spam_list and not is_retired:
            valid_entries.append(item)

    # Store in database
    # Clear old entries for idempotent replacement, or insert with version
    await db.execute(text("DELETE FROM breach_catalogue WHERE catalogue_version = :ver"), {"ver": version_sha256})

    for item in valid_entries:
        b_date = None
        b_date_str = item.get("BreachDate")
        if b_date_str:
            try:
                b_date = datetime.strptime(str(b_date_str)[:10], "%Y-%m-%d").date()
            except Exception:
                b_date = None

        a_date = None
        a_date_str = item.get("AddedDate")
        if a_date_str:
            try:
                a_date = datetime.strptime(str(a_date_str)[:10], "%Y-%m-%d").date()
            except Exception:
                a_date = None

        raw_domain = clean_domain(item.get("Domain"))
        entry = BreachCatalogue(
            name=str(item.get("Name") or "Unknown"),
            title=str(item.get("Title") or item.get("Name") or ""),
            domain=raw_domain,
            breach_date=b_date,
            added_date=a_date,
            pwn_count=int(item.get("PwnCount") or 0),
            data_classes=item.get("DataClasses") or [],
            description=str(item.get("Description") or "")[:2000],
            is_verified=bool(item.get("IsVerified", True)),
            is_fabricated=bool(item.get("IsFabricated", False)),
            is_sensitive=bool(item.get("IsSensitive", False)),
            is_retired=bool(item.get("IsRetired", False)),
            is_spam_list=bool(item.get("IsSpamList", False)),
            is_malware=bool(item.get("IsMalware", False)),
            catalogue_version=version_sha256,
            fetched_at=now,
        )
        db.add(entry)

    # Record metadata
    meta = BreachCatalogueMeta(
        version_sha256=version_sha256,
        fetched_at=now,
        record_count=len(valid_entries),
        source=source,
        uploaded_by=uploaded_by,
        raw_object_key=f"breach-catalogue/{version_sha256}.json.gz",
    )
    db.add(meta)
    await db.commit()
    logger.info("Stored breach catalogue v%s with %d records", version_sha256[:10], len(valid_entries))
    return True, f"Successfully loaded {len(valid_entries)} verified records", len(valid_entries)


async def match_vendor_breaches(
    db: AsyncSession,
    vendor: Vendor,
    vendor_domain: Optional[str],
    now: datetime,
    max_age_days: int = 30,
    name_match_pct: int = 85,
) -> Dict[str, Any]:
    """Deterministic local entity matching for breach disclosures (Prompt 11 Section 1.2).
    Runs in Phase 0 (local DB only, zero network calls).
    """
    meta = await get_latest_catalogue_meta(db)
    if meta is None or (now - meta.fetched_at).days > max_age_days:
        reason = "breach catalogue missing or older than 30 days"
        return {
            "catalogue_loaded": False,
            "not_assessed_reason": reason,
            "records_domain_match": [],
            "records_name_candidate": [],
            "count_5y": 0,
            "latest_date": "—",
            "latest_within_12m": False,
            "review_state": "none",
            "catalogue_version": "none",
            "catalogue_fetched_at": "—",
            "remediation_accepted": False,
        }

    v_dom = clean_domain(vendor_domain)
    v_dom_label = v_dom.split(".")[0] if v_dom else ""

    # Fetch reviewer decisions for this vendor
    reviews_res = await db.execute(
        text("SELECT breach_name, decision FROM breach_vendor_reviews WHERE vendor_id = :vid"),
        {"vid": vendor.id},
    )
    review_decisions = {r.breach_name: r.decision for r in reviews_res.all()}

    # Query all active catalogue records matching this version
    entries_res = await db.execute(
        select(BreachCatalogue).where(BreachCatalogue.catalogue_version == meta.version_sha256)
    )
    all_entries = entries_res.scalars().all()

    domain_matches = []
    name_candidates = []

    vendor_names_to_compare = []
    if vendor.name:
        vendor_names_to_compare.append(vendor.name)
    if getattr(vendor, "normalized_name", None):
        vendor_names_to_compare.append(vendor.normalized_name)
    if getattr(vendor, "legal_name", None):
        vendor_names_to_compare.append(vendor.legal_name)
    if v_dom_label and len(v_dom_label) > 1:
        vendor_names_to_compare.append(v_dom_label)

    from app.services import sanctions

    for e in all_entries:
        rev_state = review_decisions.get(e.name, "none")
        if rev_state == "rejected":
            continue

        c_dom = clean_domain(e.domain)
        is_domain_match = False
        if v_dom and c_dom:
            if v_dom == c_dom or v_dom.endswith("." + c_dom) or c_dom.endswith("." + v_dom):
                is_domain_match = True

        rec_dict = {
            "name": e.name,
            "title": e.title,
            "domain": e.domain or "—",
            "breach_date": e.breach_date.isoformat() if e.breach_date else "—",
            "added_date": e.added_date.isoformat() if e.added_date else "—",
            "pwn_count": e.pwn_count,
            "data_classes": e.data_classes or [],
            "description": e.description or "",
            "link": f"https://haveibeenpwned.com/PwnedWebsites#{e.name}",
            "review_state": rev_state,
        }

        if is_domain_match or rev_state == "confirmed":
            domain_matches.append(rec_dict)
        else:
            # Check name candidate matching (Prompt 11 Section 1.2)
            # token_set_ratio >= breach_name_match_pct (85)
            e_name_norm = sanctions.normalise(e.title or e.name)
            is_cand = False
            for v_name in vendor_names_to_compare:
                v_name_norm = sanctions.normalise(v_name)
                if not v_name_norm:
                    continue
                score = fuzz.token_set_ratio(e_name_norm, v_name_norm)
                if score >= name_match_pct:
                    is_cand = True
                    break

            if is_cand:
                # Prompt 11: Short or common words make a candidate, never automatic match.
                name_candidates.append(rec_dict)

    # Compute 5-year count and 12-month recency over domain_matches
    five_yrs_ago = (now - timedelta(days=5 * 365)).date()
    one_yr_ago = (now - timedelta(days=365)).date()

    count_5y = 0
    latest_dt = None
    latest_within_12m = False

    for dm in domain_matches:
        b_dt_str = dm.get("breach_date")
        if b_dt_str and b_dt_str != "—":
            try:
                b_dt = datetime.strptime(b_dt_str[:10], "%Y-%m-%d").date()
                if b_dt >= five_yrs_ago:
                    count_5y += 1
                if latest_dt is None or b_dt > latest_dt:
                    latest_dt = b_dt
            except Exception:
                pass

    if latest_dt and latest_dt >= one_yr_ago:
        latest_within_12m = True

    # Review state determination
    overall_review_state = "none"
    if any(dm.get("review_state") == "confirmed" for dm in domain_matches):
        overall_review_state = "confirmed"
    elif name_candidates and not domain_matches:
        overall_review_state = "candidate_pending"

    # Check accepted remediation in vendor_evidence
    remediation_res = await db.execute(
        text("SELECT id FROM vendor_evidence WHERE vendor_id = :vid AND evidence_type = 'breach_remediation_report' AND status = 'accepted' LIMIT 1"),
        {"vid": vendor.id},
    )
    remediation_accepted = remediation_res.first() is not None

    cand_0 = name_candidates[0] if name_candidates else {}
    latest_match = domain_matches[0] if domain_matches else {}

    return {
        "catalogue_loaded": True,
        "not_assessed_reason": "",
        "records_domain_match": domain_matches,
        "records_name_candidate": name_candidates,
        "count_5y": count_5y,
        "latest_date": latest_dt.isoformat() if latest_dt else "—",
        "latest_within_12m": latest_within_12m,
        "latest_breach_name": latest_match.get("title") or latest_match.get("name") or "—",
        "candidate_record_name": cand_0.get("title") or cand_0.get("name") or "—",
        "candidate_record_date": cand_0.get("breach_date") or "—",
        "candidate_pwn_count": cand_0.get("pwn_count") or 0,
        "candidate_record_domain": cand_0.get("domain") or "—",
        "vendor_domain": vendor_domain or "—",
        "review_state": overall_review_state,
        "catalogue_version": meta.version_sha256[:10],
        "catalogue_fetched_at": meta.fetched_at.strftime("%d %b %Y"),
        "remediation_accepted": remediation_accepted,
    }


async def run_daily_breach_refresh(session_factory):
    """Background task to periodically refresh the breach catalogue (fallback when Temporal is not used)."""
    while True:
        try:
            async with session_factory() as session:
                meta = await get_latest_catalogue_meta(session)
                now = datetime.now(timezone.utc)
                should_refresh = False
                if meta is None:
                    should_refresh = True
                elif (now - meta.fetched_at).total_seconds() > 86400:
                    should_refresh = True

                if should_refresh:
                    logger.info("Refreshing Have I Been Pwned breach catalogue...")
                    try:
                        await download_and_store_catalogue(session)
                    except Exception as exc:
                        logger.warning("Failed to refresh breach catalogue: %s", exc)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in breach refresh background loop: %s", e)

        await asyncio.sleep(86400)
