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


async def collect_adverse_media(
    db: AsyncSession,
    vendor: Vendor,
    now: datetime,
    lexicon: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, Any]:
    """Collects adverse media mentions via two-stage extraction (Prompt 9C Section F2)."""
    provider = "The Guardian / Open Media Feed"
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

    sources_reachable = True if live_enabled else False
    cb = CircuitBreaker("guardian")

    retrieved_articles: List[Dict[str, Any]] = []

    guardian_key = os.getenv("GUARDIAN_API_KEY", "").strip()
    if live_enabled:
        if not guardian_key:
            # The Guardian refuses keyless calls (HTTP 401); without a key nothing is searched.
            sources_reachable = False
        elif not await cb.can_execute():
            sources_reachable = False
        else:
            try:
                # 10s per-source timeout cap (Section E1)
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://content.guardianapis.com/search",
                        params={"q": vendor.name, "show-fields": "headline,trailText", "api-key": guardian_key},
                    )
                    if resp.status_code == 200:
                        data = resp.json().get("response", {})
                        for r in data.get("results", []):
                            fields_data = r.get("fields", {})
                            retrieved_articles.append({
                                "title": fields_data.get("headline", r.get("webTitle", "")),
                                "url": r.get("webUrl", ""),
                                "date": r.get("webPublicationDate", now.isoformat())[:10],
                                "source": "The Guardian",
                                "snippet": fields_data.get("trailText", ""),
                            })
                        await cb.record_success()
                    else:
                        # Any refusal (401 bad key, 429 quota, 5xx) means nothing was searched:
                        # never report that as "no adverse media found".
                        await cb.record_failure()
                        sources_reachable = False
            except Exception as e:
                logger.warning(f"Live adverse media lookup failed: {e}")
                await cb.record_failure()
                sources_reachable = False

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

        # (a) vendor name appears in title or snippet
        if vendor_name_clean and vendor_name_clean not in combined_text:
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
            kws = cat_data.get("keywords", [])
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
        request_url=f"https://content.guardianapis.com/search?q={vendor.name}",
        body={"headlines": matching_headlines, "extraction": extraction, "cleared_urls": list(cleared_urls)},
        source_id="guardian_api",
        response_status=200 if sources_reachable else 503,
        fetched_at=now,
    )

    facts = [
        {"label": "Source", "value": provider},
        {"label": "Retrieved", "value": now.strftime("%Y-%m-%d %H:%M:%S UTC")},
        {"label": "HTTP status", "value": "200" if sources_reachable else "503"},
        {"label": "Sources reachable", "value": "Yes" if sources_reachable else "No"},
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
