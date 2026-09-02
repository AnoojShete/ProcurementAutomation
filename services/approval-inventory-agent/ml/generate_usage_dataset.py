#!/usr/bin/env python3
"""
Feature engineering for the usage anomaly model.

Reads data/synthetic-sso-logs/sso_login_events.json, aggregates it into
per-license daily login counts, and engineers the 9-feature vector that
the IsolationForest is trained on.

Features (per license, computed over the last 90 days):

  Feature                  Description
  ────────────────────────────────────────────────────────────────
  active_seats_7d          Distinct active users in last 7 days
  active_seats_30d         Distinct active users in last 30 days
  active_seats_90d         Distinct active users in last 90 days
  utilisation_ratio        active_seats_30d / total_seats
  dod_rate_change          Mean day-over-day delta in daily login count (30-day window)
  wow_rate_change          Mean week-over-week delta in weekly totals (90-day window)
  variance_daily_logins    Variance of daily login count over 90 days
  days_since_last_login    Days since any seat last logged in
  weekend_ratio            Fraction of all logins that fell on Sat/Sun
                           (captured so the model learns this is normal for
                           seasonal/weekend-dip licenses)

Run:
  python ml/generate_usage_dataset.py
Writes:
  ml/artifacts/usage_features.csv
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

# ── Path setup ────────────────────────────────────────────────────────────────
# This script lives at services/approval-inventory-agent/ml/
# Repo root is 3 levels up.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.join(_HERE, "..", "..", "..")
SSO_LOG_PATH = os.path.join(
    _REPO_ROOT, "data", "synthetic-sso-logs", "sso_login_events.json"
)
ARTIFACT_DIR = os.path.join(_HERE, "artifacts")
OUT_CSV = os.path.join(ARTIFACT_DIR, "usage_features.csv")

FEATURE_COLUMNS = [
    "active_seats_7d",
    "active_seats_30d",
    "active_seats_90d",
    "utilisation_ratio",
    "dod_rate_change",
    "wow_rate_change",
    "variance_daily_logins",
    "days_since_last_login",
    "weekend_ratio",
]

# total_seats per app_name — mirrors the licence catalogue in generate_sso_logs.py
TOTAL_SEATS: dict[str, int] = {
    "Microsoft 365 E3": 80,
    "Slack Business+": 120,
    "Zoom Pro": 60,
    "Salesforce Starter": 40,
    "Adobe Creative Cloud": 30,
    "Jira Software": 50,
    "GitHub Enterprise": 70,
    "Figma Professional": 25,
}


def _parse_ts(ts_raw: str) -> datetime:
    dt = datetime.fromisoformat(ts_raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _weekend(d: datetime) -> bool:
    return d.weekday() >= 5


def build_features(
    sso_events: list[dict],
    now: datetime | None = None,
    total_seats_override: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Engineer the feature matrix from raw SSO events.

    Args:
        sso_events: List of {app_name, user_email, login_timestamp} dicts.
        now: Reference timestamp (defaults to UTC now). Override in tests for
             deterministic window boundaries.
        total_seats_override: Map of app_name → total_seats; falls back to the
             module-level TOTAL_SEATS dict. Useful in tests.

    Returns:
        DataFrame with one row per app_name and columns = FEATURE_COLUMNS + ['app_name'].
    """
    if now is None:
        now = datetime.now(timezone.utc)
    seats_map = total_seats_override if total_seats_override else TOTAL_SEATS

    cutoff_7d  = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)
    cutoff_90d = now - timedelta(days=90)

    # Group events by app_name
    by_app: dict[str, list[dict]] = defaultdict(list)
    for ev in sso_events:
        app = ev.get("app_name")
        if app:
            by_app[app].append(ev)

    rows = []
    for app_name, events in by_app.items():
        # Parse timestamps
        parsed = []
        for ev in events:
            try:
                ts = _parse_ts(ev["login_timestamp"])
                if ts >= cutoff_90d:
                    parsed.append((ts, ev["user_email"]))
            except Exception:
                continue

        if not parsed:
            continue

        total_seats = seats_map.get(app_name, max(1, len({e for _, e in parsed})))

        # ── Active seats per window ──────────────────────────────────────
        users_7d  = {u for ts, u in parsed if ts >= cutoff_7d}
        users_30d = {u for ts, u in parsed if ts >= cutoff_30d}
        users_90d = {u for ts, u in parsed}

        active_7d  = len(users_7d)
        active_30d = len(users_30d)
        active_90d = len(users_90d)
        utilisation_ratio = active_30d / max(total_seats, 1)

        # ── Daily login count series (90-day window) ─────────────────────
        daily_counts: dict[datetime, int] = defaultdict(int)
        for ts, _ in parsed:
            day_key = ts.replace(hour=0, minute=0, second=0, microsecond=0)
            daily_counts[day_key] += 1

        # Fill zeros for days with no logins in the 90-day window
        all_days = sorted(
            {cutoff_90d + timedelta(days=i) for i in range(91)}
            | set(daily_counts.keys())
        )
        counts_series = np.array([daily_counts.get(d, 0) for d in all_days])

        variance_daily = float(np.var(counts_series)) if len(counts_series) > 1 else 0.0

        # ── Day-over-day rate of change (30-day window) ──────────────────
        recent_days = sorted(
            [d for d in daily_counts if d >= cutoff_30d] +
            [cutoff_30d + timedelta(days=i) for i in range(31)]
        )
        recent_series = np.array([daily_counts.get(d, 0) for d in sorted(set(recent_days))])
        if len(recent_series) > 1:
            dod = float(np.mean(np.diff(recent_series.astype(float))))
        else:
            dod = 0.0

        # ── Week-over-week rate of change (90-day window) ─────────────────
        weekly_totals = []
        for week_start_offset in range(0, 90, 7):
            w_start = cutoff_90d + timedelta(days=week_start_offset)
            w_end   = w_start + timedelta(days=7)
            w_total = sum(c for d, c in daily_counts.items() if w_start <= d < w_end)
            weekly_totals.append(w_total)
        if len(weekly_totals) > 1:
            wow = float(np.mean(np.diff(np.array(weekly_totals, dtype=float))))
        else:
            wow = 0.0

        # ── Days since last login ─────────────────────────────────────────
        if parsed:
            last_ts = max(ts for ts, _ in parsed)
            days_since = max(0.0, (now - last_ts).total_seconds() / 86400.0)
        else:
            days_since = 90.0

        # ── Weekend ratio ─────────────────────────────────────────────────
        total_count = len(parsed)
        weekend_count = sum(1 for ts, _ in parsed if _weekend(ts))
        weekend_ratio = weekend_count / max(total_count, 1)

        rows.append({
            "app_name": app_name,
            "active_seats_7d": active_7d,
            "active_seats_30d": active_30d,
            "active_seats_90d": active_90d,
            "utilisation_ratio": round(utilisation_ratio, 6),
            "dod_rate_change": round(dod, 6),
            "wow_rate_change": round(wow, 6),
            "variance_daily_logins": round(variance_daily, 6),
            "days_since_last_login": round(days_since, 4),
            "weekend_ratio": round(weekend_ratio, 6),
        })

    df = pd.DataFrame(rows, columns=["app_name"] + FEATURE_COLUMNS)
    return df


def main():
    if not os.path.exists(SSO_LOG_PATH):
        print(
            f"SSO log not found at {SSO_LOG_PATH}.\n"
            "Run: python scripts/generate_sso_logs.py"
        )
        sys.exit(1)

    with open(SSO_LOG_PATH) as f:
        sso_events = json.load(f)
    print(f"Loaded {len(sso_events):,} SSO events")

    df = build_features(sso_events)
    print(f"Engineered features for {len(df)} licenses:\n{df[['app_name'] + FEATURE_COLUMNS].to_string(index=False)}")

    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")


if __name__ == "__main__":
    main()
