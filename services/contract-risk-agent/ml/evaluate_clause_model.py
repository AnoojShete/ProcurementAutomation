#!/usr/bin/env python3
"""Evaluates clause extraction: Legal-BERT (CUAD) against the rules (FR-13).

Run inside the contract-risk-agent image, from /app, with the model cached
(./scripts/download-models.sh) and CUAD's test split downloaded
(https://github.com/TheAtticusProject/cuad/raw/main/data.zip → test.json,
CC BY 4.0):
  python ml/evaluate_clause_model.py --cuad /cuad/test.json --out /out
Writes <out>/clauses.json and <out>/clauses.md. Model answers are cached in
<out>/clauses-cache.jsonl (about an hour on CPU for all 102 contracts), so
a rerun only recomputes the metrics.

Two test sets:
1. CUAD test split — 102 real contracts (EDGAR filings) annotated by
   lawyers, not used to train the model (it was fine-tuned on CUAD's train
   split). For each clause, a method "finds" it when it returns a passage
   (model) or a rule matches (rules). Correct = the passage overlaps a
   lawyer-highlighted span. Precision / recall / F1 per clause.
2. Our own contract templates (3 templates × 20 random notice periods and
   end dates): the values the app stores — renewal type, notice days, end
   date — must come out exactly. This is what the app runs on today.

Decision, fixed before running: the model becomes the primary when its F1
beats the rules on at least two of the three CUAD clauses and it gets
every template value right; otherwise the rules stay primary.
"""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # /app

from jinja2 import Environment, FileSystemLoader  # noqa: E402

from app.services import clause_model  # noqa: E402
from app.services.clause_extraction import (  # noqa: E402
    AUTO_RENEW_PATTERNS, END_DATE_LABEL_PATTERNS, MANUAL_RENEW_PATTERNS, NOTICE_PERIOD_PATTERNS,
    end_date_from, extract_clauses, notice_days_from, renewal_type_from,
)

FIELDS = list(clause_model.QUESTIONS)
SEED = 13
TEMPLATES = ["saas_subscription", "hardware_purchase", "professional_services"]
EXPECTED_RENEWAL = {"saas_subscription": "auto", "hardware_purchase": "manual", "professional_services": "manual"}


# ── rules as spans, so they can be scored like the model ────────────────────

def rule_spans(text: str) -> dict:
    """Where extract_clauses' rules match: {field: (start, end) or None}.
    Same patterns in the same order as extract_clauses."""
    lower = text.lower()
    out = {}
    m = next((m for p in MANUAL_RENEW_PATTERNS + AUTO_RENEW_PATTERNS if (m := re.search(p, lower))), None)
    out["renewal_type"] = m.span() if m else None
    m = next((m for p in NOTICE_PERIOD_PATTERNS if (m := re.search(p, lower, flags=re.DOTALL))), None)
    out["notice_period_days"] = m.span() if m else None
    m = next((m for p in END_DATE_LABEL_PATTERNS if (m := re.search(p, text, flags=re.IGNORECASE))), None)
    out["contract_end_date"] = m.span() if m else None
    return out


def overlaps(span, gold) -> bool:
    return any(span[0] < g[1] and g[0] < span[1] for g in gold)


def prf(tp, fp, fn) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(p, 3), "recall": round(r, 3),
            "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}


def score(rows, method) -> dict:
    out = {}
    for f in FIELDS:
        tp = fp = fn = 0
        for row in rows:
            span, gold = row[method][f], row["gold"][f]
            hit = span is not None and overlaps(span, gold)
            tp += hit
            fp += span is not None and not hit
            fn += bool(gold) and not hit
        out[f] = prf(tp, fp, fn)
    return out


# ── CUAD ────────────────────────────────────────────────────────────────────

def cuad_rows(path, cache_path) -> list[dict]:
    cache = {}
    if os.path.exists(cache_path):
        for line in open(cache_path):
            r = json.loads(line)
            cache[r["title"]] = r
    data = json.load(open(path))["data"]
    rows = []
    with open(cache_path, "a") as cache_file:
        for i, doc in enumerate(data):
            para = doc["paragraphs"][0]
            text = para["context"]
            gold = {f: [] for f in FIELDS}
            for qa in para["qas"]:
                for f, cat in clause_model.CUAD_CATEGORY.items():
                    if qa["id"].endswith("__" + cat):
                        gold[f] = [(a["answer_start"], a["answer_start"] + len(a["text"])) for a in qa["answers"]]
            if doc["title"] not in cache:
                t0 = time.time()
                passages = clause_model.find_passages(text)
                cache[doc["title"]] = {"title": doc["title"], "seconds": round(time.time() - t0, 1),
                                       "model": {f: (p and [p["start"], p["end"], p["score"]]) for f, p in passages.items()}}
                cache_file.write(json.dumps(cache[doc["title"]]) + "\n")
                cache_file.flush()
                print(f"[{i + 1}/{len(data)}] {len(text):>7} chars {cache[doc['title']]['seconds']:5.1f}s", flush=True)
            model = cache[doc["title"]]["model"]
            rows.append({
                "title": doc["title"], "chars": len(text), "seconds": cache[doc["title"]]["seconds"], "gold": gold,
                "model": {f: (tuple(model[f][:2]) if model[f] else None) for f in FIELDS},
                "rules": rule_spans(text),
            })
    return rows


# ── our templates ───────────────────────────────────────────────────────────

def template_cases(n_each=20) -> list[dict]:
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(HERE), "app", "templates")))
    rng = random.Random(SEED)
    cases = []
    for name in TEMPLATES:
        for _ in range(n_each):
            end = date(2026, 1, 1) + timedelta(days=rng.randint(30, 1500))
            notice = rng.choice([7, 14, 15, 30, 45, 60, 90, 120])
            text = env.get_template(f"{name}.j2").render(
                contract_id="c-eval", generated_at="2026-10-16T00:00:00+00:00", vendor_name="Acme Supplies Pvt Ltd",
                purchase_request_id="pr-eval", department="IT", currency="INR", amount=125000,
                items=[{"description": "Laptop", "quantity": 2, "unit_price": 62500}],
                contract_end_date=end.isoformat(), notice_period_days=notice,
            )
            cases.append({"template": name, "text": text, "expected": {
                "renewal_type": EXPECTED_RENEWAL[name], "notice_period_days": notice, "contract_end_date": end}})
    return cases


def model_values(text: str) -> dict:
    p = clause_model.find_passages(text)
    return {
        "renewal_type": renewal_type_from(p["renewal_type"] and p["renewal_type"]["text"]),
        "notice_period_days": notice_days_from(p["notice_period_days"] and p["notice_period_days"]["text"]),
        "contract_end_date": end_date_from(p["contract_end_date"] and p["contract_end_date"]["text"]),
    }


def template_accuracy(cases) -> dict:
    out = {}
    for method, fn in (("rules", extract_clauses), ("model", model_values)):
        right = {f: 0 for f in FIELDS}
        misses = []
        for c in cases:
            got = fn(c["text"])
            for f in FIELDS:
                if got[f] == c["expected"][f]:
                    right[f] += 1
                elif len(misses) < 5:
                    misses.append({"template": c["template"], "field": f, "expected": str(c["expected"][f]),
                                   "got": str(got[f])})
        out[method] = {"accuracy": {f: round(right[f] / len(cases), 3) for f in FIELDS}, "examples_wrong": misses}
    return out


# ── report ──────────────────────────────────────────────────────────────────

LABEL = {"renewal_type": "Renewal term", "notice_period_days": "Notice period to terminate renewal",
         "contract_end_date": "Expiration date"}


def decide(cuad, templates) -> dict:
    wins = [f for f in FIELDS if cuad["model"][f]["f1"] > cuad["rules"][f]["f1"]]
    templates_ok = all(v == 1.0 for v in templates["model"]["accuracy"].values())
    primary = "model" if len(wins) >= 2 and templates_ok else "rules"
    return {"model_beats_rules_on": wins, "model_gets_every_template_value": templates_ok, "primary": primary}


def markdown(r) -> str:
    c, t, d = r["cuad"], r["templates"], r["decision"]
    lines = [
        "# Clause extraction: Legal-BERT vs rules (FR-13)", "",
        f"Generated {r['generated_at'][:10]} by `ml/evaluate_clause_model.py`. Model: "
        f"[{r['model']}](https://huggingface.co/{r['model']}) (Legal-BERT fine-tuned on CUAD's train split).", "",
        f"## CUAD test split — {c['contracts']} real contracts, lawyer-annotated", "",
        "A clause is *found* correctly when the passage returned (model) or the text matched (rules) overlaps a "
        "span the annotators highlighted.", "",
        "| Clause | Contracts with it | Rules P / R / F1 | Model P / R / F1 |", "|---|---|---|---|",
    ]
    for f in FIELDS:
        a, b = c["rules"][f], c["model"][f]
        lines.append(f"| {LABEL[f]} | {c['positives'][f]} | {a['precision']:.2f} / {a['recall']:.2f} / **{a['f1']:.2f}** "
                     f"| {b['precision']:.2f} / {b['recall']:.2f} / **{b['f1']:.2f}** |")
    lines += ["", f"Model time on CPU: median {c['seconds_per_contract_median']:.0f} s per contract "
                  f"(three questions; contracts median {c['chars_median']:,} characters).", "",
              f"## Our contract templates — {t['cases']} contracts", "",
              "Exact values the app stores.", "",
              "| Value | Rules | Model |", "|---|---|---|"]
    for f in FIELDS:
        lines.append(f"| {LABEL[f]} | {t['rules']['accuracy'][f]:.0%} | {t['model']['accuracy'][f]:.0%} |")
    if t["model"]["examples_wrong"]:
        lines += ["", "Model mistakes (first few): " + "; ".join(
            f"{w['template']} {w['field']}: expected {w['expected']}, got {w['got']}" for w in t["model"]["examples_wrong"])]
    lines += ["", "## Decision", "",
              "Rule, fixed before running: the model is the primary when its F1 beats the rules on at least two "
              "of the three CUAD clauses **and** it gets every template value right.", "",
              f"- Model beats rules on: {', '.join(LABEL[f] for f in d['model_beats_rules_on']) or 'none'}",
              f"- Every template value right: {'yes' if d['model_gets_every_template_value'] else 'no'}",
              f"- **Primary: {d['primary']}**; the other is the fallback (`clause_router.py`).", "",
              "## Limits", "",
              "- CUAD is US commercial contracts; ours are short generated Indian procurement contracts.",
              "- \"Found\" is scored by overlap with any highlighted span, not exact boundaries.",
              "- Expiration dates in CUAD are mostly relative (\"five years from the Effective Date\"); the model "
              "finds the passage but a date is only stored when the passage states one.",
              "- 102 contracts, and only 16 have a notice-to-terminate-renewal clause — small numbers.", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cuad", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if not clause_model.available():
        sys.exit("Clause model not cached — run ./scripts/download-models.sh first.")
    os.makedirs(args.out, exist_ok=True)

    rows = cuad_rows(args.cuad, os.path.join(args.out, "clauses-cache.jsonl"))
    chars = sorted(r["chars"] for r in rows)
    seconds = sorted(r["seconds"] for r in rows)
    cuad = {
        "contracts": len(rows),
        "positives": {f: sum(bool(r["gold"][f]) for r in rows) for f in FIELDS},
        "rules": score(rows, "rules"), "model": score(rows, "model"),
        "chars_median": chars[len(chars) // 2],
        "seconds_per_contract_median": seconds[len(seconds) // 2],
    }
    cases = template_cases()
    templates = {"cases": len(cases), **template_accuracy(cases)}
    result = {"generated_at": datetime.now(timezone.utc).isoformat(), "model": clause_model.MODEL_ID,
              "cuad": cuad, "templates": templates, "decision": decide(cuad, templates)}
    json.dump(result, open(os.path.join(args.out, "clauses.json"), "w"), indent=2, default=str)
    open(os.path.join(args.out, "clauses.md"), "w").write(markdown(result))
    print(markdown(result))


if __name__ == "__main__":
    main()
