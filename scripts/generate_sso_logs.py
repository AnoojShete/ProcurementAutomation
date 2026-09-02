#!/usr/bin/env python3
"""
Synthetic SSO login event generator for the Approval & Inventory Intelligence Agent.

Produces 60–90 days of per-seat, per-day SSO login events for a configurable set
of software licenses. Each license is assigned one of four usage patterns so the
downstream IsolationForest model has a realistic inlier/outlier distribution to
learn from:

  Pattern                 | What it looks like in the data
  ────────────────────────┼────────────────────────────────────────────────────
  normal_steady           | Consistent weekday logins, predictable weekend dip
  gradual_decline         | Slow linear drop from ~80 % to ~10 % utilisation
  sudden_drop_off         | Normal usage then near-zero for the last ~30 days
  seasonal_weekend_dip    | Stable weekday, explicit weekend quiet — NOT an anomaly

See data/synthetic-sso-logs/README.md for the full spec.

Run:
  python scripts/generate_sso_logs.py
Writes:
  data/synthetic-sso-logs/sso_login_events.json
  (same path consumed by app/usage_scanner.py)

All randomness is seeded (SEED = 42) so the output is fully reproducible.
"""
import json
import os
import random
from datetime import datetime, timedelta, timezone

# ── Config ─────────────────────────────────────────────────────────────────────

SEED = 42
# Reference point: treat "now" as the current UTC day at midnight so that
# the generated timestamps always land inside the 30/60/90-day windows relative
# to whenever the scanner runs.
NOW = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

# Output path — this script lives at scripts/, repo root is one level up.
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT_PATH = os.path.join(
    _REPO_ROOT, "data", "synthetic-sso-logs", "sso_login_events.json"
)

# ── License catalogue ──────────────────────────────────────────────────────────
# Each entry maps to exactly one usage pattern.
# total_seats must match (or be set in) the licenses DB table for meaningful
# utilisation ratios. These are illustrative defaults.

LICENSES = [
    # ── normal_steady ──────────────────────────────────────────────────────
    {
        "app_name": "Microsoft 365 E3",
        "total_seats": 80,
        "active_seats": 65,   # seats that actually log in regularly
        "pattern": "normal_steady",
        "history_days": 90,
    },
    {
        "app_name": "Slack Business+",
        "total_seats": 120,
        "active_seats": 95,
        "pattern": "normal_steady",
        "history_days": 75,
    },
    # ── gradual_decline ────────────────────────────────────────────────────
    {
        "app_name": "Zoom Pro",
        "total_seats": 60,
        "active_seats": 50,   # starts here; declines to ~10 % by day 90
        "pattern": "gradual_decline",
        "history_days": 90,
    },
    {
        "app_name": "Salesforce Starter",
        "total_seats": 40,
        "active_seats": 35,
        "pattern": "gradual_decline",
        "history_days": 80,
    },
    # ── sudden_drop_off ────────────────────────────────────────────────────
    {
        "app_name": "Adobe Creative Cloud",
        "total_seats": 30,
        "active_seats": 25,
        "pattern": "sudden_drop_off",
        "history_days": 90,
        "drop_day": 62,       # days-ago when the drop started (≈ 30 d before now)
    },
    {
        "app_name": "Jira Software",
        "total_seats": 50,
        "active_seats": 45,
        "pattern": "sudden_drop_off",
        "history_days": 85,
        "drop_day": 55,
    },
    # ── seasonal_weekend_dip ───────────────────────────────────────────────
    # Weekend quiet is EXPECTED behaviour — the model must NOT flag these.
    {
        "app_name": "GitHub Enterprise",
        "total_seats": 70,
        "active_seats": 60,
        "pattern": "seasonal_weekend_dip",
        "history_days": 90,
    },
    {
        "app_name": "Figma Professional",
        "total_seats": 25,
        "active_seats": 20,
        "pattern": "seasonal_weekend_dip",
        "history_days": 70,
    },
]


# ── Per-day login count helpers ───────────────────────────────────────────────

def _weekend(d: datetime) -> bool:
    """Return True for Saturday (5) or Sunday (6)."""
    return d.weekday() >= 5


def _day_login_count_normal_steady(
    day: datetime,
    active_seats: int,
    rng: random.Random,
) -> int:
    """Consistent usage: weekday ≈ 80-95 % of active seats, weekend ≈ 15-30 %."""
    if _weekend(day):
        base_frac = rng.uniform(0.15, 0.30)
    else:
        base_frac = rng.uniform(0.80, 0.95)
    return max(0, int(active_seats * base_frac))


def _day_login_count_gradual_decline(
    day: datetime,
    active_seats: int,
    days_ago: int,
    history_days: int,
    rng: random.Random,
) -> int:
    """Linear decay from ~80 % at history_days-ago to ~10 % today.

    days_ago=history_days → oldest point (highest usage).
    days_ago=0            → most recent day (lowest usage).
    """
    # frac goes from 0.80 → 0.10 linearly
    frac = 0.80 - 0.70 * (history_days - days_ago) / max(history_days, 1)
    frac = max(0.05, frac)
    if _weekend(day):
        frac *= rng.uniform(0.20, 0.40)
    noise = rng.uniform(-0.05, 0.05)
    return max(0, int(active_seats * (frac + noise)))


def _day_login_count_sudden_drop_off(
    day: datetime,
    active_seats: int,
    days_ago: int,
    drop_day: int,
    rng: random.Random,
) -> int:
    """Normal usage before drop_day (days-ago), near-zero after.

    drop_day=62 means the cliff was 62 days ago; days 62-90 look fine,
    days 0-61 are nearly empty.
    """
    if days_ago > drop_day:
        # Before the drop → normal weekday/weekend pattern
        if _weekend(day):
            frac = rng.uniform(0.15, 0.30)
        else:
            frac = rng.uniform(0.75, 0.95)
    else:
        # After the drop → near-zero (0-5 % residual)
        frac = rng.uniform(0.00, 0.05)
    return max(0, int(active_seats * frac))


def _day_login_count_seasonal_weekend_dip(
    day: datetime,
    active_seats: int,
    rng: random.Random,
) -> int:
    """Strong stable weekday usage, explicit weekend dip — intentional seasonal pattern.

    This pattern is structurally identical to normal_steady but the test suite
    explicitly checks that the model does NOT flag it as anomalous, proving the
    model has learned that weekend dips are normal.
    """
    if _weekend(day):
        # Deliberately lower — this IS the expected seasonal pattern
        frac = rng.uniform(0.10, 0.20)
    else:
        frac = rng.uniform(0.82, 0.97)
    return max(0, int(active_seats * frac))


# ── Event generator ────────────────────────────────────────────────────────────

def _generate_events_for_license(
    license_cfg: dict,
    rng: random.Random,
) -> list[dict]:
    """Generate one SSO login event per seat per login-day for a single license."""
    events = []
    app_name = license_cfg["app_name"]
    active_seats = license_cfg["active_seats"]
    pattern = license_cfg["pattern"]
    history_days = license_cfg["history_days"]
    drop_day = license_cfg.get("drop_day", 30)  # only used by sudden_drop_off

    # Stable pool of user emails for this license
    users = [f"user{i:03d}@example.com" for i in range(1, active_seats + 1)]

    for days_ago in range(history_days, 0, -1):
        day = NOW - timedelta(days=days_ago)

        # How many seats log in today?
        if pattern == "normal_steady":
            n_logins = _day_login_count_normal_steady(day, active_seats, rng)
        elif pattern == "gradual_decline":
            n_logins = _day_login_count_gradual_decline(
                day, active_seats, days_ago, history_days, rng
            )
        elif pattern == "sudden_drop_off":
            n_logins = _day_login_count_sudden_drop_off(
                day, active_seats, days_ago, drop_day, rng
            )
        elif pattern == "seasonal_weekend_dip":
            n_logins = _day_login_count_seasonal_weekend_dip(day, active_seats, rng)
        else:
            raise ValueError(f"Unknown pattern: {pattern}")

        # Pick which users log in today (random sample)
        n_logins = min(n_logins, len(users))
        if n_logins == 0:
            continue
        day_users = rng.sample(users, n_logins)

        for user_email in day_users:
            # Random time during work hours for weekdays, any time for weekends
            if _weekend(day):
                hour = rng.randint(8, 22)
            else:
                hour = rng.randint(8, 19)
            minute = rng.randint(0, 59)
            second = rng.randint(0, 59)
            login_ts = day.replace(
                hour=hour, minute=minute, second=second, microsecond=0
            )
            events.append({
                "app_name": app_name,
                "user_email": user_email,
                "login_timestamp": login_ts.isoformat(),
            })

    return events


# ── Main ───────────────────────────────────────────────────────────────────────

def generate(out_path: str = OUT_PATH) -> list[dict]:
    """Generate all SSO events across all licenses and write to JSON.

    Returns the full list for testing/import without touching the filesystem
    when out_path is None.
    """
    rng = random.Random(SEED)

    all_events: list[dict] = []
    for lic in LICENSES:
        events = _generate_events_for_license(lic, rng)
        all_events.append(events)
        print(
            f"  {lic['app_name']:30s} pattern={lic['pattern']:22s} "
            f"events={len(events):6,d}"
        )

    # Flatten
    flat: list[dict] = [ev for batch in all_events for ev in batch]

    # Sort chronologically (makes the file readable; scanner handles any order)
    flat.sort(key=lambda e: e["login_timestamp"])

    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(flat, f, indent=2)
        print(f"\nWrote {len(flat):,} events to {out_path}")

    return flat


if __name__ == "__main__":
    print("Generating synthetic SSO login events…\n")
    generate()
