"""Reputation group collectors: adverse_media (Prompt 9C Section F2).
Two-stage pipeline:
  Stage 1 (Retrieval): search news sources (Guardian API in live mode, sample fixture in demo mode).
  Stage 2 (Keyword/entity tagging): match retrieved snippets against versioned ruleset lookup adverse_media_lexicon.
Stores title, URL, date, source and snippet only (no full articles).
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Vendor
from app.services.collectors.base import record_observation, record_raw_response
from app.services.collectors.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

DEFAULT_LEXICON = {
    "version": "1.0",
    "categories": {
        "fraud": {
            "severity": "high",
            "keywords": ["fraud", "embezzle", "accounting irregularity", "ponzi", "forgery", "tax evasion"],
        },
        "bribery_corruption": {
            "severity": "high",
            "keywords": ["bribe", "bribery", "kickback", "corrupt", "foreign corrupt practices", "fcpa"],
        },
        "regulatory_action": {
            "severity": "medium",
            "keywords": ["enforcement action", "fine", "penalty", "sebi order", "investigation", "subpoena"],
        },
        "environmental": {
            "severity": "medium",
            "keywords": ["oil spill", "pollution", "environmental violation", "toxic waste", "carbon fraud"],
        },
        "modern_slavery": {
            "severity": "high",
            "keywords": ["forced labor", "child labor", "human trafficking", "modern slavery"],
        },
        "executive_misconduct": {
            "severity": "medium",
            "keywords": ["insider trading", "c-suite misconduct", "harassment", "ousted", "cfo fired"],
        },
    },
}


GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GUARDIAN_URL = "https://content.guardianapis.com/search"
GDELT_MIN_INTERVAL_S = 5.5  # GDELT asks for at most one request every 5 seconds
_gdelt_lock = asyncio.Lock()
_gdelt_last_call = 0.0


def _mentions_vendor(vendor_name_clean: str, text: str) -> bool:
    """Full normalised name, or its first word when that is distinctive
    (5+ letters, not a common word: "Hathway" yes, "Tech" or "Global" no)."""
    from app.services import sanctions
    from app.services.breach_catalogue import is_short_or_common
    if not vendor_name_clean:
        return False
    words = f" {sanctions.normalise(text)} "
    if f" {vendor_name_clean} " in words:
        return True
    brand = vendor_name_clean.split()[0]
    return not is_short_or_common(brand) and len(brand) >= 5 and f" {brand} " in words


async def _search_gdelt(client: httpx.AsyncClient, name: str, now: datetime) -> Optional[List[Dict[str, Any]]]:
    """Keyless news search (GDELT DOC 2.0, rolling ~3 months). None = not searched."""
    global _gdelt_last_call
    from app.services import sanctions
    term = sanctions.normalise(name)
    cb = CircuitBreaker("gdelt")
    if not term or not await cb.can_execute():
        return None
    async with _gdelt_lock:
        wait = GDELT_MIN_INTERVAL_S - (asyncio.get_running_loop().time() - _gdelt_last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            resp = await client.get(GDELT_URL, params={"query": f'"{term}" sourcelang:english', "mode": "artlist",
                                                       "format": "json", "maxrecords": 75, "sort": "datedesc"})
        except Exception as e:
            logger.warning(f"GDELT news search failed: {e}")
            resp = None
        finally:
            _gdelt_last_call = asyncio.get_running_loop().time()
    try:
        data = resp.json() if resp is not None and resp.status_code == 200 else None
    except ValueError:
        data = None  # GDELT answers a rate-limited call with plain text and HTTP 200
    if data is None:
        await cb.record_failure()
        return None
    await cb.record_success()
    articles = []
    for a in data.get("articles") or []:
        seen = a.get("seendate") or ""
        articles.append({"title": a.get("title", ""), "url": a.get("url", ""), "snippet": "",
                         "date": f"{seen[:4]}-{seen[4:6]}-{seen[6:8]}" if len(seen) >= 8 else now.date().isoformat(),
                         "source": a.get("domain") or "GDELT"})
    return articles


async def _search_guardian(client: httpx.AsyncClient, name: str, now: datetime) -> Optional[List[Dict[str, Any]]]:
    """The Guardian Open Platform (24 months of archive); needs GUARDIAN_API_KEY. None = not searched."""
    key = os.getenv("GUARDIAN_API_KEY", "").strip()
    cb = CircuitBreaker("guardian")
    if not key or not await cb.can_execute():
        return None  # keyless calls get HTTP 401
    try:
        resp = await client.get(GUARDIAN_URL, params={"q": name, "show-fields": "headline,trailText", "api-key": key})
    except Exception as e:
        logger.warning(f"Guardian news search failed: {e}")
        resp = None
    if resp is None or resp.status_code != 200:
        # 401 bad key, 429 quota, 5xx: nothing was searched
        await cb.record_failure()
        return None
    await cb.record_success()
    return [{"title": (r.get("fields") or {}).get("headline", r.get("webTitle", "")), "url": r.get("webUrl", ""),
             "date": r.get("webPublicationDate", now.isoformat())[:10], "source": "The Guardian",
             "snippet": (r.get("fields") or {}).get("trailText", "")}
            for r in (resp.json().get("response") or {}).get("results", [])]


async def collect_adverse_media(
    db: AsyncSession,
    vendor: Vendor,
    now: datetime,
    lexicon: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, Any]:
    """Collects adverse media mentions via two-stage extraction (Prompt 9C Section F2)."""
    provider = "GDELT / The Guardian"
    lexicon = lexicon or DEFAULT_LEXICON
    lexicon_version = lexicon.get("version", "1.0")
    categories_cfg = lexicon.get("categories", {})

    # Check for excluded articles in audit log
    cleared_query = text("""
        SELECT payload->>'article_url' AS url
        FROM audit_log
        WHERE entity_type = 'vendor_adverse_media'
          AND (payload->>'vendor_id') = :vid
          AND action IN ('article_cleared_not_vendor', 'article_resolved')
    """)
    cleared_rows = (await db.execute(cleared_query, {"vid": vendor.id})).all()
    cleared_urls = {r.url for r in cleared_rows if r.url}

    from shared.live_mode.checker import is_live_verification_enabled
    live_enabled = await is_live_verification_enabled(db)

    retrieved_articles: List[Dict[str, Any]] = []
    searched: List[str] = []
    if live_enabled:
        async with httpx.AsyncClient(timeout=10.0) as client:  # 10s per-source cap (Section E1)
            for source, search in (("GDELT", _search_gdelt), ("The Guardian", _search_guardian)):
                found = await search(client, vendor.name or "", now)
                if found is not None:
                    searched.append(source)
                    retrieved_articles.extend(found)
    # Only a source that answered counts as searched; a refused or skipped
    # source is never reported as "no adverse media found".
    sources_reachable = bool(searched)

    retrieved_count = len(retrieved_articles)
    discarded_not_vendor = 0
    discarded_too_old = 0
    matched_keywords: List[str] = []
    matching_headlines: List[Dict[str, Any]] = []
    matched_categories_set = set()
    high_severity_count = 0

    from app.services import sanctions
    vendor_name_clean = sanctions.normalise(vendor.name or "")
    two_years_ago = (now - timedelta(days=730)).date()

    for art in retrieved_articles:
        url = art.get("url", "")
        if url in cleared_urls:
            continue

        title = (art.get("title") or "").lower()
        snippet = (art.get("snippet") or "").lower()
        combined_text = f"{title} {snippet}"

        # (a) vendor name, or its distinctive brand word, appears in title or snippet
        if not _mentions_vendor(vendor_name_clean, combined_text):
            discarded_not_vendor += 1
            continue

        # (c) article date within 24 months
        art_date_str = art.get("date", "")[:10]
        try:
            art_date = datetime.strptime(art_date_str, "%Y-%m-%d").date()
            if art_date < two_years_ago:
                discarded_too_old += 1
                continue
        except Exception:
            pass

        # (b) at least one category keyword appears
        art_categories = []
        art_severity = "medium"
        for cat_name, cat_data in categories_cfg.items():
            kws = cat_data.get("keywords") or cat_data.get("phrases") or []  # built-in / ruleset lexicon
            cat_sev = cat_data.get("severity", "medium")
            for kw in kws:
                if kw.lower() in combined_text:
                    art_categories.append(cat_name)
                    matched_categories_set.add(cat_name)
                    if kw.lower() not in matched_keywords:
                        matched_keywords.append(kw.lower())
                    if cat_sev == "high":
                        art_severity = "high"
                    break

        if art_categories:
            if art_severity == "high":
                high_severity_count += 1
            matching_headlines.append({
                "title": art.get("title"),
                "url": url,
                "date": art_date_str,
                "categories": art_categories,
                "severity": art_severity,
                "source": art.get("source", "The Guardian"),
            })

    qualifying_articles = len(matching_headlines)
    distinct_categories = sorted(list(matched_categories_set))

    fields = {
        "media.sources_reachable": sources_reachable,
        "media.qualifying_articles": qualifying_articles,
        "media.high_severity_count": high_severity_count,
        "media.categories": distinct_categories,
        "media.headlines": matching_headlines,
        "media.not_checked_reason": "Live verification mode is off" if not live_enabled else ("Sources unreachable" if not sources_reachable else ""),
    }

    extraction = {
        "lexicon_version": lexicon_version,
        "matched_keywords": matched_keywords,
        "retrieved_count": retrieved_count,
        "discarded_not_vendor": discarded_not_vendor,
        "discarded_too_old": discarded_too_old,
    }

    raw = await record_raw_response(
        db=db,
        vendor_id=vendor.id,
        signal_key="adverse_media",
        provider=provider,
        request_method="GET",
        request_url=f"{GDELT_URL}?query={vendor.name}",
        body={"headlines": matching_headlines, "extraction": extraction, "cleared_urls": list(cleared_urls)},
        source_id="news_search",
        response_status=200 if sources_reachable else 503,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200" if sources_reachable else "503"},
        {"label": "Sources reachable", "value": "Yes" if sources_reachable else "No"},
        {"label": "Sources searched", "value": ", ".join(searched) or "None"},
        {"label": "Qualifying articles", "value": str(qualifying_articles)},
        {"label": "High severity count", "value": str(high_severity_count)},
    ]

    obs_status = "ok" if (sources_reachable and live_enabled) else ("not_checked" if not live_enabled else "error")
    obs = await record_observation(
        db=db,
        vendor_id=vendor.id,
        signal_key="adverse_media",
        source_name="Adverse Media Screening",
        provider=provider,
        status=obs_status,
        facts=facts,
        fields=fields,
        raw_response_id=raw.id,
        ttl_days=3,
        fetched_at=now,
        extraction=extraction,
    )
    return obs, raw
