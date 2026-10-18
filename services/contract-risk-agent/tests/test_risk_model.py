"""FR-04: hard overrides beat the model, missing data is left out (not
filled with a value that reads as risk), signal coverage is reported, and
the red-team profiles land in their expected bands."""
import json
import os
import sys
import warnings

import pytest

ML_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml")
sys.path.insert(0, ML_DIR)

from generate_vendor_dataset import FEATURE_COLUMNS, build_dataset  # noqa: E402
from train_risk_model import fit, split  # noqa: E402
from app.services.risk_service import assess, hard_override_checks  # noqa: E402
from train_risk_model import train, MODEL_PATH  # noqa: E402
import joblib  # noqa: E402

GOOD = {"vendor_tenure_months": 96, "on_time_delivery_rate": 0.97, "financial_stability_score": 0.92,
        "breach_disclosure_count": 0, "security_cert_flag": 1, "geo_risk_flag": 0}
NOTHING = {name: None for name in FEATURE_COLUMNS}


@pytest.fixture(scope="module")
def model():
    warnings.filterwarnings("ignore")
    X_train, _, y_train, _ = split(build_dataset())
    return fit(X_train, y_train)


def test_override_beats_the_model(model):
    clean = assess(model, FEATURE_COLUMNS, GOOD, hard_override_checks("active"))
    assert clean["band"] == "Low"
    overridden = assess(model, FEATURE_COLUMNS, GOOD, hard_override_checks("cancelled"))
    assert overridden["band"] == "High"
    assert overridden["top_factors"][0]["feature"] == "override:gstin"
    assert overridden["top_factors"][0]["override"] is True
    assert overridden["score"] == clean["score"]  # the model's own score is kept


@pytest.mark.parametrize("status,expected", [
    ("cancelled", "triggered"), ("Suspended", "triggered"), ("active", "clear"),
    (None, "not_checked"), ("unverified", "not_checked"),
])
def test_gstin_check_states(status, expected):
    gstin = next(c for c in hard_override_checks(status) if c["check"] == "gstin")
    assert gstin["status"] == expected


def test_sanctions_and_ifsc_are_reported_as_not_checked_until_their_data_exists():
    checks = {c["check"]: c["status"] for c in hard_override_checks("active")}
    assert checks["sanctions"] == "not_checked" and checks["ifsc"] == "not_checked"
    assert {c["check"]: c["status"] for c in hard_override_checks("active", sanctions_match=True)}["sanctions"] == "triggered"


def test_missing_data_is_not_penalised(model):
    # Before FR-04, missing on-time rate / financial stability were filled
    # with 0.5 — worse than the typical vendor — so "no data" read as risk.
    known = {**GOOD, "on_time_delivery_rate": None, "financial_stability_score": None}
    filled_with_old_default = {**GOOD, "on_time_delivery_rate": 0.5, "financial_stability_score": 0.5}
    gap = assess(model, FEATURE_COLUMNS, known, hard_override_checks(None))
    old = assess(model, FEATURE_COLUMNS, filled_with_old_default, hard_override_checks(None))
    assert gap["score"] < old["score"]
    assert gap["band"] != "High"
    assert not any(f["feature"] in ("on_time_delivery_rate", "financial_stability_score") for f in gap["top_factors"])


def test_nothing_on_file_is_scored_without_crashing_and_says_so(model):
    r = assess(model, FEATURE_COLUMNS, NOTHING, hard_override_checks(None))
    assert (r["signals_used"], r["signals_total"]) == (0, 6)
    assert r["top_factors"] == []
    assert r["band"] != "High"


def test_signal_count(model):
    partial = {**NOTHING, "vendor_tenure_months": 12, "geo_risk_flag": 1}
    assert assess(model, FEATURE_COLUMNS, partial, hard_override_checks(None))["signals_used"] == 2


def test_redteam_profiles_land_in_their_expected_bands(model):
    with open(os.path.join(ML_DIR, "redteam_profiles.json")) as f:
        profiles = json.load(f)["profiles"]
    misses = []
    for p in profiles:
        band = assess(model, FEATURE_COLUMNS, p["features"], hard_override_checks(p.get("gstin_status")))["band"]
        ok = band == p["expected"] if "expected" in p else band != p["expected_not"]
        if not ok:
            misses.append(f"{p['name']}: {band}")
    assert misses == []


# The original trained-artifact checks (kept from before FR-04).
class TestRiskModel:
    @classmethod
    def setup_class(cls):
        train()
        bundle = joblib.load(MODEL_PATH)
        cls.model = bundle["model"]
        cls.features = bundle["features"]

    def _predict(self, **overrides) -> float:
        vector = {
            "vendor_tenure_months": overrides.get("vendor_tenure_months", 24),
            "on_time_delivery_rate": overrides.get("on_time_delivery_rate", 0.8),
            "financial_stability_score": overrides.get("financial_stability_score", 0.8),
            "breach_disclosure_count": overrides.get("breach_disclosure_count", 0),
            "security_cert_flag": overrides.get("security_cert_flag", 1),
            "geo_risk_flag": overrides.get("geo_risk_flag", 0),
        }
        X = [[vector[f] for f in self.features]]
        return float(self.model.predict_proba(X)[0][1])

    def test_low_risk_vendor_scores_lower_than_high_risk_vendor(self):
        low_risk_score = self._predict(
            vendor_tenure_months=96, on_time_delivery_rate=0.98, financial_stability_score=0.95,
            breach_disclosure_count=0, security_cert_flag=1, geo_risk_flag=0,
        )
        high_risk_score = self._predict(
            vendor_tenure_months=2, on_time_delivery_rate=0.35, financial_stability_score=0.2,
            breach_disclosure_count=4, security_cert_flag=0, geo_risk_flag=1,
        )
        assert low_risk_score < high_risk_score

    def test_scores_are_valid_probabilities(self):
        score = self._predict()
        assert 0.0 <= score <= 1.0

    def test_feature_importances_available_for_explainability(self):
        assert len(self.model.feature_importances_) == len(self.features)
        assert all(importance >= 0 for importance in self.model.feature_importances_)
