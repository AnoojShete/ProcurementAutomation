"""Comprehensive automated verification tests for the 5 live-testing hotfixes:
1. Vendor onboarding starts in 'onboarding' status; trigger rejects premature active INSERT.
2. Phase 0 non-remediable override short-circuits Phase 1 & 2 (zero external HTTP calls).
3. Concurrency & collector import verification (independent DB sessions, no missing imports).
4. Real DNS/TLS probes with demo-safe mode.
5. Inherent tier live configuration and effective tier computation (max of inherent and spend).
6. SWIFT/BIC foreign bank validation (ISO 9362) and Bank Melli Iran / prohibited country screening.
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Vendor
from app.services.collectors.collector_manager import collect_all_signals
from app.services.collectors.cyber_collectors import (
    collect_email,
    collect_web,
    derive_vendor_domain,
)
from app.services.collectors.identity_collectors import (
    collect_bank,
    collect_jurisdiction,
    collect_sanctions,
)
from app.services.scorecard.default_ruleset import get_default_ruleset
from app.services.scorecard.engine import calculate_effective_tier, evaluate_risk


# ---------------------------------------------------------------------------
# Fix 1 & 5: Onboarding status & Phase 0 Short-Circuit on Sanctions/Prohibited
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_caspian_onboarding_short_circuits_phase_0():
    """Caspian Petrochem (country='IR', Bank Melli) starts with status='onboarding',
    detects non-remediable override in Phase 0, and short-circuits Phase 1 & 2
    with zero live external calls and skip_reason='skipped_nonremediable_override'.
    """
    now = datetime.now(timezone.utc)
    vendor = Vendor(
        id="c0000000-0000-0000-0000-000000000001",
        name="Caspian Petrochemical Co",
        status="onboarding",
        country="IR",
        bank_name="Bank Melli Iran",
        swift_bic="MELIIRTHXXX",
    )

    db = AsyncMock(spec=AsyncSession)
    v_row = SimpleNamespace(
        id=vendor.id,
        name=vendor.name,
        country="IR",
        bank_name="Bank Melli Iran",
        swift_bic="MELIIRTHXXX",
        routing_code=None,
        bank_account_number="1234567890",
        ifsc_verification_status=None,
        gstin_cached_response={},
        created_at=now,
    )
    res_mock = MagicMock()
    res_mock.first.return_value = v_row
    db.execute.return_value = res_mock

    # Run collectors
    obs = await collect_all_signals(db, vendor, now=now)

    # Sanctions and Jurisdiction ran in Phase 0
    assert obs["sanctions"].fields.get("sanctions.status") == "match"
    assert obs["jurisdiction"].fields.get("country.prohibited") is True

    # Phase 1 & 2 signals MUST be short-circuited with skipped_nonremediable_override
    for sig in ["gst", "web", "email", "breach", "certification", "financial", "adverse_media"]:
        assert sig in obs
        assert obs[sig].skip_reason == "skipped_nonremediable_override"
        assert obs[sig].status == "not_checked"


@pytest.mark.asyncio
async def test_swift_bic_sanctioned_bank_triggers_jurisdiction_override():
    """Even if vendor claims country='AE' (UAE), providing Bank Melli SWIFT (MELIIRTHXXX)
    extracts country 'IR' and triggers both sanctions and prohibited jurisdiction in Phase 0.
    """
    now = datetime.now(timezone.utc)
    vendor = Vendor(
        id="c0000000-0000-0000-0000-000000000002",
        name="Gulf Maritime Traders",
        status="onboarding",
        country="AE",
        bank_name="Bank Melli Iran Dubai Branch",
        swift_bic="MELIIRTHXXX",
    )

    db = AsyncMock(spec=AsyncSession)
    v_row = SimpleNamespace(
        id=vendor.id,
        name=vendor.name,
        country="AE",
        bank_name="Bank Melli Iran Dubai Branch",
        swift_bic="MELIIRTHXXX",
        routing_code=None,
        bank_account_number="1234567890",
        ifsc_verification_status=None,
        gstin_cached_response={},
        created_at=now,
    )
    res_mock = MagicMock()
    res_mock.first.return_value = v_row
    db.execute.return_value = res_mock

    # Jurisdiction collector extracts chars 5-6 -> 'IR' -> prohibited
    j_obs, _ = await collect_jurisdiction(db, vendor, now)
    assert j_obs.fields["country.prohibited"] is True
    assert j_obs.fields["country.code"] == "IR"

    # Sanctions collector detects MELIIR prefix -> match
    s_obs, _ = await collect_sanctions(db, vendor, now)
    assert s_obs.fields["sanctions.status"] == "match"


# ---------------------------------------------------------------------------
# Fix 2: Collector Import & Session Concurrency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_every_collector_entrypoint_imports_and_executes():
    """Verifies that all collectors can be imported and executed without missing import errors."""
    from app.services.collectors.identity_collectors import collect_gst, collect_sanctions, collect_bank, collect_jurisdiction
    from app.services.collectors.cyber_collectors import collect_web, collect_email, collect_breach, collect_certification
    from app.services.collectors.reputation_collectors import collect_adverse_media
    from app.services.collectors.company_collectors import collect_company_age, collect_financial
    from app.services.collectors.performance_collectors import collect_delivery_sla, collect_feedback, collect_incidents

    collectors = [
        ("sanctions", collect_sanctions),
        ("bank", collect_bank),
        ("jurisdiction", collect_jurisdiction),
        ("gst", collect_gst),
        ("web", collect_web),
        ("email", collect_email),
        ("breach", collect_breach),
        ("certification", collect_certification),
        ("adverse_media", collect_adverse_media),
        ("company_age", collect_company_age),
        ("financial", collect_financial),
        ("delivery_sla", collect_delivery_sla),
        ("feedback", collect_feedback),
        ("incidents", collect_incidents),
    ]

    now = datetime.now(timezone.utc)
    vendor = Vendor(
        id="t0000000-0000-0000-0000-000000000001",
        name="Test Vendor Systems",
        status="active",
        country="IN",
        website="testvendor.example",
    )

    db = AsyncMock(spec=AsyncSession)
    res_mock = MagicMock()
    res_mock.first.return_value = None
    res_mock.scalar.return_value = 0
    res_mock.scalars.return_value.all.return_value = []
    res_mock.scalars.return_value.first.return_value = None
    db.execute.return_value = res_mock

    for name, fn in collectors:
        if name == "certification":
            obs, raw = await fn(db, vendor, now, effective_tier="moderate")
        else:
            obs, raw = await fn(db, vendor, now)
        assert obs is not None
        assert raw is not None


# ---------------------------------------------------------------------------
# Fix 3: Real Cyber Probes & Demo-Safe Mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_website_domain_derivation_prioritizes_website():
    """Website field is prioritized over email and normalized name."""
    v1 = Vendor(name="Acme Corp", contact_email="admin@gmail.com", website="https://acmecorp.com/portal?ref=1")
    assert derive_vendor_domain(v1) == "acmecorp.com"

    v2 = Vendor(name="Acme Corp", contact_email="admin@acmepartner.com", website=None)
    assert derive_vendor_domain(v2) == "acmepartner.com"

    v3 = Vendor(name="Beta Solutions", contact_email=None, website=None)
    assert derive_vendor_domain(v3) == "betasolutions.com"


@pytest.mark.asyncio
async def test_real_domain_tls_and_dns_probe():
    """Probing a real corporate domain parses valid TLS version and SPF/DMARC records."""
    now = datetime.now(timezone.utc)
    vendor = Vendor(
        id="t0000000-0000-0000-0000-000000000002",
        name="Cloudflare Vendor",
        status="active",
        country="US",
        website="cloudflare.com",
    )

    db = AsyncMock(spec=AsyncSession)
    res_mock = MagicMock()
    res_mock.scalar.return_value = True
    db.execute.return_value = res_mock

    # Web probe
    web_obs, _ = await collect_web(db, vendor, now)
    assert web_obs.fields["web.reachable"] is True
    # Prompt 11: a grade only ever comes from a real SSL Labs result; the probe fills TLS facts.
    assert web_obs.fields["web.ssl_grade"] is None
    assert web_obs.fields["web.cert_valid"] is True
    assert web_obs.fields["web.cert_days_left"] > 0

    # Email probe
    email_obs, _ = await collect_email(db, vendor, now)
    assert email_obs.fields["email.has_mx"] is True
    assert email_obs.fields["email.spf_present"] is True
    assert email_obs.fields["email.dmarc_policy"] in ("reject", "quarantine", "none")


@pytest.mark.asyncio
async def test_demo_safe_mode_on_synthetic_domains():
    """Synthetic demo domains (.local, .test) use safe deterministic observations."""
    now = datetime.now(timezone.utc)
    vendor = Vendor(
        id="t0000000-0000-0000-0000-000000000003",
        name="Local Demo Corp",
        status="active",
        country="IN",
        website="acme.local",
    )

    db = AsyncMock(spec=AsyncSession)
    res_mock = MagicMock()
    res_mock.scalar.return_value = False
    db.execute.return_value = res_mock

    web_obs, _ = await collect_web(db, vendor, now)
    assert web_obs.fields["web.reachable"] is True
    assert web_obs.fields["web.ssl_grade"] is None
    assert web_obs.fields["web.cert_valid"] is True

    email_obs, _ = await collect_email(db, vendor, now)
    assert email_obs.fields["email.has_mx"] is True
    assert email_obs.fields["email.spf_present"] is True
    assert email_obs.fields["email.dmarc_policy"] == "reject"


# ---------------------------------------------------------------------------
# Fix 4: Inherent Tier and Effective Tier Computation
# ---------------------------------------------------------------------------

def test_effective_tier_strictness_ranking():
    """Strictness ranking: low (0) < moderate (1) < high (2) < critical (3).
    Only flags inherent_profile_missing if inherent_tier is None.
    """
    # 1. Inherent tier None -> fallback to spend tier + provisional reason
    eff, reasons = calculate_effective_tier(spend_tier="standard", inherent_tier=None)
    assert eff == "moderate"
    assert any(r["code"] == "inherent_profile_missing" for r in reasons)

    # 2. Inherent tier Critical on petty spend (₹0) -> effective tier Critical, no inherent_profile_missing
    eff, reasons = calculate_effective_tier(spend_tier="petty", inherent_tier="critical")
    assert eff == "critical"
    assert not any(r["code"] == "inherent_profile_missing" for r in reasons)

    # 3. Inherent tier Low on strategic spend (₹1 Cr) -> effective tier High (strategic mapped to high)
    eff, reasons = calculate_effective_tier(spend_tier="strategic", inherent_tier="low")
    assert eff == "high"
    assert not any(r["code"] == "inherent_profile_missing" for r in reasons)

    # 4. Inherent tier High on standard spend -> effective tier High
    eff, reasons = calculate_effective_tier(spend_tier="standard", inherent_tier="high")
    assert eff == "high"
    assert not any(r["code"] == "inherent_profile_missing" for r in reasons)


def test_scorecard_evaluates_with_critical_effective_tier():
    """Setting inherent_tier='critical' enforces critical tier required signals in the scorecard."""
    ruleset = get_default_ruleset()
    now = datetime.now(timezone.utc)

    # Minimal observations
    observations = {
        "sanctions": {"signal_key": "sanctions", "status": "ok", "fields": {"sanctions.status": "no_match"}},
        "jurisdiction": {"signal_key": "jurisdiction", "status": "ok", "fields": {"country.prohibited": False, "country.high_risk": False}},
    }

    vendor_context = {
        "name": "Critical Infrastructure Vendor",
        "spend_tier": "petty",
        "inherent_tier": "critical",
    }

    result = evaluate_risk(ruleset=ruleset, observations=observations, assessed_at=now, vendor_context=vendor_context)
    assert result["effective_tier"] == "critical"
    assert not any(r["code"] == "inherent_profile_missing" for r in result["provisional_reasons"])


# ---------------------------------------------------------------------------
# Fix 5: Bank SWIFT/BIC ISO 9362 Validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bank_swift_validation():
    """Foreign accounts with valid 8 or 11 character ISO 9362 SWIFT codes pass as foreign_account.
    Malformed codes fail with invalid status (R-BNK-01).
    """
    now = datetime.now(timezone.utc)
    db = AsyncMock(spec=AsyncSession)

    # 1. Valid 8-char SWIFT
    v1 = Vendor(id="b1", name="German Vendor GmbH", country="DE", swift_bic="DEUTDEDD", bank_name="Deutsche Bank")
    res1 = MagicMock()
    res1.first.return_value = SimpleNamespace(
        country="DE", swift_bic="DEUTDEDD", bank_name="Deutsche Bank",
        routing_code=None, bank_account_number="12345678", ifsc_verification_status=None
    )
    db.execute.return_value = res1
    obs1, raw1 = await collect_bank(db, v1, now)
    assert obs1.fields["bank.status"] == "foreign_account"
    assert obs1.status == "not_applicable"

    # 2. Valid 11-char SWIFT
    v2 = Vendor(id="b2", name="UK Vendor Ltd", country="GB", swift_bic="BARCGB22XXX", bank_name="Barclays Bank")
    res2 = MagicMock()
    res2.first.return_value = SimpleNamespace(
        country="GB", swift_bic="BARCGB22XXX", bank_name="Barclays Bank",
        routing_code=None, bank_account_number="12345678", ifsc_verification_status=None
    )
    db.execute.return_value = res2
    obs2, raw2 = await collect_bank(db, v2, now)
    assert obs2.fields["bank.status"] == "foreign_account"

    # 3. Invalid format SWIFT (malformed length / invalid chars)
    v3 = Vendor(id="b3", name="US Vendor Inc", country="US", swift_bic="INVALID_SWIFT_12345", bank_name="Generic Bank")
    res3 = MagicMock()
    res3.first.return_value = SimpleNamespace(
        country="US", swift_bic="INVALID_SWIFT_12345", bank_name="Generic Bank",
        routing_code=None, bank_account_number="12345678", ifsc_verification_status=None
    )
    db.execute.return_value = res3
    obs3, raw3 = await collect_bank(db, v3, now)
    assert obs3.fields["bank.status"] == "invalid"
    assert obs3.status == "error"


@pytest.mark.asyncio
async def test_parallel_collectors_commit_their_own_sessions():
    """Each Phase 2 check writes its observation in its own session. Closing
    that session without a commit rolled the observation back, and saving the
    score then failed on risk_score_rule_results.observation_id (found 25 Oct:
    every contract generation and risk recompute returned 500)."""
    from app.services.collectors import collector_manager as cm
    obs = SimpleNamespace(fields={})
    task_db = MagicMock(commit=AsyncMock())
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=task_db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    collect = AsyncMock(return_value=(obs, None))
    names = ["collect_sanctions", "collect_jurisdiction", "collect_bank", "collect_company_age",
             "collect_delivery_sla", "collect_feedback", "collect_incidents", "collect_gst",
             "collect_web", "collect_email", "collect_breach", "collect_certification",
             "collect_financial", "collect_adverse_media"]
    with patch("app.database.async_session_factory", factory):
        with patch.multiple(cm, **{n: collect for n in names}):
            await collect_all_signals(SimpleNamespace(), SimpleNamespace(id="v-1", status="active"))
    assert factory.call_count == 6
    assert task_db.commit.await_count == 6
