"""Unit and integration tests for World Bank Worldwide Governance Indicators (WGI) service
and jurisdiction risk collector.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Vendor
from app.services.collectors.identity_collectors import collect_jurisdiction
from app.services.scorecard.engine import evaluate_risk
from app.services.scorecard.ruleset_v2 import RULESET_V2_DEFINITION
from app.services.world_bank import (
    clear_wgi_cache,
    fetch_wgi_indicators,
    WGIResult,
)


@pytest.fixture(autouse=True)
def reset_cache():
    clear_wgi_cache()
    yield
    clear_wgi_cache()


@pytest.mark.asyncio
async def test_fetch_wgi_indicators_invalid_code():
    """Invalid country codes (e.g. empty, numbers, length != 2) should return status='no_data' without querying."""
    res = await fetch_wgi_indicators("XYZ")
    assert res.status == "no_data"
    assert res.country_code == "XYZ"
    assert res.pv is None
    assert res.rl is None
    assert res.wgi_composite is None

    empty_res = await fetch_wgi_indicators("")
    assert empty_res.status == "no_data"
    assert empty_res.country_code == "UNKNOWN"


@pytest.mark.asyncio
async def test_fetch_wgi_indicators_cache_hit():
    """A subsequent request for the same country code should retrieve from cache without HTTP client calls."""
    mock_pv_payload = [
        {"page": 1, "pages": 1, "total": 1},
        [{"value": -0.3021, "date": "2025", "country": {"value": "United States"}}],
    ]
    mock_rl_payload = [
        {"page": 1, "pages": 1, "total": 1},
        [{"value": 0.7914, "date": "2025", "country": {"value": "United States"}}],
    ]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    resp_pv = MagicMock()
    resp_pv.status_code = 200
    resp_pv.json.return_value = mock_pv_payload

    resp_rl = MagicMock()
    resp_rl.status_code = 200
    resp_rl.json.return_value = mock_rl_payload

    mock_client.get.side_effect = [resp_pv, resp_rl]

    # First fetch (cache miss)
    res1 = await fetch_wgi_indicators("US", client=mock_client)
    assert res1.status == "ok"
    assert res1.country_code == "US"
    assert res1.pv == -0.3021
    assert res1.rl == 0.7914
    assert res1.wgi_composite == round((-0.3021 + 0.7914) / 2.0, 4)
    assert res1.wgi_year == 2025
    assert mock_client.get.call_count == 2

    # Second fetch (cache hit)
    res2 = await fetch_wgi_indicators("US", client=mock_client)
    assert res2.status == "ok"
    assert res2.wgi_composite == res1.wgi_composite
    # No extra calls were made
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_fetch_wgi_indicators_handles_timeout_gracefully():
    """Network timeouts or exceptions should return status='no_data' without raising unhandled exceptions."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = httpx.TimeoutException("World Bank API timeout")

    res = await fetch_wgi_indicators("GB", client=mock_client)
    assert res.status == "no_data"
    assert res.wgi_composite is None


@pytest.mark.asyncio
async def test_collect_jurisdiction_domestic_vendor():
    """Domestic vendor (IN) should use statutory domestic baseline and trigger R-JUR-06 (0 pts)."""
    now = datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc)
    vendor = Vendor(
        id="v-dom-001",
        name="Tata Consultancy",
        country="IN",
        status="active",
    )

    db = AsyncMock(spec=AsyncSession)
    v_row = SimpleNamespace(
        id=vendor.id,
        country="IN",
        swift_bic=None,
    )
    res_mock = MagicMock()
    res_mock.first.return_value = v_row
    db.execute.return_value = res_mock

    with patch("app.services.world_bank.fetch_wgi_indicators") as mock_wb:
        obs, raw = await collect_jurisdiction(db, vendor, now)
        # Domestic vendor should not make external World Bank API call
        mock_wb.assert_not_called()

    assert obs.fields["country.code"] == "IN"
    assert obs.fields["country.is_domestic"] is True
    assert obs.fields["country.prohibited"] is False
    assert obs.fields["country.wgi_composite"] == 0.85
    assert obs.fields["na_reason_code"] == "domestic_vendor"

    # Evaluate against ruleset_v2
    eval_res = evaluate_risk(
        ruleset=RULESET_V2_DEFINITION,
        observations={"jurisdiction": obs},
        assessed_at=now,
    )
    rule_ids = [r["rule_id"] for r in eval_res["rule_results"]]
    assert "R-JUR-06" in rule_ids
    assert "R-JUR-03" not in rule_ids
    assert "R-JUR-04" not in rule_ids


@pytest.mark.asyncio
async def test_collect_jurisdiction_foreign_stable_governance():
    """Foreign vendor with positive WGI (e.g. Germany) triggers R-JUR-05 (0 pts)."""
    now = datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc)
    vendor = Vendor(
        id="v-de-001",
        name="Siemens AG",
        country="DE",
        status="active",
    )

    db = AsyncMock(spec=AsyncSession)
    v_row = SimpleNamespace(
        id=vendor.id,
        country="DE",
        swift_bic=None,
    )
    res_mock = MagicMock()
    res_mock.first.return_value = v_row
    db.execute.return_value = res_mock

    mock_wgi = WGIResult(
        country_code="DE",
        country_name="Germany",
        pv=0.2083,
        rl=1.6043,
        wgi_composite=0.9063,
        wgi_year=2025,
        status="ok",
        raw_response={"status": "mocked"},
    )

    with patch("app.services.world_bank.fetch_wgi_indicators", AsyncMock(return_value=mock_wgi)):
        obs, raw = await collect_jurisdiction(db, vendor, now)

    assert obs.fields["country.code"] == "DE"
    assert obs.fields["country.is_domestic"] is False
    assert obs.fields["country.wgi_composite"] == 0.9063
    assert obs.fields["country.pv"] == 0.2083
    assert obs.fields["country.rl"] == 1.6043
    assert obs.fields["country.status"] == "ok"

    eval_res = evaluate_risk(
        ruleset=RULESET_V2_DEFINITION,
        observations={"jurisdiction": obs},
        assessed_at=now,
    )
    rule_ids = [r["rule_id"] for r in eval_res["rule_results"]]
    assert "R-JUR-05" in rule_ids
    assert "R-JUR-03" not in rule_ids
    assert "R-JUR-04" not in rule_ids


@pytest.mark.asyncio
async def test_collect_jurisdiction_foreign_below_average_governance():
    """Foreign vendor with below-average WGI (-1.0 <= composite < 0.0) triggers R-JUR-04 (1 pt)."""
    now = datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc)
    vendor = Vendor(
        id="v-br-001",
        name="Empresa Brasileira SA",
        country="BR",
        status="active",
    )

    db = AsyncMock(spec=AsyncSession)
    v_row = SimpleNamespace(
        id=vendor.id,
        country="BR",
        swift_bic=None,
    )
    res_mock = MagicMock()
    res_mock.first.return_value = v_row
    db.execute.return_value = res_mock

    mock_wgi = WGIResult(
        country_code="BR",
        country_name="Brazil",
        pv=-0.38,
        rl=-0.49,
        wgi_composite=-0.435,
        wgi_year=2025,
        status="ok",
        raw_response={"status": "mocked"},
    )

    with patch("app.services.world_bank.fetch_wgi_indicators", AsyncMock(return_value=mock_wgi)):
        obs, raw = await collect_jurisdiction(db, vendor, now)

    assert obs.fields["country.wgi_composite"] == -0.435
    eval_res = evaluate_risk(
        ruleset=RULESET_V2_DEFINITION,
        observations={"jurisdiction": obs},
        assessed_at=now,
    )
    rule_ids = [r["rule_id"] for r in eval_res["rule_results"]]
    assert "R-JUR-04" in rule_ids
    assert "R-JUR-03" not in rule_ids
    assert "R-JUR-05" not in rule_ids


@pytest.mark.asyncio
async def test_collect_jurisdiction_foreign_low_governance():
    """Foreign vendor with composite < -1.0 triggers R-JUR-03 (2 pts)."""
    now = datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc)
    vendor = Vendor(
        id="v-ru-001",
        name="Volga Logistics",
        country="RU",
        status="active",
    )

    db = AsyncMock(spec=AsyncSession)
    v_row = SimpleNamespace(
        id=vendor.id,
        country="RU",
        swift_bic=None,
    )
    res_mock = MagicMock()
    res_mock.first.return_value = v_row
    db.execute.return_value = res_mock

    mock_wgi = WGIResult(
        country_code="RU",
        country_name="Russian Federation",
        pv=-0.945,
        rl=-1.272,
        wgi_composite=-1.1085,
        wgi_year=2025,
        status="ok",
        raw_response={"status": "mocked"},
    )

    with patch("app.services.world_bank.fetch_wgi_indicators", AsyncMock(return_value=mock_wgi)):
        obs, raw = await collect_jurisdiction(db, vendor, now)

    assert obs.fields["country.wgi_composite"] == -1.1085
    eval_res = evaluate_risk(
        ruleset=RULESET_V2_DEFINITION,
        observations={"jurisdiction": obs},
        assessed_at=now,
    )
    rule_ids = [r["rule_id"] for r in eval_res["rule_results"]]
    assert "R-JUR-03" in rule_ids
    assert "R-JUR-04" not in rule_ids
    assert "R-JUR-05" not in rule_ids


@pytest.mark.asyncio
async def test_collect_jurisdiction_unranked_territory():
    """When World Bank data is unavailable, R-JUR-07 triggers as not_assessed."""
    now = datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc)
    vendor = Vendor(
        id="v-unknown-001",
        name="Pacific Isle Trading",
        country="ZZ",
        status="active",
    )

    db = AsyncMock(spec=AsyncSession)
    v_row = SimpleNamespace(
        id=vendor.id,
        country="ZZ",
        swift_bic=None,
    )
    res_mock = MagicMock()
    res_mock.first.return_value = v_row
    db.execute.return_value = res_mock

    mock_wgi = WGIResult(
        country_code="ZZ",
        country_name=None,
        pv=None,
        rl=None,
        wgi_composite=None,
        wgi_year=None,
        status="no_data",
        raw_response={},
    )

    with patch("app.services.world_bank.fetch_wgi_indicators", AsyncMock(return_value=mock_wgi)):
        obs, raw = await collect_jurisdiction(db, vendor, now)

    assert obs.fields["country.status"] == "wgi_unavailable"
    assert obs.fields["country.wgi_composite"] is None

    eval_res = evaluate_risk(
        ruleset=RULESET_V2_DEFINITION,
        observations={"jurisdiction": obs},
        assessed_at=now,
    )
    rule_ids = [r["rule_id"] for r in eval_res["rule_results"]]
    assert "R-JUR-07" in rule_ids
