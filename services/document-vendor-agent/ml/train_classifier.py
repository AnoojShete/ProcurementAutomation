#!/usr/bin/env python3
"""Trains the ML document classifier and compares it with the keyword
classifier on held-out documents (FR-29). The model is saved — and so used
by app/services/classification.py — only if it beats the keywords on the
validation set; otherwise any old model is removed and keywords stay.

Data: ml/classification_corpus.py (invoice / po / quote in clean, OCR-noise
and no-title variants, plus "other" paperwork) and the committed
data/synthetic-classification rows (training only). Split 60/20/20,
stratified by label and variant, seeded.

What's compared on validation and test:
  keyword  — app.services.classification._classify_with_keywords
  ml       — TF-IDF character n-grams + logistic regression
  shipped  — what the pipeline does with the model: ML when it is at least
             ML_MIN_CONFIDENCE sure, otherwise keywords

Run inside the document-vendor-agent image, from /app:
    python ml/train_classifier.py [--out docs-results-dir]
Writes ml/artifacts/classifier.joblib (if kept), classifier.json / .md.
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

from classification_corpus import corpus  # noqa: E402

ARTIFACTS = os.path.join(_HERE, "artifacts")
MODEL_PATH = os.path.join(ARTIFACTS, "classifier.joblib")
LABELS = ["invoice", "po", "quote", "other"]
SEED = 29
ML_MIN_CONFIDENCE = 0.6     # same as app/services/classification.py
HELD_OUT_OTHER = (4, 6)     # credit notes and goods-receipt notes (indexes in OTHER_TEMPLATES)
_COMMITTED = [os.path.join(_HERE, "..", "..", "..", "data", "synthetic-classification", "classification_training_data.csv"),
              "/app/data/synthetic-classification/classification_training_data.csv",
              "/data/synthetic-classification/classification_training_data.csv"]


def committed_rows():
    path = next((p for p in _COMMITTED if os.path.exists(p)), None)
    if not path:
        return []
    return [(r["text"], r["label"], "committed", "committed") for r in csv.DictReader(open(path))]


def build_model() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=2, lowercase=True)),
        ("clf", LogisticRegression(C=10.0, max_iter=3000, class_weight="balanced", random_state=SEED)),
    ])


def predict_keyword(texts):
    from app.services.classification import _classify_with_keywords
    return [_classify_with_keywords(t).document_type for t in texts]


def predict_shipped(model, texts):
    from app.services.classification import _classify_with_keywords
    out = []
    for t, probs in zip(texts, model.predict_proba(texts)):
        best = probs.argmax()
        out.append(model.classes_[best] if probs[best] >= ML_MIN_CONFIDENCE else _classify_with_keywords(t).document_type)
    return out


def report(y, pred, variants):
    p, r, f, n = precision_recall_fscore_support(y, pred, labels=LABELS, zero_division=0)
    by_variant = {}
    for v in sorted(set(variants)):
        idx = [i for i, x in enumerate(variants) if x == v]
        by_variant[v] = round(accuracy_score([y[i] for i in idx], [pred[i] for i in idx]), 3)
    return {"accuracy": round(accuracy_score(y, pred), 3), "macro_f1": round(f1_score(y, pred, labels=LABELS, average="macro", zero_division=0), 3),
            "per_class": {lab: {"precision": round(float(p[i]), 3), "recall": round(float(r[i]), 3), "f1": round(float(f[i]), 3), "n": int(n[i])}
                          for i, lab in enumerate(LABELS)},
            "accuracy_by_variant": by_variant}


def run(out_dir: str) -> dict:
    rows = corpus(seed=SEED)
    strata = [f"{lab}:{var}" for _, lab, var, _ in rows]
    tr, rest = train_test_split(range(len(rows)), test_size=0.4, stratify=strata, random_state=SEED)
    va, te = train_test_split(rest, test_size=0.5, stratify=[strata[i] for i in rest], random_state=SEED)
    pick = lambda idx: ([rows[i][0] for i in idx], [rows[i][1] for i in idx], [rows[i][2] for i in idx])
    extra = committed_rows()
    X_tr, y_tr, _ = pick(tr)
    X_tr += [t for t, *_ in extra]
    y_tr += [lab for _, lab, *_ in extra]
    X_va, y_va, v_va = pick(va)
    X_te, y_te, v_te = pick(te)

    model = build_model().fit(X_tr, y_tr)
    results = {}
    for split, (X, y, v) in {"validation": (X_va, y_va, v_va), "test": (X_te, y_te, v_te)}.items():
        results[split] = {"keyword": report(y, predict_keyword(X), v), "ml": report(y, list(model.predict(X)), v),
                          "shipped": report(y, predict_shipped(model, X), v)}

    # Generalisation: train without layout C and two kinds of "other"
    # paperwork, test on exactly those kinds — the in-template test above is
    # easy because train and test share templates.
    unseen = {"C", f"other-{HELD_OUT_OTHER[0]}", f"other-{HELD_OUT_OTHER[1]}"}
    seen_idx = [i for i in range(len(rows)) if rows[i][3] not in unseen]
    unseen_idx = [i for i in range(len(rows)) if rows[i][3] in unseen]
    X_s, y_s, _ = pick(seen_idx)
    X_u, y_u, v_u = pick(unseen_idx)
    gen_model = build_model().fit(X_s + [t for t, *_ in extra], y_s + [lab for _, lab, *_ in extra])
    results["unseen_kinds"] = {"keyword": report(y_u, predict_keyword(X_u), v_u), "ml": report(y_u, list(gen_model.predict(X_u)), v_u),
                               "shipped": report(y_u, predict_shipped(gen_model, X_u), v_u),
                               "held_out": sorted(unseen), "train_size": len(X_s), "test_size": len(X_u)}

    keep = (results["validation"]["shipped"]["macro_f1"] > results["validation"]["keyword"]["macro_f1"]
            and results["unseen_kinds"]["shipped"]["macro_f1"] > results["unseen_kinds"]["keyword"]["macro_f1"])
    os.makedirs(ARTIFACTS, exist_ok=True)
    if keep:
        joblib.dump(model, MODEL_PATH)
    elif os.path.exists(MODEL_PATH):
        os.remove(MODEL_PATH)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {"corpus": len(rows), "committed_rows_in_training": len(extra), "seed": SEED,
                 "split": {"train": len(X_tr), "validation": len(X_va), "test": len(X_te)},
                 "labels": dict(Counter(r[1] for r in rows))},
        "model": "TF-IDF char_wb 2-5 + logistic regression (balanced)",
        "decision": {"ml_used": keep, "rule": "keep the model only if the shipped router beats keywords on validation macro-F1 and on document kinds held out of training",
                     "ml_min_confidence": ML_MIN_CONFIDENCE},
        **results,
    }
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        json.dump(summary, open(os.path.join(out_dir, "classifier.json"), "w"), indent=2)
        open(os.path.join(out_dir, "classifier.md"), "w").write(to_markdown(summary))
    return summary


def to_markdown(s: dict) -> str:
    t = s["test"]
    lines = [
        "# Document classifier — keyword vs ML", "",
        f"Generated {s['generated_at']} by `services/document-vendor-agent/ml/train_classifier.py`. "
        f"{s['data']['corpus']} documents from `ml/classification_corpus.py` (generated invoices / POs / quotes in clean, "
        "OCR-noise and missing-title variants, plus delivery notes, statements, receipts, letters, credit notes, GRNs as "
        f"*other*), split {s['data']['split']['train']} / {s['data']['split']['validation']} / {s['data']['split']['test']}; "
        "synthetic, so these numbers compare the classifiers, they don't measure real intake.", "",
        f"**Decision: {'the ML model is used' if s['decision']['ml_used'] else 'keywords stay — the ML model was not better'}** "
        f"({s['decision']['rule']}; the pipeline uses ML when ≥ {s['decision']['ml_min_confidence']} confident, else keywords).", "",
        "## Test set", "", "| Classifier | Accuracy | Macro-F1 | Clean | OCR noise | No title | Other |", "|---|---|---|---|---|---|---|",
    ]
    for name, label in (("keyword", "Keywords"), ("ml", "ML alone"), ("shipped", "**Shipped** (ML ≥ 0.6, else keywords)")):
        r = t[name]
        bv = r["accuracy_by_variant"]
        lines.append(f"| {label} | {r['accuracy']} | {r['macro_f1']} | {bv.get('clean', '–')} | {bv.get('ocr_noise', '–')} | "
                     f"{bv.get('no_title', '–')} | {bv.get('other', '–')} |")
    u = s["unseen_kinds"]
    lines += ["", f"## Document kinds held out of training ({', '.join(u['held_out'])}; trained on {u['train_size']}, tested on {u['test_size']})", "",
              "The in-template test above is easy — train and test share templates. This one trains without one layout "
              "and two kinds of *other* paperwork and tests on exactly those.", "",
              "| Classifier | Accuracy | Macro-F1 | Clean | OCR noise | No title | Other |", "|---|---|---|---|---|---|---|"]
    for name, label in (("keyword", "Keywords"), ("ml", "ML alone"), ("shipped", "**Shipped**")):
        r = u[name]
        bv = r["accuracy_by_variant"]
        lines.append(f"| {label} | {r['accuracy']} | {r['macro_f1']} | {bv.get('clean', '–')} | {bv.get('ocr_noise', '–')} | "
                     f"{bv.get('no_title', '–')} | {bv.get('other', '–')} |")
    lines += ["", "## Per class (test)", "", "| Class | Keywords P / R | Shipped P / R |", "|---|---|---|"]
    for lab in LABELS:
        k, m = t["keyword"]["per_class"][lab], t["shipped"]["per_class"][lab]
        lines.append(f"| {lab} | {k['precision']} / {k['recall']} | {m['precision']} / {m['recall']} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    s = run(ap.parse_args().out)
    print(json.dumps({"ml_used": s["decision"]["ml_used"],
                      "test": {k: {"macro_f1": v["macro_f1"], "by_variant": v["accuracy_by_variant"]} for k, v in s["test"].items()},
                      "unseen": {k: {"macro_f1": v["macro_f1"], "by_variant": v["accuracy_by_variant"]}
                                 for k, v in s["unseen_kinds"].items() if isinstance(v, dict)}}, indent=1))
