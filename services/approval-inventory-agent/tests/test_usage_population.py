"""FR-32: the licence-usage anomaly model is trained and evaluated on a
labelled simulated population, scored relative to the data's own date, and
the demo licences land where their generated patterns say they should."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "ml"))

from usage_population import FEATURES, FEATURE_SETS, columns, simulate, training_split  # noqa: E402

from app.services.usage_service import _events_as_of  # noqa: E402

THRESHOLDS = (0.34, 0.39)   # watch, anomalous — docs/results/licence-anomaly.md


def test_snapshot_data_is_scored_as_of_its_last_event():
    snapshot = [{"login_timestamp": "2026-09-24T10:00:00"}, {"login_timestamp": "2026-09-20T10:00:00"}]
    today = datetime(2026, 10, 16, tzinfo=timezone.utc)
    assert _events_as_of(snapshot, today) == datetime(2026, 9, 24, 10, tzinfo=timezone.utc)
    live = [{"login_timestamp": (today - timedelta(minutes=5)).isoformat()}]
    assert _events_as_of(live, today) == today - timedelta(minutes=5)
    assert _events_as_of([], today) == today


def test_stale_snapshot_looks_abandoned_without_the_fix():
    """Why it matters: against today's date a snapshot from three weeks ago
    reports three weeks without a login."""
    from app.ml.usage_anomaly import UsageAnomalyScorer
    end = datetime(2026, 9, 24, tzinfo=timezone.utc)
    events = simulate(np.random.default_rng(1), "X", "steady", 50, end)
    names = UsageAnomalyScorer._engineer(events, 50, now=end)[1]
    days = names.index("days_since_last_login")
    as_of = UsageAnomalyScorer._engineer(events, 50, now=_events_as_of(events, end + timedelta(days=22)))[0][0][days]
    stale = UsageAnomalyScorer._engineer(events, 50, now=end + timedelta(days=22))[0][0][days]
    assert as_of < 1 and stale > 21


@pytest.fixture(scope="module")
def split():
    return training_split()


def test_trainer_and_evaluation_share_one_disjoint_split(split):
    X_all, y, pats, names, tr, va, te = split
    assert len(set(tr) & set(va)) == len(set(tr) & set(te)) == len(set(va) & set(te)) == 0
    assert len(tr) + len(va) + len(te) == len(y)
    again = training_split()
    assert (again[4] == tr).all() and (again[6] == te).all()    # deterministic
    assert set(FEATURES) <= set(names) and FEATURES == FEATURE_SETS["scale_free"]


def test_model_separates_the_patterns_on_held_out_licences(split):
    from sklearn.ensemble import IsolationForest
    from sklearn.metrics import average_precision_score
    X_all, y, pats, names, tr, va, te = split
    X = X_all[:, columns(names, FEATURES)]
    model = IsolationForest(n_estimators=200, random_state=42, n_jobs=-1).fit(X[tr])
    raw = model.score_samples(X[tr])
    score = lambda rows: np.clip((raw.max() - model.score_samples(rows)) / (raw.max() - raw.min()), 0, 1)
    assert average_precision_score(y[te], score(X[te])) >= 0.8
    # every simulated abandoned licence is flagged, no steady one is called anomalous on average
    assert score(X[te][pats[te] == "abandoned"]).min() >= THRESHOLDS[1]
    assert score(X[te][pats[te] == "steady"]).mean() < THRESHOLDS[0]


def test_demo_licences_match_their_generated_patterns(split):
    """The committed demo data: the three normal licences are normal, and
    Docker Pro (sudden drop-off) and Notion (gradual decline) score higher
    than all of them."""
    from sklearn.ensemble import IsolationForest
    from app.ml.usage_anomaly import UsageAnomalyScorer
    X_all, y, pats, names, tr, va, te = split
    cols = columns(names, FEATURES)
    model = IsolationForest(n_estimators=200, random_state=42, n_jobs=-1).fit(X_all[tr][:, cols])
    raw = model.score_samples(X_all[tr][:, cols])
    path = os.path.join(_ROOT, "..", "..", "data", "synthetic-sso-logs", "sso_login_events.json")
    if not os.path.exists(path):
        pytest.skip("demo SSO data not mounted")
    events = json.load(open(path))
    as_of = _events_as_of(events, datetime.now(timezone.utc))
    seats = {"Microsoft 365 E3": 50, "Slack Enterprise": 45, "JetBrains All Products Pack": 120,
             "Docker Pro": 60, "Notion Team": 200}
    score, status = {}, {}
    for app, n in seats.items():
        vec, _ = UsageAnomalyScorer._engineer([e for e in events if e["app_name"] == app], n, now=as_of)
        score[app] = float(np.clip((raw.max() - model.score_samples(vec[:, cols])[0]) / (raw.max() - raw.min()), 0, 1))
        status[app] = "anomalous" if score[app] >= THRESHOLDS[1] else "watch" if score[app] >= THRESHOLDS[0] else "normal"
    normal = ("Microsoft 365 E3", "Slack Enterprise", "JetBrains All Products Pack")
    assert all(status[a] == "normal" for a in normal), status
    # The two declining licences score above every normal one. (Both sit
    # just under the watch line — the model catches 87 % of drop-offs and
    # 71 % of declines on the test set; these two are among the misses.)
    assert min(score["Docker Pro"], score["Notion Team"]) > max(score[a] for a in normal), score


def test_logins_stay_on_their_simulated_day():
    """The demo log ends at 23:59; login times must not spill into the next
    day, or Friday logins become Saturday ones and a weekend-dip licence
    (JetBrains in the demo) looks like it's used at weekends."""
    end = datetime(2026, 10, 15, 23, 59, tzinfo=timezone.utc)
    events = simulate(np.random.default_rng(3), "X", "weekend_dip", 120, end)
    stamps = [datetime.fromisoformat(e["login_timestamp"]) for e in events]
    weekend = sum(t.weekday() >= 5 for t in stamps) / len(stamps)
    assert weekend < 0.05, weekend
    assert max(stamps) <= end


def test_demo_log_weekend_dip_licence_is_quiet_at_weekends():
    path = os.path.join(_ROOT, "..", "..", "data", "synthetic-sso-logs", "sso_login_events.json")
    if not os.path.exists(path):
        pytest.skip("demo SSO data not mounted")
    stamps = [datetime.fromisoformat(e["login_timestamp"]) for e in json.load(open(path))
              if e["app_name"] == "JetBrains All Products Pack"]
    assert sum(t.weekday() >= 5 for t in stamps) / len(stamps) < 0.05


def test_factor_contributions_point_toward_risk(split):
    """`contribution` > 0 must mean "pushes toward anomalous". SHAP explains
    IsolationForest's normality score, so the sign has to be flipped; for a
    licence most users stopped using, losing its recent users is the top
    risk factor. (IsolationForest also isolates unusually *high* values, so
    a normal licence can still show a factor that raises its score.)"""
    shap = pytest.importorskip("shap")
    from sklearn.ensemble import IsolationForest
    from app.ml.usage_anomaly import UsageAnomalyScorer
    X_all, y, pats, names, tr, va, te = split
    X = X_all[tr][:, columns(names, FEATURES)]
    model = IsolationForest(n_estimators=200, contamination=0.3, random_state=42, n_jobs=-1).fit(X)
    raw = model.score_samples(X)
    bundle = {"model": model, "features": FEATURES, "score_min": float(raw.min()), "score_max": float(raw.max()),
              "version": "v_population_test", "shap_explainer": shap.TreeExplainer(model)}
    saved = (UsageAnomalyScorer._bundle, UsageAnomalyScorer._shap_explainer)
    UsageAnomalyScorer._bundle, UsageAnomalyScorer._shap_explainer = bundle, bundle["shap_explainer"]
    try:
        _check_factor_directions(UsageAnomalyScorer())
    finally:
        UsageAnomalyScorer._bundle, UsageAnomalyScorer._shap_explainer = saved


def _check_factor_directions(scorer):
    end = datetime(2026, 10, 15, tzinfo=timezone.utc)
    rng = np.random.default_rng(11)
    for pattern in ("sudden_dropoff", "steady"):
        result = scorer.score(pattern, simulate(rng, pattern, pattern, 80, end), 80, now=end)
        factors = result["top_factors"]
        assert all(f["direction"] == ("increasing_risk" if f["contribution"] > 0 else "decreasing_risk")
                   for f in factors), factors
        if pattern == "sudden_dropoff":
            # Most users stopped: losing last week's users is the main risk factor.
            assert factors[0]["feature"] == "retention_7d" and factors[0]["contribution"] > 0, factors
