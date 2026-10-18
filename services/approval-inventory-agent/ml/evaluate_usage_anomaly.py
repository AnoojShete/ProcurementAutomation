#!/usr/bin/env python3
"""Evaluates the licence-usage anomaly model (FR-32) and picks its thresholds.

A seeded population of simulated licences with known patterns
(ml/usage_population.py) is split 60 / 20 / 20 into train / validation /
test. The IsolationForest is trained exactly like the production model
(train_usage_anomaly_model.py), scores are normalised the same way, and:

  - validation picks the thresholds:
      anomalous = lowest score where precision >= 0.90 (reclaim is proposed)
      watch     = highest score where recall >= 0.90  (shown for review)
  - test reports ROC-AUC, average precision, precision/recall at those
    thresholds, detection per pattern, and two baselines:
      * the old training set size — the same model fitted on 5 licences
      * a plain utilisation rule — score = 1 - utilisation_ratio

Run inside the approval-inventory-agent image, from /app:
    python ml/evaluate_usage_anomaly.py --out /out
Writes licence-anomaly.json and licence-anomaly.md.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from usage_population import FEATURE_SETS, FEATURES, MIX, PATTERNS, SPLIT_LICENCES, SPLIT_SEED, columns, training_split  # noqa: E402

N_LICENCES = SPLIT_LICENCES
SEED = SPLIT_SEED
N_ESTIMATORS = 200
RANDOM_STATE = 42
TARGET_PRECISION = 0.90
TARGET_RECALL = 0.90


def fit(X):
    model = IsolationForest(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=-1).fit(X)
    raw = model.score_samples(X)
    return model, float(raw.min()), float(raw.max())


def normalised(model, s_min, s_max, X):
    """Same mapping as app/ml/usage_anomaly.py: 1 = most anomalous."""
    span = max(s_max - s_min, 1e-9)
    return np.clip((s_max - model.score_samples(X)) / span, 0.0, 1.0)


def pick_thresholds(y, scores):
    precision, recall, thr = precision_recall_curve(y, scores)
    # precision/recall have one more entry than thr; entry i belongs to thr[i]
    anomalous = next((float(t) for p, t in zip(precision[:-1], thr) if p >= TARGET_PRECISION), float(thr[-1]))
    watch_candidates = [float(t) for r, t in zip(recall[:-1], thr) if r >= TARGET_RECALL]
    watch = max(watch_candidates) if watch_candidates else float(thr[0])
    watch = min(watch, anomalous - 0.01)
    return round(watch, 2), round(anomalous, 2)


def at(y, scores, t):
    flagged = scores >= t
    tp = int((flagged & (y == 1)).sum())
    fp = int((flagged & (y == 0)).sum())
    fn = int((~flagged & (y == 1)).sum())
    return {"threshold": t, "precision": round(tp / max(tp + fp, 1), 3), "recall": round(tp / max(tp + fn, 1), 3),
            "flagged": int(flagged.sum()), "true_positives": tp, "false_positives": fp, "missed": fn}


def evaluate() -> dict:
    X_all, y, pats, names, tr, va, te = training_split()

    # Pick the feature set on validation only.
    selection = {}
    for set_name, cols in FEATURE_SETS.items():
        X = X_all[:, columns(names, cols)]
        m, a, b = fit(X[tr])
        v = normalised(m, a, b, X[va])
        selection[set_name] = {"features": cols, "validation_average_precision": round(float(average_precision_score(y[va], v)), 3),
                               "validation_roc_auc": round(float(roc_auc_score(y[va], v)), 3)}
    chosen = max(selection, key=lambda k: selection[k]["validation_average_precision"])

    X = X_all[:, columns(names, FEATURE_SETS[chosen])]
    model, s_min, s_max = fit(X[tr])
    val_scores = normalised(model, s_min, s_max, X[va])
    test_scores = normalised(model, s_min, s_max, X[te])
    watch, anomalous = pick_thresholds(y[va], val_scores)

    per_pattern = {}
    for p in MIX:
        m = pats[te] == p
        if m.any():
            s = test_scores[m]
            per_pattern[p] = {"label": PATTERNS[p], "n": int(m.sum()), "mean_score": round(float(s.mean()), 3),
                              "flagged_anomalous": round(float((s >= anomalous).mean()), 3),
                              "flagged_watch_or_more": round(float((s >= watch).mean()), 3)}

    def summary(scores):
        return {"roc_auc": round(float(roc_auc_score(y[te], scores)), 3),
                "average_precision": round(float(average_precision_score(y[te], scores)), 3)}

    # Baselines on the same test set.
    X_orig = X_all[:, columns(names, FEATURE_SETS["original"])]
    m_o, a_o, b_o = fit(X_orig[tr])
    rng = np.random.default_rng(SEED)
    five = rng.choice(tr, size=5, replace=False)
    m5, a5, b5 = fit(X_orig[five])
    util = X_all[:, names.index("utilisation_ratio")]
    baselines = {
        "previous_model_5_licences_original_features": summary(normalised(m5, a5, b5, X_orig[te])),
        "original_features_trained_on_population": summary(normalised(m_o, a_o, b_o, X_orig[te])),
        "utilisation_rule": summary(1 - np.clip(util[te], 0, 1)),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "population": {"licences": N_LICENCES, "seed": SEED, "mix": MIX, "anomalous_share": round(float(y.mean()), 3),
                       "split": {"train": len(tr), "validation": len(va), "test": len(te)}},
        "feature_selection": {"chosen": chosen, "candidates": selection, "production_uses": FEATURES,
                              "production_matches_choice": FEATURES == FEATURE_SETS[chosen]},
        "thresholds": {"watch": watch, "anomalous": anomalous, "chosen_on": "validation", "rule": {
            "anomalous": f"lowest score with precision >= {TARGET_PRECISION}",
            "watch": f"highest score with recall >= {TARGET_RECALL}"}},
        "test": {"model": summary(test_scores), "at_anomalous": at(y[te], test_scores, anomalous),
                 "at_watch": at(y[te], test_scores, watch), "per_pattern": per_pattern},
        "baselines": baselines,
        "model": {"type": "IsolationForest", "n_estimators": N_ESTIMATORS, "features": FEATURE_SETS[chosen]},
    }


def to_markdown(r: dict) -> str:
    t, b, fs = r["test"], r["baselines"], r["feature_selection"]
    fsrows = "\n".join(f"| {'**' + k + '**' if k == fs['chosen'] else k} | {', '.join(v['features'])} | {v['validation_average_precision']} | {v['validation_roc_auc']} |"
                       for k, v in fs["candidates"].items())
    rows = "\n".join(f"| {p.replace('_', ' ')} | {'anomaly' if d['label'] else 'normal'} | {d['n']} | {d['mean_score']:.2f} | "
                     f"{d['flagged_watch_or_more'] * 100:.0f} % | {d['flagged_anomalous'] * 100:.0f} % |"
                     for p, d in t["per_pattern"].items())
    a, w = t["at_anomalous"], t["at_watch"]
    return f"""# Licence-usage anomaly model — evaluation

Generated {r['generated_at']} by `services/approval-inventory-agent/ml/evaluate_usage_anomaly.py`
on {r['population']['licences']} simulated licences (seed {r['population']['seed']}, {r['population']['anomalous_share'] * 100:.0f} % with an anomalous pattern;
patterns in `ml/usage_population.py`). Split {r['population']['split']['train']} / {r['population']['split']['validation']} / {r['population']['split']['test']} train / validation / test.
Synthetic data: these numbers say the model separates the simulated patterns, not how it does on a real company's logins.

## Thresholds (chosen on validation, rules `license.anomaly_*`)

| Status | Score ≥ | Chosen as | On test: precision | recall | flagged |
|---|---|---|---|---|---|
| anomalous (reclaim proposed) | **{a['threshold']}** | lowest score with precision ≥ 0.90 | {a['precision']} | {a['recall']} | {a['flagged']} ({a['false_positives']} false) |
| watch (shown for review) | **{w['threshold']}** | highest score with recall ≥ 0.90 | {w['precision']} | {w['recall']} | {w['flagged']} ({w['false_positives']} false) |

## Test set

| | ROC-AUC | Average precision |
|---|---|---|
| **This model** ({fs['chosen']} features, trained on {r['population']['split']['train']} licences) | **{t['model']['roc_auc']}** | **{t['model']['average_precision']}** |
| Original 9 features, trained on the same {r['population']['split']['train']} licences | {b['original_features_trained_on_population']['roc_auc']} | {b['original_features_trained_on_population']['average_precision']} |
| Previous model: original features, trained on 5 licences | {b['previous_model_5_licences_original_features']['roc_auc']} | {b['previous_model_5_licences_original_features']['average_precision']} |
| Low utilisation alone (1 − utilisation) | {b['utilisation_rule']['roc_auc']} | {b['utilisation_rule']['average_precision']} |

## Feature set (picked on validation by average precision)

| Set | Features | Validation AP | Validation ROC-AUC |
|---|---|---|---|
{fsrows}

## By pattern (test set)

| Pattern | Truth | Licences | Mean score | ≥ watch | ≥ anomalous |
|---|---|---|---|---|---|
{rows}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(_HERE, "artifacts"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    r = evaluate()
    json.dump(r, open(os.path.join(a.out, "licence-anomaly.json"), "w"), indent=2)
    open(os.path.join(a.out, "licence-anomaly.md"), "w").write(to_markdown(r))
    print(json.dumps({"chosen": r["feature_selection"]["chosen"], "production_matches_choice": r["feature_selection"]["production_matches_choice"],
                      "thresholds": r["thresholds"], "test": r["test"]["model"], "at_anomalous": r["test"]["at_anomalous"],
                      "at_watch": r["test"]["at_watch"], "baselines": r["baselines"]}, indent=1))


if __name__ == "__main__":
    main()
