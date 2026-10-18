"""Foreign-currency documents: converted to INR once, at processing time,
with the rate stored, so the value doesn't move with later rate changes."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services import document_service, fx, pipeline


class _FakeClient:
    """Stands in for httpx.AsyncClient; records the query it was sent."""
    calls = []

    def __init__(self, response=None, error=None, **_):
        self.response, self.error = response, error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, url, params=None):
        _FakeClient.calls.append(params)
        if self.error:
            raise self.error
        return self.response


def _client(body=None, error=None):
    response = httpx.Response(200, json=body, request=httpx.Request("GET", "https://fx.test")) if body else None
    return lambda **kw: _FakeClient(response=response, error=error, **kw)


@pytest.fixture(autouse=True)
def fresh_cache():
    fx._cache.clear()
    _FakeClient.calls = []


class TestConvert:
    @pytest.mark.asyncio
    async def test_inr_needs_no_lookup(self):
        with patch.object(fx.httpx, "AsyncClient", _client(error=AssertionError("no call expected"))):
            c = await fx.convert(1000.0, "INR")
        assert (c.amount_base, c.rate) == (1000.0, 1.0)

    @pytest.mark.asyncio
    async def test_usd_converted_with_dated_rate(self):
        body = {"base": "USD", "date": "2026-10-14", "rates": {"INR": 95.16}}
        with patch.object(fx.httpx, "AsyncClient", _client(body)):
            c = await fx.convert(1699.48, "usd")
        assert c.amount_base == round(1699.48 * 95.16, 2)
        assert c.rate_date == date(2026, 10, 14)
        assert _FakeClient.calls == [{"base": "USD", "symbols": "INR"}]

    @pytest.mark.asyncio
    async def test_unreachable_rate_service_is_retryable_not_guessed(self):
        with patch.object(fx.httpx, "AsyncClient", _client(error=httpx.ConnectError("down"))):
            with pytest.raises(fx.FxUnavailableError):
                await fx.convert(10.0, "USD")
        assert fx.FxUnavailableError in document_service.TRANSIENT_ERRORS


class TestMatchingUsesInr:
    @pytest.mark.asyncio
    async def test_ledger_gets_inr_total_and_line_prices(self):
        envelope = {
            "document_id": "d1", "document_type": "invoice", "vendor_id": "v1", "raw_text": "",
            "extracted_fields": {"total": 100.0, "currency": "USD",
                                 "line_items": [{"description": "x", "quantity": 2, "unit_price": 50.0}]},
            "fx": {"rate": 95.0, "total_inr": 9500.0},
        }
        sent = {}

        class Client:
            def __init__(self, **_): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False
            async def post(self, url, json=None, headers=None):
                sent.update(json)
                return httpx.Response(200, json={"data": {"status": "no_match", "issues": []}},
                                      request=httpx.Request("POST", url))

        with patch("httpx.AsyncClient", Client):
            await pipeline.invoice_matching_agent(AsyncMock(), None, envelope)
        assert sent["total"] == 9500.0
        assert sent["lines"][0]["unit_price"] == 4750.0


class TestReviewKeepsRate:
    @pytest.mark.asyncio
    async def test_corrected_total_reuses_the_stored_rate(self):
        doc = SimpleNamespace(total=200.0, currency="USD", fx_rate=90.0, total_inr=9000.0,
                              fx_rate_date=date(2026, 1, 1), fx_source="ECB")
        with patch.object(fx, "convert", AsyncMock(side_effect=AssertionError("no new rate expected"))):
            await document_service._reconvert(doc, "USD")
        assert doc.total_inr == 18000.0 and doc.fx_rate == 90.0

    @pytest.mark.asyncio
    async def test_corrected_currency_takes_a_new_rate(self):
        doc = SimpleNamespace(total=200.0, currency="EUR", fx_rate=90.0, total_inr=18000.0,
                              fx_rate_date=date(2026, 1, 1), fx_source="ECB")
        new = fx.Conversion(amount_base=21000.0, rate=105.0, rate_date=date(2026, 10, 14), source="ECB")
        with patch.object(fx, "convert", AsyncMock(return_value=new)):
            await document_service._reconvert(doc, "USD")
        assert (doc.total_inr, doc.fx_rate) == (21000.0, 105.0)
