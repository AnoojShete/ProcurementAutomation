"""Seeded synthetic licence-usage population with known patterns (FR-32).

The anomaly model was trained on five rows (one per demo licence), so with
contamination 0.2 it always called one of five licences anomalous. This
module simulates many licences with a known usage pattern each, so the
model can be trained on a real distribution and evaluated against labels.

Patterns (label 1 = should be flagged for review / reclaim):
  steady           0  most seats log in on most weekdays, some at weekends
  weekend_dip      0  the same with almost no weekend use (seasonal, normal)
  low_stable       0  only a quarter to a half of the seats in use, but stable
  gradual_decline  1  users drop away one by one across the 90 days
  sudden_dropoff   1  most users stop on one day between day 45 and 78
  abandoned        1  everyone stops 21-45 days before the end

Features come from the production code (UsageAnomalyScorer._engineer), so
training, evaluation and live scoring use exactly the same numbers.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))          # service root, for `app.`

PATTERNS = {
    "steady": 0, "weekend_dip": 0, "low_stable": 0,
    "gradual_decline": 1, "sudden_dropoff": 1, "abandoned": 1,
}
# Share of each pattern in a simulated population (30 % anomalous).
MIX = {"steady": 0.40, "weekend_dip": 0.15, "low_stable": 0.15,
       "gradual_decline": 0.12, "sudden_dropoff": 0.12, "abandoned": 0.06}
DAYS = 90

# Candidate feature sets (columns of UsageAnomalyScorer._engineer). The
# evaluation picks one on validation data; FEATURES is what production
# trains on — keep it equal to the evaluation's choice
# (docs/results/licence-anomaly.md).
FEATURE_SETS = {
    "original": ["active_seats_7d", "active_seats_30d", "active_seats_90d", "utilisation_ratio",
                 "dod_rate_change", "wow_rate_change", "variance_daily_logins",
                 "days_since_last_login", "weekend_ratio"],
    "scale_free": ["utilisation_7d", "utilisation_ratio", "utilisation_90d", "retention_7d",
                   "retention_30d", "days_since_last_login", "weekend_ratio"],
    "retention": ["retention_7d", "retention_30d", "days_since_last_login"],
}
FEATURES = FEATURE_SETS["scale_free"]


def simulate(rng: np.random.Generator, app_name: str, pattern: str, seats: int, end: datetime) -> list[dict]:
    """Login events for one licence over the DAYS before `end`."""
    start = end - timedelta(days=DAYS)
    in_use = rng.uniform(0.25, 0.45) if pattern == "low_stable" else rng.uniform(0.65, 0.95)
    users = [f"user{i}@company.com" for i in range(max(1, int(seats * in_use)))]
    p_weekday = rng.uniform(0.55, 0.9)
    p_weekend = rng.uniform(0.0, 0.03) if pattern == "weekend_dip" else rng.uniform(0.1, 0.3)

    # The last day (exclusive) on which each user still logs in.
    stop = np.full(len(users), DAYS)
    if pattern == "gradual_decline":
        keep = rng.uniform(0.2, 0.45)
        leaving = rng.random(len(users)) > keep
        stop[leaving] = rng.integers(10, DAYS - 5, leaving.sum())
    elif pattern == "sudden_dropoff":
        cut = int(rng.integers(45, 79))
        leaving = rng.random(len(users)) > rng.uniform(0.05, 0.3)
        stop[leaving] = cut
    elif pattern == "abandoned":
        stop[:] = DAYS - int(rng.integers(21, 46))

    events = []
    for d in range(DAYS):
        day = start + timedelta(days=d)
        weekend = day.weekday() >= 5
        p = p_weekend if weekend else p_weekday
        active = (stop > d) & (rng.random(len(users)) < p)
        for i in np.flatnonzero(active):
            ts = day + timedelta(hours=int(rng.integers(8, 19)), minutes=int(rng.integers(0, 60)))
            events.append({"user_email": users[i], "app_name": app_name, "login_timestamp": ts.isoformat(),
                           "session_duration_minutes": int(rng.integers(10, 480))})
    return events


def population(n: int, seed: int, end: datetime | None = None):
    """(X, y, patterns, seats, column names) for n simulated licences; X has
    every column _engineer produces — select a feature set by name."""
    from app.ml.usage_anomaly import UsageAnomalyScorer
    end = end or datetime(2026, 10, 15, tzinfo=timezone.utc)
    rng = np.random.default_rng(seed)
    names = list(MIX)
    picks = rng.choice(names, size=n, p=[MIX[k] for k in names])
    X, y, seats_out, names_out = [], [], [], []
    for i, pattern in enumerate(picks):
        seats = int(rng.integers(20, 221))
        events = simulate(rng, f"app-{i}", pattern, seats, end)
        vec, names_out = UsageAnomalyScorer._engineer(events, seats, now=end)
        X.append(vec[0])
        y.append(PATTERNS[pattern])
        seats_out.append(seats)
    return np.array(X), np.array(y), np.array(picks), np.array(seats_out), list(names_out)


def columns(names: list[str], wanted: list[str]) -> list[int]:
    return [names.index(c) for c in wanted]


SPLIT_SEED = 2026      # seed 7 was used while exploring feature sets; not reported
SPLIT_LICENCES = 600


def training_split():
    """The one population and 60/20/20 split that both the trainer and the
    evaluation use, so the shipped model is exactly the evaluated one and
    the thresholds chosen on validation apply to it as they are."""
    from sklearn.model_selection import train_test_split
    X_all, y, pats, seats, names = population(SPLIT_LICENCES, seed=SPLIT_SEED)
    idx = np.arange(len(y))
    tr, rest = train_test_split(idx, test_size=0.4, stratify=pats, random_state=SPLIT_SEED)
    va, te = train_test_split(rest, test_size=0.5, stratify=pats[rest], random_state=SPLIT_SEED)
    return X_all, y, pats, names, tr, va, te

