"""Tests for Prompt 11: Breach signal local matching, GST identity match, and honest scorecard display."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.services.breach_catalogue import (
    clean_domain,
    is_short_or_common,
    download_and_store_catalogue,
    match_vendor_breaches,
)
from app.services.collectors.identity_collectors import (
    validate_gstin_offline,
    check_pan_consistency,
    compare_gst_names,
)
from app.services.scorecard.default_ruleset import get_default_ruleset
from app.services.scorecard.engine import evaluate_risk


# =====================================================================
# 5.1 BREACH SIGNAL TESTS
# =====================================================================
class TestBreachCatalogueAndMatching:
    def test_clean_domain(self):
        assert clean_domain("https://www.adda.io/portal") == "adda.io"
        assert clean_domain("HTTP://APP.ADDA.IO/") == "app.adda.io"
        assert clean_domain("adda.io") == "adda.io"
        assert clean_domain(None) is None

    def test_short_or_common_term(self):
        assert is_short_or_common("adda") is True
        assert is_short_or_common("uber") is True
        assert is_short_or_common("tech") is True
        assert is_short_or_common("Technologies") is False
        assert is_short_or_common("3Five8") is False

    @pytest.mark.asyncio
    async def test_catalogue_filtering_and_checksum(self):
        raw_breaches = [
            {
                "Name": "ValidBreach",
                "Title": "Valid Breach Inc",
                "Domain": "valid.com",
                "BreachDate": "2024-01-01",
                "PwnCount": 50000,
                "IsVerified": True,
                "IsFabricated": False,
                "IsSpamList": False,
                "IsRetired": False,
                "DataClasses": ["Email addresses", "Passwords"],
            },
            {
                "Name": "FabricatedBreach",
                "Title": "Fake",
                "Domain": "fake.com",
                "BreachDate": "2024-01-01",
                "PwnCount": 100,
                "IsVerified": True,
                "IsFabricated": True,
                "IsSpamList": False,
                "IsRetired": False,
            },
            {
                "Name": "SpamBreach",
                "Title": "Spam List",
                "Domain": "spam.com",
                "BreachDate": "2024-01-01",
                "PwnCount": 1000,
                "IsVerified": True,
                "IsFabricated": False,
                "IsSpamList": True,
                "IsRetired": False,
            },
            {
                "Name": "RetiredBreach",
                "Title": "Retired Service",
                "Domain": "retired.com",
                "BreachDate": "2020-01-01",
                "PwnCount": 200,
                "IsVerified": True,
                "IsFabricated": False,
                "IsSpamList": False,
                "IsRetired": True,
            },
        ]
        raw_json_str = json.dumps(raw_breaches)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        success, msg, count = await download_and_store_catalogue(
            db=mock_db,
            source="manual_upload",
            uploaded_by="admin@example.com",
            raw_json_str=raw_json_str,
        )

        assert success is True
        # Only 1 valid breach meets is_verified=True, is_fabricated=False, is_spam_list=False, is_retired=False
        assert count == 1
        assert "Successfully loaded 1 verified records" in msg

    @pytest.mark.asyncio
    async def test_entity_matching_domain_and_candidates(self):
        now = datetime.now(timezone.utc)
        meta = SimpleNamespace(
            version_sha256="test-sha-123",
            fetched_at=now,
        )

        entries = [
            SimpleNamespace(
                name="ADDA",
                title="ADDA Apartment SuperApp",
                domain="adda.io",
                breach_date=datetime(2025, 3, 24).date(),
                added_date=datetime(2025, 3, 25).date(),
                pwn_count=1829314,
                data_classes=["Email addresses", "Names", "Phone numbers"],
                description="ADDA breach",
            ),
            SimpleNamespace(
                name="AddaTechCand",
                title="Adda Technologies",
                domain="other-domain.net",
                breach_date=datetime(2024, 1, 1).date(),
                added_date=datetime(2024, 1, 2).date(),
                pwn_count=10000,
                data_classes=["Email addresses"],
                description="Adda Tech breach",
            ),
            SimpleNamespace(
                name="Zomato",
                title="Zomato Food Delivery",
                domain="zomato.com",
                breach_date=datetime(2017, 5, 1).date(),
                added_date=datetime(2017, 5, 2).date(),
                pwn_count=17000000,
                data_classes=["Passwords"],
                description="Zomato breach",
            ),
        ]

        mock_db = AsyncMock()

        async def mock_execute(stmt, params=None):
            m_res = MagicMock()
            s_str = str(stmt)
            if "breach_catalogue_meta" in s_str or "breach_catalogue_meta" in getattr(stmt, "_sql", ""):
                m_res.scalars.return_value.first.return_value = meta
                return m_res
            if "breach_vendor_reviews" in s_str or "breach_vendor_reviews" in getattr(stmt, "_sql", ""):
                m_res.all.return_value = []
                return m_res
            m_res.scalars.return_value.all.return_value = entries
            return m_res

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        vendor = SimpleNamespace(
            id="v-123",
            name="3Five8 Technologies Pvt. Ltd.",
            normalized_name="3five8 technologies",
            legal_name="3Five8 Technologies Private Limited",
        )

        # 1. Exact domain match test (adda.io)
        res = await match_vendor_breaches(
            db=mock_db,
            vendor=vendor,
            vendor_domain="adda.io",
            now=now,
        )
        assert len(res["records_domain_match"]) == 1
        assert res["records_domain_match"][0]["name"] == "ADDA"

        # 2. Subdomain match test (app.adda.io)
        res_sub = await match_vendor_breaches(
            db=mock_db,
            vendor=vendor,
            vendor_domain="app.adda.io",
            now=now,
        )
        assert len(res_sub["records_domain_match"]) == 1
        assert res_sub["records_domain_match"][0]["name"] == "ADDA"

        # 3. Name candidate test: vendor with different domain, but name "Adda Technologies"
        vendor_cand = SimpleNamespace(
            id="v-cand",
            name="Adda Technologies",
            normalized_name="adda technologies",
            legal_name="Adda Technologies Inc",
        )
        res_cand = await match_vendor_breaches(
            db=mock_db,
            vendor=vendor_cand,
            vendor_domain="unrelateddomain.org",
            now=now,
        )
        assert len(res_cand["records_domain_match"]) == 0
        assert len(res_cand["records_name_candidate"]) == 1
        assert res_cand["records_name_candidate"][0]["name"] == "AddaTechCand"


# =====================================================================
# 5.2 GST IDENTITY TESTS
# =====================================================================
class TestGstIdentityMatching:
    def test_offline_format_and_check_digit(self):
        # Valid GSTIN
        valid_gstin = "29AAACZ3829K1ZT"
        is_valid, err = validate_gstin_offline(valid_gstin)
        assert is_valid is True
        assert err == "valid"

        # Invalid format (too short / wrong format)
        is_valid_inv, err_inv = validate_gstin_offline("INVALID123")
        assert is_valid_inv is False
        assert "invalid" in err_inv.lower()

        # Invalid state code (38 not between 01 and 37)
        is_valid_bad_state, err_bad_state = validate_gstin_offline("38AAACZ3829K1ZT")
        assert is_valid_bad_state is False
        assert "state code" in err_bad_state.lower()

    def test_pan_entity_type_check(self):
        # 4th character 'C' = Company -> consistent with Pvt Ltd
        suffix_c, pan_c = check_pan_consistency("3Five8 Technologies Pvt. Ltd.", "C")
        assert suffix_c == "pvt_ltd"
        assert pan_c is True

        # 4th character 'P' = Individual (Proprietorship) -> inconsistent with Pvt Ltd
        suffix_p, pan_p = check_pan_consistency("3Five8 Technologies Pvt. Ltd.", "P")
        assert suffix_p == "pvt_ltd"
        assert pan_p is False

    def test_name_comparison_levels(self):
        # Exact match (>= 90%)
        m_level_exact, score_exact = compare_gst_names(
            "3Five8 Technologies Private Limited",
            "3Five8 Technologies Pvt. Ltd.",
            "",
        )
        assert m_level_exact == "exact"
        assert score_exact >= 90

        # Close match (75-89%)
        m_level_close, score_close = compare_gst_names(
            "3Five8 Software Technologies",
            "3Five8 Technologies Pvt. Ltd.",
            "",
        )
        assert m_level_close in ("exact", "close")
        assert score_close >= 75

        # Mismatch (< 75%)
        m_level_mismatch, score_mismatch = compare_gst_names(
            "Completely Different Enterprise Inc",
            "3Five8 Technologies Pvt. Ltd.",
            "",
        )
        assert m_level_mismatch == "mismatch"
        assert score_mismatch < 75


# =====================================================================
# 5.3 SCORECARD EVALUATION AND HONEST DISPLAY TESTS
# =====================================================================
class TestScorecardEvaluationAndHonestDisplay:
    def test_ruleset_sum_strictly_100_and_gst_max_20(self):
        ruleset = get_default_ruleset()
        signals = ruleset["signals"]
        total_max = sum(s["max_points"] for s in signals)
        assert total_max == 100, f"Expected ruleset max_points to sum to 100, got {total_max}"

        gst_signal = next(s for s in signals if s["key"] == "gst")
        assert gst_signal["max_points"] == 20, f"Expected GST max_points to be 20, got {gst_signal['max_points']}"

        breach_signal = next(s for s in signals if s["key"] == "breach")
        assert breach_signal["max_points"] == 4, f"Expected Breach max_points to be 4, got {breach_signal['max_points']}"

    def test_gst_rules_in_scorecard(self):
        ruleset = get_default_ruleset()
        now = datetime.now(timezone.utc)

        # Test GST mismatch (< 75%) -> R-GST-09 (12 pts)
        obs_gst_mismatch = [
            {
                "signal_key": "gst",
                "status": "ok",
                "fetched_at": now.isoformat(),
                "fields": {
                    "gstin.status": "active",
                    "gstin.name_match_level": "mismatch",
                    "gstin.name_match_pct": 60,
                    "gstin.pan_type_consistent": True,
                    "gstin.number": "29AAACZ3829K1ZT",
                    "gstin.return_filed_within_60d": True,
                },
            }
        ]
        res = evaluate_risk(
            ruleset=ruleset,
            observations=obs_gst_mismatch,
            assessed_at=now,
            vendor_context={"tier": "Critical", "country": "IN"},
        )
        gst_res = next(r for r in res["rule_results"] if r["signal_key"] == "gst")
        assert gst_res["rule_id"] == "R-GST-09"
        assert gst_res["points"] == 12
        assert "impersonation" in gst_res["reason_text"].lower() or "similar" in gst_res["reason_text"].lower()

    def test_breach_candidate_requires_review(self):
        ruleset = get_default_ruleset()
        now = datetime.now(timezone.utc)

        # Name candidate pending review -> R-BRC-08 (review_pending, potential_points=4)
        obs_breach_candidate = [
            {
                "signal_key": "breach",
                "status": "ok",
                "fetched_at": now.isoformat(),
                "fields": {
                    "breach.has_candidates": True,
                    "breach.records_domain_match": [],
                    "breach.records_name_candidate": [{"name": "CandidateBreach", "pwn_count": 50000}],
                    "breach.review_status": "pending_review",
                    "breach.review_state": "candidate_pending",
                    "breach.catalogue_version": "abc12345",
                    "breach.days_since_last": 120,
                    "breach.max_pwn_count": 50000,
                },
            }
        ]
        res = evaluate_risk(
            ruleset=ruleset,
            observations=obs_breach_candidate,
            assessed_at=now,
            vendor_context={"tier": "Critical", "country": "IN"},
        )
        breach_res = next(r for r in res["rule_results"] if r["signal_key"] == "breach")
        assert breach_res["rule_id"] == "R-BRC-08"
        assert breach_res["status"] == "review_pending"
        assert breach_res["potential_points"] == 4
        assert "reviewer must confirm" in breach_res["reason_text"].lower()

    def test_honest_scorecard_explanation_structure(self):
        ruleset = get_default_ruleset()
        now = datetime.now(timezone.utc)

        # Seed vendor state: Critical tier, bank unverified, GST offline, sanctions not checked
        obs = [
            {
                "signal_key": "gst",
                "status": "ok",
                "fetched_at": now.isoformat(),
                "fields": {
                    "gstin.status": "active",
                    "gstin.name_match_level": "exact",
                    "gstin.name_match_pct": 98,
                    "gstin.pan_type_consistent": True,
                    "gstin.number": "29AAACZ3829K1ZT",
                    "gstin.return_filed_within_60d": True,
                },
            },
            {
                "signal_key": "sanctions",
                "status": "not_checked",
                "fetched_at": now.isoformat(),
                "fields": {
                    "sanctions.status": "not_screened",
                    "sanctions.not_checked_reason": "Live screening not invoked",
                    "sanctions.matched": False,
                },
            },
            {
                "signal_key": "bank",
                "status": "not_checked",
                "fetched_at": now.isoformat(),
                "fields": {
                    "bank.status": "pending",
                    "bank.reason": "Bank details not yet verified",
                },
            },
        ]
        res = evaluate_risk(
            ruleset=ruleset,
            observations=obs,
            assessed_at=now,
            vendor_context={"tier": "Critical", "country": "IN"},
        )

        expl = res["explanation"]

        # 1. Honest arithmetic line present and never "Total = 0 = 0"
        arithmetic_line = expl.get("arithmetic_line", "")
        assert "Total =" in arithmetic_line
        assert "assessed" in arithmetic_line
        assert "potential points" in arithmetic_line
        assert "Total = 0 = 0" not in arithmetic_line

        # 2. Safety notice present when required checks are missing
        safety_notice = expl.get("safety_notice", "")
        assert "Required checks incomplete" in safety_notice or "SAFETY NOTICE" in safety_notice

        # 3. Group headers and sentence formatting
        groups = expl.get("groups", [])
        assert len(groups) > 0
        for g in groups:
            header = g.get("header", "")
            assert "checks completed" in header
            for sentence in g.get("sentences", []):
                assert ":" in sentence, f"Sentence missing short_label prefix: {sentence}"
                assert "—." not in sentence, f"Found bare dash in sentence: {sentence}"

        # 4. Attribution present
        assert "Breach data from Have I Been Pwned" in expl.get("attribution", "")
