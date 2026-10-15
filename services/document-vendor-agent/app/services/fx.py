"""Converts a document's amount to the base currency (INR).

The rate is fetched once, when the document is processed, and stored on
the document with its date (documents.fx_rate / fx_rate_date / total_inr),
so the INR value of a USD invoice never changes afterwards. Rates are the
ECB daily reference rates via Frankfurter (no API key). If the rate can't
be fetched the document is retried later, never matched on a guessed rate.
"""
import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# One lookup per currency per hour is plenty for daily reference rates.
_CACHE_SECONDS = 3600
_cache: dict[str, tuple[float, "Rate"]] = {}


class FxUnavailableError(Exception):
    """The exchange rate couldn't be fetched; retry the document later."""


@dataclass
class Rate:
    rate: float          # 1 unit of `currency` in the base currency
    rate_date: date
    source: str


@dataclass
class Conversion:
    amount_base: Optional[float]
    rate: float
    rate_date: Optional[date]
    source: str


async def get_rate(currency: str) -> Rate:
    currency = currency.upper()
    base = settings.base_currency.upper()
    if currency == base:
        return Rate(1.0, date.today(), "same currency")
    cached = _cache.get(currency)
    if cached and time.monotonic() - cached[0] < _CACHE_SECONDS:
        return cached[1]
    url = f"{settings.fx_api_url.rstrip('/')}/latest"
    try:
        async with httpx.AsyncClient(timeout=settings.fx_timeout_seconds, follow_redirects=True) as client:
            resp = await client.get(url, params={"base": currency, "symbols": base})
        resp.raise_for_status()
        body = resp.json()
        rate = Rate(float(body["rates"][base]), date.fromisoformat(body["date"]), "ECB via frankfurter.dev")
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise FxUnavailableError(f"no {currency}->{base} exchange rate: {e}") from e
    _cache[currency] = (time.monotonic(), rate)
    return rate


async def convert(amount: Optional[float], currency: Optional[str]) -> Conversion:
    rate = await get_rate(currency or settings.base_currency)
    amount_base = round(amount * rate.rate, 2) if amount is not None else None
    return Conversion(amount_base, rate.rate, rate.rate_date, rate.source)
