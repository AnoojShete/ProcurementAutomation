"""Generates data/synthetic-sso-logs/sso_login_events.json — the login
history of the five demo licences (scripts/seed-demo-data.sh seeds them with
these app names and seat counts).

Each licence gets a known usage pattern from the same simulator the anomaly
model is trained and evaluated on (ml/usage_population.py), so what the
licence page shows can be checked against what was generated:

  Microsoft 365 E3             steady            → normal
  Slack Enterprise             steady            → normal
  JetBrains All Products Pack  weekend_dip       → normal (developers off at weekends)
  Docker Pro                   sudden_dropoff    → anomalous
  Notion Team                  gradual_decline   → anomalous

The data ends on a fixed date (a snapshot); the scanner scores it relative to
its latest event, not today's date.

Run from the service root:  python scripts/generate_sso_logs.py
"""
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "ml"))
from usage_population import simulate  # noqa: E402

END = datetime(2026, 10, 15, 23, 59, tzinfo=timezone.utc)
SEED = 42
DEMO_LICENCES = [  # (app_name, seats as seeded, pattern)
    ("Microsoft 365 E3", 50, "steady"),
    ("Slack Enterprise", 45, "steady"),
    ("JetBrains All Products Pack", 120, "weekend_dip"),
    ("Docker Pro", 60, "sudden_dropoff"),
    ("Notion Team", 200, "gradual_decline"),
]


def generate_sso_logs() -> str:
    rng = np.random.default_rng(SEED)
    logs = []
    for app, seats, pattern in DEMO_LICENCES:
        logs += simulate(rng, app, pattern, seats, END)
    logs.sort(key=lambda e: e["login_timestamp"])
    out_dir = os.path.join(_HERE, "..", "..", "..", "data", "synthetic-sso-logs")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "sso_login_events.json")
    with open(path, "w") as f:
        json.dump(logs, f, separators=(",", ":"))
    print(f"Generated {len(logs)} SSO login events to {path}")
    for app, seats, pattern in DEMO_LICENCES:
        print(f"  {app:30s} {seats:4d} seats  {pattern:16s} {sum(1 for e in logs if e['app_name'] == app):6d} events")
    return path


if __name__ == "__main__":
    generate_sso_logs()
