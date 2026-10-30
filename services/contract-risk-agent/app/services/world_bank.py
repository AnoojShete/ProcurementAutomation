"""World Bank Open Data Indicators API service for Worldwide Governance Indicators (WGI).

Fetches Political Stability (PV.EST) and Rule of Law (RL.EST) to evaluate country governance risk.
Specifications:
- Public, free, NO API key required.
- Endpoint pattern: https://api.worldbank.org/v2/country/{country_iso2}/indicator/{indicator_code}?format=json&mrnev=1
- Active WGI indicator identifiers:
  * GOV_WGI_PV.EST (Political Stability and Absence of Violence/Terrorism)
  * GOV_WGI_RL.EST (Rule of Law)
  with fallback to legacy codes PV.EST and RL.EST.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional, Tuple
import httpx

logger = logging.getLogger(__name__)

WORLD_BANK_BASE_URL = "https://api.worldbank.org/v2"

INDICATOR_CANDIDATES = {
    "pv": ["GOV_WGI_PV.EST", "PV.EST"],
    "rl": ["GOV_WGI_RL.EST", "RL.EST"],
}

CACHE_TTL_SECONDS = 86400  # 24 hours


@dataclass
class WGIResult:
    country_code: str
    country_name: Optional[str]
    pv: Optional[float]
    rl: Optional[float]
    wgi_composite: Optional[float]
    wgi_year: Optional[int]
    status: str  # "ok", "no_data", "error"
    raw_response: Dict[str, Any]


_wgi_cache: Dict[str, Tuple[datetime, WGIResult]] = {}


def clear_wgi_cache() -> None:
    """Clears the in-memory WGI indicator cache (useful for testing)."""
    _wgi_cache.clear()


async def _fetch_single_indicator(
    client: httpx.AsyncClient,
    country_iso2: str,
    indicator_codes: List[str],
) -> Tuple[Optional[float], Optional[int], Optional[str], Optional[Dict[str, Any]]]:
    """Tries indicator code candidates sequentially for the given country.

    Returns: (value, year, country_name, raw_data_dict)
    """
    for code in indicator_codes:
        url = f"{WORLD_BANK_BASE_URL}/country/{country_iso2}/indicator/{code}"
        params = {"format": "json", "mrnev": "1"}
        try:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(
                    "World Bank API non-200 (%s) for country=%s indicator=%s",
                    resp.status_code,
                    country_iso2,
                    code,
                )
                continue

            data = resp.json()
            # Valid response is a list with at least 2 items: metadata dict, and data list
            if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list) and len(data[1]) > 0:
                item = data[1][0]
                raw_val = item.get("value")
                if raw_val is not None:
                    try:
                        val = float(raw_val)
                    except (ValueError, TypeError):
                        val = None

                    raw_date = item.get("date")
                    year = int(raw_date) if raw_date and str(raw_date).isdigit() else None
                    c_name = item.get("country", {}).get("value")
                    return val, year, c_name, item

            # If response is error metadata (e.g. invalid indicator code), try next candidate
        except (httpx.HTTPError, asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                "Error fetching World Bank indicator %s for %s: %s",
                code,
                country_iso2,
                exc,
            )
            continue

    return None, None, None, None


async def fetch_wgi_indicators(
    country_iso2: str,
    client: Optional[httpx.AsyncClient] = None,
    bypass_cache: bool = False,
) -> WGIResult:
    """Fetches Worldwide Governance Indicators (PV and RL) for a country ISO2 code.

    Returns a WGIResult with Political Stability (pv), Rule of Law (rl),
    composite score ((pv + rl) / 2), indicator year, and audit raw responses.
    """
    clean_country = (country_iso2 or "").strip().upper()
    if len(clean_country) != 2 or not clean_country.isalpha():
        return WGIResult(
            country_code=clean_country or "UNKNOWN",
            country_name=None,
            pv=None,
            rl=None,
            wgi_composite=None,
            wgi_year=None,
            status="no_data",
            raw_response={},
        )

    now = datetime.now(timezone.utc)

    # Check in-memory cache
    if not bypass_cache and clean_country in _wgi_cache:
        cached_time, cached_res = _wgi_cache[clean_country]
        if (now - cached_time).total_seconds() < CACHE_TTL_SECONDS:
            return cached_res

    should_close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=5.0)
        should_close_client = True

    try:
        pv_task = _fetch_single_indicator(client, clean_country, INDICATOR_CANDIDATES["pv"])
        rl_task = _fetch_single_indicator(client, clean_country, INDICATOR_CANDIDATES["rl"])
        (pv, pv_year, pv_cname, pv_raw), (rl, rl_year, rl_cname, rl_raw) = await asyncio.gather(
            pv_task, rl_task, return_exceptions=False
        )

        country_name = pv_cname or rl_cname

        # Calculate composite score
        if pv is not None and rl is not None:
            wgi_composite = round((pv + rl) / 2.0, 4)
        elif pv is not None:
            wgi_composite = round(pv, 4)
        elif rl is not None:
            wgi_composite = round(rl, 4)
        else:
            wgi_composite = None

        years = [y for y in (pv_year, rl_year) if y is not None]
        wgi_year = max(years) if years else None

        raw_combined = {
            "pv_indicator": pv_raw,
            "rl_indicator": rl_raw,
        }

        status = "ok" if wgi_composite is not None else "no_data"

        result = WGIResult(
            country_code=clean_country,
            country_name=country_name,
            pv=round(pv, 4) if pv is not None else None,
            rl=round(rl, 4) if rl is not None else None,
            wgi_composite=wgi_composite,
            wgi_year=wgi_year,
            status=status,
            raw_response=raw_combined,
        )

        _wgi_cache[clean_country] = (now, result)
        return result

    except Exception as exc:
        logger.error("Failed to retrieve WGI indicators for %s: %s", clean_country, exc)
        return WGIResult(
            country_code=clean_country,
            country_name=None,
            pv=None,
            rl=None,
            wgi_composite=None,
            wgi_year=None,
            status="error",
            raw_response={"error": str(exc)},
        )
    finally:
        if should_close_client:
            await client.aclose()
