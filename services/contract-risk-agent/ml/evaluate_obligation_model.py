#!/usr/bin/env python3
"""Evaluates obligation extraction (feature expansion Phase 2): for each
obligation type with a CUAD category, Legal-BERT against the regex rules.

Run inside the contract-risk-agent image, from /app, with the model cached
and CUAD's test split mounted (same data as ml/evaluate_clause_model.py):
  python ml/evaluate_obligation_model.py --cuad /cuad/test.json --out /out
Writes <out>/obligations.json and <out>/obligations.md; model answers are
cached in <out>/obligations-cache.jsonl, so a rerun only recomputes metrics.

1. CUAD test split (102 contracts, lawyer-annotated): a method finds a
   clause correctly when its span overlaps an annotated span. P / R / F1.
2. Our three templates (20 each, random seat counts): every value the app
   stores must come out exactly — by the rules, and by the model.
3. The FR-13 clause fields (renewal type, notice period, end date) must still
   come out exactly from the templates now that they carry more clauses.

Decision, fixed before running: a type uses the model when its CUAD F1 beats
the rules' F1 and it reads every template value of that type correctly;
otherwise the rules stay. Types without a CUAD category (SLA, data
protection) and Price Restrictions (no examples in the test split) use the
rules and are checked on the templates only.
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # /app
sys.path.insert(0, HERE)

from jinja2 import Environment, FileSystemLoader  # noqa: E402

from app.services import clause_model  # noqa: E402
from app.services import obligation_extraction as ox  # noqa: E402
from evaluate_clause_model import overlaps, prf  # noqa: E402

SEED = 21
CUAD_TYPES = [k for k, t in ox.TYPES.items() if t.cuad_category]


def cuad_rows(path, cache_path):
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
            gold = {k: [] for k in CUAD_TYPES}
            for qa in para["qas"]:
                for k in CUAD_TYPES:
                    if qa["id"].endswith("__" + ox.TYPES[k].cuad_category):
                        gold[k] = [(a["answer_start"], a["answer_start"] + len(a["text"])) for a in qa["answers"]]
            if doc["title"] not in cache:
                t0 = time.time()
                model = {}
                for k in CUAD_TYPES:
                    p = clause_model.answer(text, clause_model.cuad_question(ox.TYPES[k].cuad_category))
                    model[k] = p and [p["start"], p["end"], p["score"]]
                cache[doc["title"]] = {"title": doc["title"], "seconds": round(time.time() - t0, 1), "model": model}
                cache_file.write(json.dumps(cache[doc["title"]]) + "\n")
                cache_file.flush()
                print(f"[{i + 1}/{len(data)}] {len(text):>7} chars {cache[doc['title']]['seconds']:6.1f}s", flush=True)
            m = cache[doc["title"]]["model"]
            rows.append({"title": doc["title"], "gold": gold, "seconds": cache[doc["title"]]["seconds"],
                         "model": {k: (tuple(m[k][:2]) if m.get(k) else None) for k in CUAD_TYPES},
                         "rules": {k: ox.rule_span(text, k) for k in CUAD_TYPES}})
    return rows


def score(rows, method):
    out = {}
    for k in CUAD_TYPES:
        tp = fp = fn = 0
        for r in rows:
            span, gold = r[method][k], r["gold"][k]
            hit = span is not None and overlaps(span, gold)
            tp += hit
            fp += span is not None and not hit
            fn += bool(gold) and not hit
        out[k] = {**prf(tp, fp, fn), "contracts_with_clause": sum(1 for r in rows if r["gold"][k])}
    return out


def template_cases(n_each=20):
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(HERE), "app", "templates")))
    rng = random.Random(SEED)
    cases = []
    for name in ("saas_subscription", "hardware_purchase", "professional_services"):
        for _ in range(n_each):
            users = rng.choice([5, 12, 25, 40, 60, 150, 500])
            minimum = max(1, users // 2)
            text = env.get_template(f"{name}.j2").render(
                contract_id="c-eval", generated_at="2026-10-20T00:00:00+00:00", vendor_name="Acme Supplies Pvt Ltd",
                purchase_request_id="pr-eval", department="IT", currency="INR", amount=125000,
                items=[{"description": "Seat", "quantity": users, "unit_price": 1000}],
                contract_end_date="2027-10-20", notice_period_days=30, licensed_users=users, minimum_users=minimum)
            expected = {
                "saas_subscription": {
                    "sla_uptime": {"uptime_pct": 99.9, "credit_pct_per_step": 10.0, "step_pct": 0.1, "credit_cap_pct": 50.0},
                    "license_limit": {"seats": users, "non_transferable": True, "territory": "India"},
                    "price_cap": {"max_increase_pct": 5.0},
                    "audit_rights": {"days": 30, "frequency": "annual"},
                    "minimum_commitment": {"seats": minimum, "months": 12},
                    "post_termination": {"days": 30},
                    "data_protection": {"breach_notice_hours": 72},
                    "liability_cap": {"fees_months": 12},
                    "insurance": {"amount": 10000000.0},
                },
                "hardware_purchase": {"warranty": {"months": 36}, "liability_cap": {}},
                "professional_services": {
                    "termination_convenience": {"days": 30}, "post_termination": {"days": 15},
                    "liability_cap": {"fees_months": 12}, "insurance": {"amount": 5000000.0},
                },
            }[name]
            cases.append({"template": name, "text": text, "expected": expected})
    return cases


def template_accuracy(cases, with_model):
    out = {}
    for method in ("rules", "model") if with_model else ("rules",):
        right, total, wrong = {}, {}, []
        for c in cases:
            got = ({o["type"]: o["value"] for o in ox.extract_with_rules(c["text"])} if method == "rules"
                   else {o["type"]: o["value"] for o in ox.extract_with_model(c["text"], CUAD_TYPES)})
            for k, exp in c["expected"].items():
                if method == "model" and k not in CUAD_TYPES:
                    continue
                total[k] = total.get(k, 0) + 1
                if got.get(k) == exp:
                    right[k] = right.get(k, 0) + 1
                elif len(wrong) < 8:
                    wrong.append({"template": c["template"], "type": k, "expected": exp, "got": got.get(k)})
            # Extra obligation types found where the template has none.
            for k in got:
                if k not in c["expected"] and len(wrong) < 8:
                    wrong.append({"template": c["template"], "type": k, "expected": None, "got": got[k]})
        out[method] = {"accuracy": {k: round(right.get(k, 0) / total[k], 3) for k in total}, "examples_wrong": wrong}
    return out


def clause_fields_still_exact():
    """FR-13 regression: renewal type, notice period and end date from the
    templates that now carry the obligation clauses."""
    from evaluate_clause_model import template_accuracy as fr13_accuracy, template_cases as fr13_cases
    return fr13_accuracy(fr13_cases())


def decide(cuad, templates):
    out = {}
    for k in CUAD_TYPES:
        beats = cuad["model"][k]["f1"] > cuad["rules"][k]["f1"]
        tmpl = templates.get("model", {}).get("accuracy", {}).get(k)
        out[k] = {"model_beats_rules": beats, "model_template_accuracy": tmpl,
                  "primary": "model" if beats and (tmpl is None or tmpl == 1.0) else "rules"}
    for k, t in ox.TYPES.items():
        if not t.cuad_category:
            out[k] = {"model_beats_rules": None, "model_template_accuracy": None, "primary": "rules", "note": t.notes}
    return out


def markdown(r):
    c, t, d = r["cuad"], r["templates"], r["decision"]
    L = ["# Obligation extraction: Legal-BERT vs rules (feature expansion Phase 2)", "",
         f"Generated {r['generated_at'][:10]} by `ml/evaluate_obligation_model.py`. Model: "
         f"[{r['model']}](https://huggingface.co/{r['model']}), asked CUAD's own question for each category.", ""]
    if c:
        L += [f"## CUAD test split — {r['contracts']} lawyer-annotated contracts", "",
              "Correct = the returned passage (model) or the rule's match overlaps an annotated span.", "",
              "| Obligation | CUAD category | Contracts with it | Rules P / R / F1 | Model P / R / F1 | Primary |",
              "|---|---|---|---|---|---|"]
        for k in CUAD_TYPES:
            ru, mo = c["rules"][k], c["model"][k]
            L.append(f"| {ox.TYPES[k].label} | {ox.TYPES[k].cuad_category} | {mo['contracts_with_clause']} | "
                     f"{ru['precision']:.2f} / {ru['recall']:.2f} / **{ru['f1']:.2f}** | "
                     f"{mo['precision']:.2f} / {mo['recall']:.2f} / **{mo['f1']:.2f}** | {d[k]['primary']} |")
        L += ["", f"Model time per contract (8 questions, CPU): median {r['median_seconds']} s.", ""]
    L += ["## Our templates — values the app stores", "", "| Obligation | Rules exact | Model exact |", "|---|---|---|"]
    for k in ox.TYPES:
        ru = t["rules"]["accuracy"].get(k)
        mo = t.get("model", {}).get("accuracy", {}).get(k)
        if ru is None and mo is None:
            continue
        L.append(f"| {ox.TYPES[k].label} | {'' if ru is None else f'{ru:.0%}'} | {'' if mo is None else f'{mo:.0%}'} |")
    for method in t:
        if t[method]["examples_wrong"]:
            L += ["", f"{method.title()} misses (first few): " + "; ".join(
                f"{w['template']} {w['type']}: expected {w['expected']}, got {w['got']}" for w in t[method]["examples_wrong"])]
    fr = r["fr13_templates"]
    L += ["", "## FR-13 clause fields, templates with the new clauses", "",
          f"Rules: {fr['rules']['accuracy']} · Model: {fr['model']['accuracy']}", "",
          "## Decision", "",
          "A type uses the model only if its CUAD F1 beats the rules and it reads every template value right.", "",
          "| Obligation | Primary | Why |", "|---|---|---|"]
    for k in ox.TYPES:
        x = d[k]
        why = x.get("note") or ("model F1 higher and templates exact" if x["primary"] == "model" else
                                "model F1 not higher" if not x["model_beats_rules"] else "model misses template values")
        L.append(f"| {ox.TYPES[k].label} | {x['primary']} | {why} |")
    L += ["", "Rules for SLA uptime and data protection are checked on our templates only (no CUAD category); "
          "Price Restrictions has no examples in CUAD's test split. Every extracted obligation is confirmed by a "
          "person before reminders start, so a wrong extraction costs a correction, not a missed obligation.", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cuad", help="CUAD test.json")
    ap.add_argument("--out", default="/out")
    ap.add_argument("--templates-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with_model = clause_model.available()
    r = {"generated_at": datetime.now(timezone.utc).isoformat(), "model": clause_model.MODEL_ID,
         "model_available": with_model, "cuad": None}
    if a.cuad and not a.templates_only and with_model:
        rows = cuad_rows(a.cuad, os.path.join(a.out, "obligations-cache.jsonl"))
        r["contracts"] = len(rows)
        r["cuad"] = {"rules": score(rows, "rules"), "model": score(rows, "model")}
        secs = sorted(x["seconds"] for x in rows)
        r["median_seconds"] = secs[len(secs) // 2]
    r["templates"] = template_accuracy(template_cases(), with_model)
    r["fr13_templates"] = clause_fields_still_exact() if with_model else {"rules": {"accuracy": {}}, "model": {"accuracy": {}}}
    r["decision"] = decide(r["cuad"] or {"rules": {k: {"f1": 1} for k in CUAD_TYPES}, "model": {k: {"f1": 0} for k in CUAD_TYPES}},
                           r["templates"])
    json.dump(r, open(os.path.join(a.out, "obligations.json"), "w"), indent=2, default=str)
    open(os.path.join(a.out, "obligations.md"), "w").write(markdown(r))
    print(json.dumps({k: v["primary"] for k, v in r["decision"].items()}))


if __name__ == "__main__":
    main()
