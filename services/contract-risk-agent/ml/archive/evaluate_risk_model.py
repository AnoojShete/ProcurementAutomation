#!/usr/bin/env python3
"""Evaluates the vendor risk model and writes the results (FR-04).

Run inside the contract-risk-agent image, from /app:
  python ml/evaluate_risk_model.py --out /out
Writes <out>/risk-model.json and <out>/risk-model.html: dataset size and
class balance, how labels are made, accuracy / ROC-AUC (complete and with
missing values), incident rate per band, feature importances, and the
red-team profiles (ml/redteam_profiles.json) against their expected bands.

Uses the same split, training procedure and band thresholds as the
service (train_risk_model.split/fit, risk_service.assess), seeded, so the
numbers are reproducible.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, roc_auc_score

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # /app, for app.services.risk_service

from generate_vendor_dataset import (  # noqa: E402
    FEATURE_COLUMNS, KAGGLE_CSV, LABEL_COLUMN, N_SYNTHETIC, OUT_CSV, STRESSED_SHARE, build_dataset, risk_probability,
)
from train_risk_model import MISSING_RATE, MODEL_PARAMS, fit, split, with_missing  # noqa: E402
from app.services.risk_service import _band_for_score, assess, hard_override_checks  # noqa: E402

BANDS = ["Low", "Medium", "High"]


def band_table(scores, labels) -> list[dict]:
    rows = []
    bands = [_band_for_score(s) for s in scores]
    for b in BANDS:
        idx = [i for i, x in enumerate(bands) if x == b]
        incidents = int(sum(labels[i] for i in idx))
        rows.append({"band": b, "vendors": len(idx), "incidents": incidents,
                     "incident_rate": round(incidents / len(idx), 3) if idx else None})
    return rows


def run_redteam(model) -> list[dict]:
    with open(os.path.join(HERE, "redteam_profiles.json")) as f:
        profiles = json.load(f)["profiles"]
    out = []
    for p in profiles:
        r = assess(model, FEATURE_COLUMNS, p["features"], hard_override_checks(p.get("gstin_status")))
        if "expected" in p:
            ok, expectation = r["band"] == p["expected"], p["expected"]
        else:
            ok, expectation = r["band"] != p["expected_not"], f"not {p['expected_not']}"
        out.append({"name": p["name"], "expected": expectation, "band": r["band"], "score": round(r["score"], 3),
                    "signals": f"{r['signals_used']}/{r['signals_total']}", "pass": ok,
                    "top_factor": r["top_factors"][0]["feature"] if r["top_factors"] else None})
    return out


def evaluate() -> dict:
    df = pd.read_csv(OUT_CSV) if os.path.exists(OUT_CSV) else build_dataset()
    X_train, X_test, y_train, y_test = split(df)
    model = fit(X_train, y_train)

    proba = model.predict_proba(X_test.astype(float))[:, 1]
    preds = (proba >= 0.5).astype(int)
    proba_missing = model.predict_proba(with_missing(X_test, seed=11))[:, 1]
    cm = confusion_matrix(y_test, preds, labels=[0, 1])

    importances = sorted(
        ({"feature": f, "importance": round(float(i), 3)} for f, i in zip(FEATURE_COLUMNS, model.feature_importances_)),
        key=lambda r: r["importance"], reverse=True,
    )
    redteam = run_redteam(model)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {
            "rows": int(len(df)),
            "source": "Kaggle procurement KPI + synthetic supplement" if os.path.exists(KAGGLE_CSV)
            else f"fully synthetic, seeded, {STRESSED_SHARE:.0%} stressed-vendor segment",
            "features": FEATURE_COLUMNS,
            "label": LABEL_COLUMN,
            "incidents": int(df[LABEL_COLUMN].sum()),
            "incident_share": round(float(df[LABEL_COLUMN].mean()), 3),
            "label_rule": (
                "risk = 0.35·(1−on-time) + 0.25·(1−financial) + 0.25·min(breaches/6, 1) + 0.10·geo flag "
                "− 0.10·certified − 0.10·min(tenure/120, 1), plus N(0, 0.08) noise; incident drawn with that probability"
            ),
            "train_rows": int(len(X_train)), "test_rows": int(len(X_test)),
        },
        "model": {"type": "RandomForestClassifier", **{k: v for k, v in MODEL_PARAMS.items() if k != "random_state"},
                  "missing_rate_in_training": MISSING_RATE,
                  "bands": "Low ≤ 0.33 < Medium ≤ 0.66 < High (config.yaml risk_model.bands)"},
        "metrics": {
            "accuracy": round(float(accuracy_score(y_test, preds)), 3),
            "roc_auc": round(float(roc_auc_score(y_test, proba)), 3),
            "roc_auc_with_20pct_missing": round(float(roc_auc_score(y_test, proba_missing)), 3),
            # The labels are drawn at random from the rule's probability, so
            # even that probability can't separate them perfectly.
            "roc_auc_ceiling_label_rule": round(float(roc_auc_score(y_test, risk_probability(X_test))), 3),
            "confusion_matrix_at_0_5": {"true_negative": int(cm[0][0]), "false_positive": int(cm[0][1]),
                                        "false_negative": int(cm[1][0]), "true_positive": int(cm[1][1])},
        },
        "per_band_test_set": band_table(proba, list(y_test)),
        "feature_importances": importances,
        "redteam": {"passed": sum(r["pass"] for r in redteam), "total": len(redteam), "profiles": redteam},
    }


def to_markdown(r: dict) -> str:
    d, m = r["dataset"], r["metrics"]
    cm = m["confusion_matrix_at_0_5"]
    lines = [
        "# Vendor risk model — evaluation", "",
        f"Generated {r['generated_at']} by `services/contract-risk-agent/ml/evaluate_risk_model.py`.", "",
        "## Dataset", "",
        f"- {d['rows']} vendors ({d['source']}); train {d['train_rows']} / test {d['test_rows']}, stratified.",
        f"- {d['incidents']} with an incident ({d['incident_share']:.1%}).",
        f"- Label: {d['label_rule']}.",
        f"- Features: {', '.join(d['features'])}.", "",
        "## Results (test set)", "",
        "| Metric | Value |", "|---|---|",
        f"| Accuracy (threshold 0.5) | {m['accuracy']} |",
        f"| ROC-AUC | {m['roc_auc']} |",
        f"| ROC-AUC with 20% of values missing | {m['roc_auc_with_20pct_missing']} |",
        f"| ROC-AUC ceiling (the label rule's own probability) | {m['roc_auc_ceiling_label_rule']} |", "",
        "| | Predicted no incident | Predicted incident |", "|---|---|---|",
        f"| Actual no incident | {cm['true_negative']} | {cm['false_positive']} |",
        f"| Actual incident | {cm['false_negative']} | {cm['true_positive']} |", "",
        "### Incident rate per band", "",
        "| Band | Vendors | Incidents | Incident rate |", "|---|---|---|---|",
        *[f"| {b['band']} | {b['vendors']} | {b['incidents']} | {b['incident_rate'] if b['incident_rate'] is not None else '—'} |"
          for b in r["per_band_test_set"]], "",
        "### Feature importances", "",
        "| Feature | Importance |", "|---|---|",
        *[f"| {f['feature']} | {f['importance']} |" for f in r["feature_importances"]], "",
        f"## Red-team profiles ({r['redteam']['passed']}/{r['redteam']['total']} as expected)", "",
        "| Profile | Expected | Band | Score | Signals | Top factor | OK |", "|---|---|---|---|---|---|---|",
        *[f"| {p['name']} | {p['expected']} | {p['band']} | {p['score']} | {p['signals']} | {p['top_factor'] or '—'} | {'✓' if p['pass'] else '✗'} |"
          for p in r["redteam"]["profiles"]], "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "..", "results"))
    out = ap.parse_args().out
    os.makedirs(out, exist_ok=True)
    result = evaluate()
    with open(os.path.join(out, "risk-model.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out, "risk-model.html"), "w") as f:
        f.write(to_markdown(result))
    print(json.dumps({k: result[k] for k in ("metrics", "per_band_test_set")}, indent=2))
    print(f"red-team: {result['redteam']['passed']}/{result['redteam']['total']}")
    for p in result["redteam"]["profiles"]:
        if not p["pass"]:
            print(f"  ✗ {p['name']}: expected {p['expected']}, got {p['band']} ({p['score']})")


if __name__ == "__main__":
    main()
