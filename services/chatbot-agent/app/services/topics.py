"""Answers built from live platform data for questions the index can't
answer well on its own.

Licence usage anomalies: the anomaly score of each licence is computed by
approval-inventory-agent from the SSO usage log when asked (IsolationForest,
explained with SHAP); it isn't stored, so a passage in the index could only
say "not scored yet", and retrieval used to return the threshold rule
instead ("Current value: 0.39"). This module asks the approval agent, with
the user's own token, for the summary and each licence's score, and writes an
answer that says how detection works, the live thresholds, which licences
are flagged or closest to the line, and what to do next.
"""
import logging
from typing import Optional

import httpx
from sqlalchemy import text

from app.config import settings
from shared.auth.jwt_tokens import create_access_token
from shared.auth.middleware import CurrentUser

logger = logging.getLogger(__name__)
STAFF = ("approver", "finance", "admin", "service")
FACTOR_WORDS = {
    "utilisation_90d": "low use over 90 days", "utilisation_30d": "low use over 30 days",
    "trend_slope": "usage falling", "retention_7d": "users not coming back within a week",
    "weekend_ratio": "unusual weekday/weekend pattern", "active_ratio": "few active seats",
}


async def _rules(db) -> dict:
    rows = (await db.execute(text(
        "SELECT rule_key, current_value FROM business_rules WHERE rule_key IN "
        "('license.anomaly_anomalous_threshold', 'license.anomaly_watch_threshold', 'license.grace_period_days', "
        "'license.reclaim_cooldown_days')"))).all()
    return {r[0]: r[1] for r in rows}


async def _licences(db) -> list:
    return (await db.execute(text(
        "SELECT id, app_name, total_seats, assigned_seats, cost_per_seat FROM licenses ORDER BY app_name"))).all()


async def _scores(user: CurrentUser, licence_ids: list[str]) -> tuple[Optional[dict], dict]:
    """(summary, {licence_id: usage_anomaly}) from approval-inventory-agent."""
    token = create_access_token(user_id=user.id, email=user.email, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}
    base = settings.orders_api_base_url.rstrip("/")
    summary, scores = None, {}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{base}/licenses/anomaly-summary", headers=headers)
        if r.status_code == 200:
            summary = r.json().get("data")
        for lid in licence_ids[:40]:
            r = await client.get(f"{base}/licenses/{lid}/usage-anomaly", headers=headers)
            if r.status_code == 200:
                scores[lid] = (r.json().get("data") or {}).get("usage_anomaly") or {}
    return summary, scores


def _status(score: Optional[float], watch: float, anomalous: float) -> str:
    if score is None:
        return "not enough history"
    return "anomalous" if score >= anomalous else "watch" if score >= watch else "normal"


def licence_anomaly_answer(licences: list, scores: dict, rules: dict, summary: Optional[dict]) -> str:
    """Pure: the answer text from the data (tested on its own)."""
    anomalous = float(rules.get("license.anomaly_anomalous_threshold", 0.39))
    watch = float(rules.get("license.anomaly_watch_threshold", 0.34))
    grace = rules.get("license.grace_period_days", 7)
    rows = []
    for l in licences:
        s = scores.get(str(l.id)) or {}
        score = s.get("anomaly_score")
        factor = next((f for f in s.get("top_factors") or [] if f.get("direction") == "increasing_risk"), None)
        rows.append({"name": l.app_name, "score": score, "status": _status(score, watch, anomalous),
                     "active": s.get("active_seats_30d"), "seats": l.total_seats or s.get("total_seats"),
                     "assigned": l.assigned_seats, "cost": float(l.cost_per_seat or 0),
                     "factor": FACTOR_WORDS.get(factor["feature"], factor["feature"].replace("_", " ")) if factor else None})
    flagged = [r for r in rows if r["status"] == "anomalous"]
    watching = [r for r in rows if r["status"] == "watch"]
    scored = sorted([r for r in rows if r["score"] is not None], key=lambda r: -r["score"])

    def line(r):
        use = f"{r['active']} of {r['seats']} seats active in the last 30 days" if r["active"] is not None else \
            f"{r['assigned']} of {r['seats']} seats assigned"
        why = f"; main signal: {r['factor']}" if r["factor"] else ""
        return f"- {r['name']}: score {r['score']:.2f} ({r['status']}), {use}{why}"

    if not licences:
        return "There are no software licences on the platform yet, so there is nothing to check for anomalies."
    if flagged:
        head = (f"Yes: {len(flagged)} of {len(rows)} licences show a usage anomaly (score at or above {anomalous:g}):\n"
                + "\n".join(line(r) for r in flagged))
    else:
        head = f"No: none of the {len(rows)} licences is anomalous right now (no score at or above {anomalous:g})."
        if watching:
            head += f" {len(watching)} {'is' if len(watching) == 1 else 'are'} on the watch list ({watch:g} to {anomalous:g}):\n" \
                    + "\n".join(line(r) for r in watching)
        elif scored:
            head += " Closest to the line:\n" + "\n".join(line(r) for r in scored[:3])
    how = (f"How it's detected: each licence's daily sign-ins from the SSO log are scored by an anomaly model "
           f"(Isolation Forest) on utilisation, trend and retention; the main factors are explained per licence. "
           f"A score of {anomalous:g} or more is anomalous and {watch:g} or more is on watch (business rules "
           f"“Anomalous threshold” and “Watch threshold”).")
    if flagged:
        nxt = (f"What to do: open each flagged licence on the Licences page, check the usage trend and its reasons, "
               f"then confirm or dismiss the reclaim request the platform raised; seats are reclaimed after a "
               f"{grace}-day grace period.")
    else:
        spare = [f"{r['name']} ({(r['seats'] or 0) - (r['assigned'] or 0)} unassigned)" for r in rows
                 if (r["seats"] or 0) - (r["assigned"] or 0) > 0]
        nxt = "What to do: nothing is needed now." + (
            f" Unassigned seats are still worth a look on the Licences page: {', '.join(spare[:5])}." if spare else "")
    if summary and summary.get("potential_annual_savings"):
        nxt += f" Potential saving if flagged seats are reclaimed: INR {summary['potential_annual_savings']:,.0f} a year."
    return f"{head}\n\n{how}\n\n{nxt}"


async def answer_licence_anomalies(db, user: CurrentUser) -> str:
    if user.role not in STAFF:
        return ("Licence usage and anomalies are visible to approvers, finance and admins. I can help with your own "
                "purchase requests, vendors or contract terms instead.")
    licences = await _licences(db)
    try:
        summary, scores = await _scores(user, [str(l.id) for l in licences])
    except httpx.HTTPError as e:
        logger.warning(f"licence anomaly lookup failed: {e}")
        return "I couldn't reach the licence usage service just now, so I can't say which licences are anomalous."
    return licence_anomaly_answer(licences, scores, await _rules(db), summary)
