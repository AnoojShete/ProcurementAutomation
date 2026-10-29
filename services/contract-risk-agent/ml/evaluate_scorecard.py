"""How well does the shipped deterministic scorecard rank vendors by
incident risk? (FR-04, merge review G10)

Uses the synthetic vendor dataset and the test split the retired Random
Forest was evaluated on (ml/archive/), so the numbers compare directly:
each test vendor's six features are turned into scorecard observations and
scored by the real engine (`evaluate_risk`, default ruleset); the points are
compared with the synthetic incident label.

    tenure             -> company age (years since incorporation)
    on-time rate       -> delivery SLA (20 orders delivered)
    financial score    -> financial standing (score basis)
    breaches (5 y)     -> breach history (not within the last 12 months)
    security cert      -> certification (required; valid or none)
    geographic risk    -> jurisdiction (high-risk country, else domestic)
    identity checks    -> clear (the dataset has none: sanctions, GSTIN, bank)

    python ml/evaluate_scorecard.py    # writes docs/results/risk-scorecard-eval.json

The label is synthetic (a weighted rule plus noise), so this measures how
closely the ruleset follows that rule, not real-world incident prediction.
"""
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "archive"))
sys.path.insert(0, os.path.dirname(HERE))

import pandas as pd  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from generate_vendor_dataset import FEATURE_COLUMNS, LABEL_COLUMN, OUT_CSV, build_dataset, risk_probability  # noqa: E402
from app.services.scorecard.default_ruleset import get_default_ruleset  # noqa: E402
from app.services.scorecard.engine import evaluate_risk  # noqa: E402

NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)
RF_ROC_AUC = 0.715          # docs/results/risk-model.json (archived Random Forest, same split)


def split(df: pd.DataFrame):
    """The archived model's split (train_risk_model.split): stratified 80/20, seed 42."""
    from sklearn.model_selection import train_test_split
    return train_test_split(df[FEATURE_COLUMNS], df[LABEL_COLUMN], test_size=0.2, random_state=42,
                            stratify=df[LABEL_COLUMN])


def observations(row) -> dict:
    clear = {
        "sanctions": {"sanctions.status": "no_match"},
        "gst": {"gstin.status": "active", "gstin.verification_level": "live", "gstin.name_match_level": "exact"},
        "bank": {"bank.status": "valid"},
        "web": {"web.ssl_grade": "A"},
        "email": {"email.dmarc_policy": "reject", "email.spf_present": True},
        "feedback": {"fbk.count_12m": 0},
        "incidents": {"inc.history_available": False},
        "adverse_media": {"media.qualifying_articles": 0},
    }
    clear.update({
        "company_age": {"age.basis": "incorporation", "age.years": float(row.vendor_tenure_months) / 12},
        "delivery_sla": {"sla.orders_delivered": 20, "sla.on_time_pct": float(row.on_time_delivery_rate) * 100},
        "financial": {"fin.basis": "score", "fin.score": float(row.financial_stability_score)},
        "breach": {"breach.catalogue_loaded": True, "breach.count_5y": int(row.breach_disclosure_count), "breach.latest_within_12m": False},
        "certification": {"cert.required": True, "cert.status": "valid" if row.security_cert_flag else "none"},
        "jurisdiction": ({"country.is_domestic": False, "country.high_risk": True} if row.geo_risk_flag
                         else {"country.is_domestic": True}),
    })
    return {k: {"signal_key": k, "status": "ok", "fields": v, "fetched_at": NOW.isoformat()} for k, v in clear.items()}


def evaluate() -> dict:
    if os.path.exists(OUT_CSV):
        df = pd.read_csv(OUT_CSV)
        if len(df) < 2000:
            df = build_dataset()
    else:
        df = build_dataset()
    _, X_test, _, y_test = split(df)
    ruleset = get_default_ruleset()
    points, bands = [], []
    for row in X_test.itertuples(index=False):
        r = evaluate_risk(ruleset, observations(row), NOW, vendor_context={"spend_tier": "standard", "country": "IN"})
        points.append(r["total_points"])
        bands.append(r["final_band"])
    labels = list(y_test)
    table = []
    for band in ("Low", "Medium", "High"):
        idx = [i for i, b in enumerate(bands) if b == band]
        incidents = sum(labels[i] for i in idx)
        table.append({"band": band, "vendors": len(idx), "incidents": int(incidents),
                      "incident_rate": round(incidents / len(idx), 3) if idx else None})
    return {
        "dataset": {"vendors": len(df), "test_vendors": len(X_test), "incident_rate": round(float(df[LABEL_COLUMN].mean()), 3),
                    "label": "synthetic: weighted rule over the six features plus noise (ml/archive/generate_vendor_dataset.py)"},
        "roc_auc_scorecard_points": round(float(roc_auc_score(labels, points)), 3),
        "roc_auc_random_forest_archived": RF_ROC_AUC,
        "roc_auc_ceiling_label_rule": round(float(roc_auc_score(labels, risk_probability(X_test))), 3),
        "bands": table,
        "points": {"min": min(points), "max": max(points), "mean": round(sum(points) / len(points), 1)},
        "run_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    result = evaluate()
    print(json.dumps(result, indent=2))
    root = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    out = os.path.join(root, "docs", "results", "risk-scorecard-eval.json")
    if os.path.isdir(os.path.dirname(out)):
        with open(out, "w") as f:
            json.dump(result, f, indent=2)
        print("-> docs/results/risk-scorecard-eval.json")


if __name__ == "__main__":
    main()
