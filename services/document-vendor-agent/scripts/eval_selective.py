"""Selective-automation study: can enterprise evidence let more invoices
skip review at a fixed document-level error rate? (RS-03, RS-05, RS-06,
RS-07, RS-09; plan in docs/RESEARCH_PAPER_PLAN.md)

Two stages, run inside the document-vendor-agent image (see the
"Research" section of docs/readmeforme.md for the docker command):

  python scripts/eval_selective.py extract   # render + read every invoice (cached, resumable)
  python scripts/eval_selective.py evaluate  # evidence, splits, gates → docs/results/selective.{json,md}

`extract` runs the production reading code on each generated document:
app/services/ocr.extract_text for PDFs, PaddleOCR with the production
settings and parsing for images (one model per worker instead of one
subprocess per image: ~15 s → ~1 s), classify_document and extract_fields. `evaluate` computes the evidence the pipeline would
have, against the generated vendor master, PO ledger and invoice history
instead of the database: vendor matching (same normalisation, scorer and
thresholds as app/services/vendor_matching.py), the three-way match
(approval-inventory-agent's pure invoice_ledger.evaluate), duplicate
detection (same rule as app/services/duplicate_detection.py), GSTIN check
digit (app/services/gstin_service.py) and bank details against the master.

A document counts as correct when vendor name, total, currency and invoice
number were read right AND no business error was injected; accepting a
document that isn't is an error. Systems compared:
  B0   the current rule (overall confidence >= 0.8 and no forced-review flag)
  B1   calibrated gate, document-internal evidence only
  B2   rules-only enterprise matcher (accept when every enterprise check passes)
  P    calibrated gate, document-internal + enterprise evidence
  FC   per-component gates (vendor, total, currency, number, business) at alpha/5 each (RQ2)
"""
import argparse
import importlib.util
import json
import math
import multiprocessing
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date

import numpy as np

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(SERVICE_DIR))
sys.path[:0] = [SERVICE_DIR, REPO_ROOT]

from scripts.procurement_world import GENERATOR_VERSION, build_world, render  # noqa: E402

DATA_DIR = os.path.join(REPO_ROOT, "data", "procurement-world")
RESULTS_DIR = os.path.join(REPO_ROOT, "docs", "results")
USD_TO_INR = 83.0
ALPHAS = (0.01, 0.02, 0.05, 0.10)  # the plan fixed 1/2/5 %; 10 % added once nothing passed at 5 %
SECONDARY_ALPHA = 0.10  # ablation and RQ3 (at <= 5 % no gate accepts anything, so they'd be all zeros)
DELTA = 0.1
N_SPLITS = 20
GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")


# --------------------------------------------------------------------- extract

_PADDLE = None


def _paddle_text(data: bytes) -> tuple[str, float]:
    """What app/services/ocr.py does for an image (PaddleOCR with the same
    settings and line parsing as _paddle_worker.py, then the same
    _rows_to_text / _ocr_confidence), but with one PaddleOCR per worker
    process instead of a new subprocess and model load per image."""
    global _PADDLE
    import contextlib
    import io as _io

    from PIL import Image

    from app.services.ocr import _ocr_confidence, _rows_to_text
    if _PADDLE is None:
        with contextlib.redirect_stdout(sys.stderr):
            from paddleocr import PaddleOCR
            _PADDLE = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    img = Image.open(_io.BytesIO(data)).convert("RGB")
    with contextlib.redirect_stdout(sys.stderr):
        result = _PADDLE.ocr(np.array(img), cls=True)
    lines = []
    for block in result or []:
        for line in block or []:
            if line and len(line) >= 2 and line[1] and line[1][0]:
                xs, ys = [float(p[0]) for p in line[0]], [float(p[1]) for p in line[0]]
                lines.append({"text": line[1][0], "confidence": float(line[1][1]) if len(line[1]) > 1 else 0.0,
                              "box": [min(xs), min(ys), max(xs), max(ys)]})
    return _rows_to_text(lines), _ocr_confidence(lines)


def _extract_one(seed: int, doc) -> dict:
    from app.services.classification import classify_document
    from app.services.field_extraction import extract_fields
    from app.services.ocr import extract_text

    data, filename, content_type = render(doc, seed)
    t0 = time.time()
    try:
        if content_type.startswith("image/"):
            text, quality = _paddle_text(data)
            method = "paddleocr"
        else:
            result = extract_text(data, filename, content_type)
            text, method, quality = result.text, result.method, result.text_quality
    except Exception as e:  # an unreadable document is a data point, not a crash
        text, method, quality = "", f"error:{type(e).__name__}", 0.0
    cls = classify_document(text)
    fields, conf = extract_fields(text, document_type="invoice")
    return {
        "doc_id": doc.doc_id, "method": method, "text_quality": quality, "raw_text": text,
        "classification": cls.document_type, "classification_confidence": cls.confidence,
        "fields": fields.to_dict(document_type="invoice"), "field_confidences": vars(conf),
        "seconds": round(time.time() - t0, 3),
    }


def cmd_extract(args):
    world = build_world(seed=args.seed, n_vendors=args.vendors, n_invoices=args.invoices)
    out_dir = os.path.join(DATA_DIR, f"seed{args.seed}")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "world.json"), "w") as f:
        json.dump(world.to_dict(), f)
    path = os.path.join(out_dir, "extraction.jsonl")
    done = set()
    if os.path.exists(path):
        with open(path) as f:
            done = {json.loads(line)["doc_id"] for line in f if line.strip()}
    todo = [d for d in world.documents if d.doc_id not in done]
    print(f"{len(world.documents)} documents, {len(done)} already read, {len(todo)} to go", flush=True)
    t0 = time.time()
    # spawn, not fork: PaddleOCR crashes in a forked child.
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=ctx) as pool, open(path, "a") as out:
        futures = [pool.submit(_extract_one, args.seed, d) for d in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            out.write(json.dumps(fut.result()) + "\n")
            if i % 100 == 0 or i == len(todo):
                out.flush()
                print(f"  {i}/{len(todo)} read ({time.time() - t0:.0f} s)", flush=True)


# -------------------------------------------------------------------- evidence

def _load_ledger_module():
    path = os.path.join(REPO_ROOT, "services", "approval-inventory-agent", "app", "services", "invoice_ledger.py")
    spec = importlib.util.spec_from_file_location("invoice_ledger", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["invoice_ledger"] = module
    spec.loader.exec_module(module)
    return module


def _to_inr(amount, currency):
    return float(amount or 0) * (USD_TO_INR if currency == "USD" else 1.0)


def truth_labels(doc, ex, normalize) -> dict:
    f = ex["fields"]
    got_total = f.get("total")
    comps = {
        "vendor": normalize(f.get("vendor_name_raw") or "") == normalize(doc["vendor_name"]),
        "total": got_total is not None and abs(float(got_total) - doc["total"]) <= 0.01,
        "currency": (f.get("currency") or "") == doc["currency"],
        "number": (f.get("document_number") or "").strip().upper() == doc["document_number"],
        "business": doc["injection"] is None,
    }
    comps["fields"] = all(comps[k] for k in ("vendor", "total", "currency", "number"))
    comps["correct"] = comps["fields"] and comps["business"]
    return comps


FEATURE_GROUPS = {
    "document": ["text_quality", "method_pdf", "method_ocr", "method_error", "classification_conf",
                 "is_invoice", "conf_vendor", "conf_number", "conf_date", "conf_total", "conf_lines",
                 "overall_conf", "amounts_consistent", "amounts_mismatch", "currency_found",
                 "n_lines", "log_text_len", "gstin_found", "gstin_checksum_ok"],
    "vendor": ["vendor_score", "vendor_matched", "vendor_lookalike"],
    "bank": ["bank_present", "bank_matches_master", "bank_differs"],
    "gstin": ["gstin_matches_master"],
    "po": ["po_ref_found", "po_matched", "po_variance", "po_no_match", "po_ambiguous", "po_issues"],
    "duplicate": ["is_duplicate"],
    "currency": ["currency_matches_master"],
    "history": ["log_vendor_history"],
    # Exploratory, not in P: the duplicate check without its invoice-number
    # condition (= rule vendor.duplicate_invoice_number_fuzzy_threshold set
    # to 0). Used only by the P+dup system.
    "duplicate_any_number": ["is_duplicate_any_number"],
}
EXPLORATORY_GROUPS = ["duplicate_any_number"]
CORE_GROUPS = [g for g in FEATURE_GROUPS if g not in EXPLORATORY_GROUPS]
ENTERPRISE_GROUPS = [g for g in CORE_GROUPS if g != "document"]


def compute_evidence(world: dict, extraction: dict, noise: float = 0.0, noise_seed: int = 0) -> list:
    """One row per document, in date order, with features, labels and the
    B0 / B2 decisions. `noise` makes that share of the master data stale
    (RQ3): vendors' bank details and GSTIN out of date, POs missing."""
    from rapidfuzz import fuzz

    from app.config import load_duplicate_detection_config, load_extraction_config, load_vendor_matching_config
    from app.services.confidence import build_confidence_scores, overall_confidence
    from app.services.gstin_service import validate_gstin_offline
    from app.services.pipeline import find_po_reference
    from app.services.vendor_matching import normalize_vendor_name

    ledger = _load_ledger_module()
    tol = ledger.Tolerances()
    match_threshold = load_vendor_matching_config().get("fuzzy_match_threshold", 88)
    lookalike_min = 70  # rule vendor.lookalike_min_similarity (default)
    dup_cfg = load_duplicate_detection_config()
    dup_tol = float(dup_cfg.get("amount_tolerance_pct", 0.01))
    dup_days = int(dup_cfg.get("date_window_days", 5))
    dup_num = int(dup_cfg.get("document_number_fuzzy_threshold", 85))
    review_threshold = float(load_extraction_config().get("confidence_threshold", 0.8))

    rng = np.random.default_rng(noise_seed)
    master = {}
    for v in world["vendors"]:
        m = {"name": v["name"], "norm": normalize_vendor_name(v["name"]), "gstin": v["gstin"],
             "currency": v["currency"], "bank": dict(v["bank"])}
        if noise and rng.random() < noise:
            m["bank"] = {"account_number": str(rng.integers(10**11, 10**12)), "routing_code": "STALE0000000"}
            m["gstin"] = None
        master[v["vendor_id"]] = m
    pos_by_vendor = defaultdict(list)
    for p in world["pos"]:
        if noise and rng.random() < noise:
            continue  # PO not entered in the ledger (yet)
        pos_by_vendor[p["vendor_id"]].append(ledger.Candidate(
            request_id=p["po_id"], status="ordered", amount=p["amount"],
            lines=[ledger.POLine(i, l["description"], l["quantity"], l["unit_price"]) for i, l in enumerate(p["lines"])],
        ))
    cand_by_id = {c.request_id: c for cs in pos_by_vendor.values() for c in cs}
    history = defaultdict(list)  # vendor key -> earlier invoices as recorded (true fields)
    rows = []
    docs = sorted(world["documents"], key=lambda d: (d["document_date"], d["doc_id"]))
    for doc in docs:
        ex = extraction[doc["doc_id"]]
        f, fc = ex["fields"], ex["field_confidences"]
        text = ex["raw_text"] or ""
        labels = truth_labels(doc, ex, normalize_vendor_name)

        # --- document-internal evidence
        scores = build_confidence_scores(ex["classification_confidence"], {
            "vendor_name": fc["vendor_name"], "document_number": fc["document_number"],
            "document_date": fc["document_date"], "total": fc["total"], "line_items": fc["line_items"],
        }, ex["text_quality"])
        overall = overall_confidence(scores)
        check = (f.get("amount_check") or {}).get("status")
        gstins = GSTIN_RE.findall(text.upper())
        gstin = gstins[0] if gstins else None
        lines = [li for li in (f.get("line_items") or []) if li.get("quantity") and li.get("unit_price") is not None]
        feat = {
            "text_quality": ex["text_quality"], "method_pdf": float(ex["method"] == "pdf_text"),
            "method_ocr": float(ex["method"] in ("paddleocr", "docling")), "method_error": float(ex["method"].startswith("error")),
            "classification_conf": ex["classification_confidence"], "is_invoice": float(ex["classification"] == "invoice"),
            "conf_vendor": fc["vendor_name"], "conf_number": fc["document_number"], "conf_date": fc["document_date"],
            "conf_total": fc["total"], "conf_lines": fc["line_items"], "overall_conf": overall,
            "amounts_consistent": float(check == "consistent"), "amounts_mismatch": float(check == "mismatch"),
            "currency_found": float(bool(f.get("currency"))), "n_lines": float(len(lines)),
            "log_text_len": math.log1p(len(text)), "gstin_found": float(gstin is not None),
            "gstin_checksum_ok": float(gstin is not None and validate_gstin_offline(gstin)[0]),
        }

        # --- enterprise evidence: vendor master
        norm = normalize_vendor_name(f.get("vendor_name_raw") or "")
        best_id, best = None, 0.0
        if norm:
            for vid, m in master.items():
                s = fuzz.token_sort_ratio(norm, m["norm"])
                if s > best:
                    best_id, best = vid, s
        matched = best_id is not None and best >= match_threshold
        lookalike = best_id is not None and not matched and best >= lookalike_min
        m = master[best_id] if matched else None
        bank_present = bool(f.get("bank_account_number"))
        bank_same = bool(m and bank_present and f.get("bank_account_number") == m["bank"]["account_number"]
                         and (f.get("routing_code") or "").upper() == m["bank"]["routing_code"])
        feat.update({
            "vendor_score": best / 100, "vendor_matched": float(matched), "vendor_lookalike": float(lookalike),
            "bank_present": float(bank_present), "bank_matches_master": float(bank_same),
            "bank_differs": float(bank_present and not bank_same),
            "gstin_matches_master": float(bool(m and gstin and m["gstin"] and gstin == m["gstin"])),
            "currency_matches_master": float(bool(m and f.get("currency") == m["currency"])),
        })

        # --- three-way match against the vendor's open POs
        po_ref = find_po_reference(text)
        status, n_issues = "no_vendor", 0
        if matched and f.get("total"):
            res = ledger.evaluate(float(f["total"]),
                                  [ledger.InvoiceLine(li.get("description") or "", float(li["quantity"]), float(li["unit_price"]))
                                   for li in lines],
                                  pos_by_vendor.get(best_id, []), tol, po_ref)
            status, n_issues = res.status, len(res.issues)
        feat.update({
            "po_ref_found": float(po_ref is not None), "po_matched": float(status in ("matched", "partial")),
            "po_variance": float(status == "variance"), "po_no_match": float(status in ("no_match", "no_vendor")),
            "po_ambiguous": float(status == "ambiguous"), "po_issues": float(n_issues),
        })

        # --- duplicate check against the vendor's earlier invoices
        is_dup = is_dup_any = False
        if matched and f.get("total") is not None:
            total = float(f["total"])
            try:
                d0 = date.fromisoformat(f.get("document_date") or "")
            except ValueError:
                d0 = None
            for prev in history[best_id]:
                if abs(prev["total"] - total) > max(total * dup_tol, 0.01):
                    continue
                if d0 and abs((prev["date"] - d0).days) > dup_days:
                    continue
                is_dup_any = True
                num = f.get("document_number")
                if num and fuzz.ratio(num, prev["number"]) < dup_num:
                    continue
                is_dup = True
                break
        feat["is_duplicate"] = float(is_dup)
        feat["is_duplicate_any_number"] = float(is_dup_any)
        feat["log_vendor_history"] = math.log1p(len(history[best_id])) if matched else 0.0

        # --- the current production decision (B0) and the rules-only matcher (B2)
        forced = (is_dup or lookalike or not norm or ex["classification"] == "other"
                  or status not in ("matched", "partial") or (bank_present and not bank_same))
        b0_accept = overall >= review_threshold and not forced
        b2_accept = (matched and not lookalike and status in ("matched", "partial") and not is_dup
                     and (not bank_present or bank_same) and (gstin is None or feat["gstin_matches_master"] == 1.0)
                     and feat["currency_matches_master"] == 1.0)

        rows.append({"doc_id": doc["doc_id"], "vendor_id": doc["vendor_id"], "visual": doc["visual"],
                     "injection": doc["injection"], "amount_inr": _to_inr(doc["total"], doc["currency"]),
                     "features": feat, "labels": labels, "b0": b0_accept, "b2": b2_accept,
                     "seconds": ex["seconds"]})

        # What the system records once the invoice is reviewed: the true
        # vendor and amounts. Only correct invoices use up the PO balance.
        key = doc["vendor_id"] if doc["injection"] != "lookalike_vendor" else "new:" + normalize_vendor_name(doc["vendor_name"])
        history[key].append({"total": doc["total"], "date": date.fromisoformat(doc["document_date"]),
                             "number": doc["document_number"]})
        if doc["injection"] is None and doc.get("po_id") in cand_by_id:
            cand = cand_by_id[doc["po_id"]]
            for li in doc["invoice_lines"]:
                k = next((pl.line_no for pl in cand.lines if pl.description == li["description"]), None)
                if k is not None:
                    cand.invoiced_qty[k] = cand.invoiced_qty.get(k, 0) + li["quantity"]
            cand.invoiced_amount = round(cand.invoiced_amount + doc["total"], 2)
    return rows


# -------------------------------------------------------------------- evaluate

def _matrix(rows, groups):
    names = [n for g in groups for n in FEATURE_GROUPS[g]]
    return np.array([[r["features"][n] for n in names] for r in rows], dtype=float), names


def vendor_splits(rows, n_splits, seed):
    """Vendor-grouped 50 / 25 / 25 train / calibration / test, so every
    test vendor is unseen (and its invoices aren't split across sets)."""
    vendors = sorted({r["vendor_id"] for r in rows})
    splits = []
    for s in range(n_splits):
        rng = np.random.default_rng(seed * 1000 + s)
        perm = rng.permutation(vendors)
        n = len(perm)
        groups = {"train": set(perm[: n // 2]), "cal": set(perm[n // 2: 3 * n // 4]), "test": set(perm[3 * n // 4:])}
        splits.append({k: np.array([r["vendor_id"] in v for r in rows]) for k, v in groups.items()})
    return splits


def run_systems(rows, splits, alphas, calibrators=("logistic", "hgb"), with_fc=True, feature_sets=None):
    from app.services.selective_gate import Gate, aurc, ece, fit_calibrator, selective_metrics

    y = np.array([r["labels"]["correct"] for r in rows], dtype=int)
    wrong = 1 - y
    amounts = np.array([r["amount_inr"] for r in rows])
    feature_sets = feature_sets or {"B1": ["document"], "P": CORE_GROUPS, "P+dup": list(FEATURE_GROUPS)}
    mats = {name: _matrix(rows, groups)[0] for name, groups in feature_sets.items()}
    b0 = np.array([r["b0"] for r in rows])
    b2 = np.array([r["b2"] for r in rows])
    comps = ["vendor", "total", "currency", "number", "business"]
    comp_y = {c: np.array([r["labels"][c] for r in rows], dtype=int) for c in comps}
    results = defaultdict(list)  # (system, alpha) -> per-split metrics
    accepted_wrong = defaultdict(list)

    t_start = time.time()
    for si, sp in enumerate(splits):
        if si % 5 == 0:
            print(f"    split {si + 1}/{len(splits)} ({time.time() - t_start:.0f} s)", flush=True)
        tr, ca, te = sp["train"], sp["cal"], sp["test"]
        for name, rule in (("B0", b0), ("B2", b2)):
            m = selective_metrics(rule[te], wrong[te])
            m["value_at_risk_inr"] = float(amounts[te][rule[te] & (wrong[te] == 1)].sum())
            for a in alphas:
                results[(name, a)].append(m | {"violation": m["risk"] > a})
        for fs, X in mats.items():
            for kind in calibrators:
                model = fit_calibrator(X[tr], y[tr], kind, seed=si)
                for a in alphas:
                    gate = Gate.from_model(model, X[tr], X[ca], y[ca], alpha=a, delta=DELTA)
                    s = gate.scores(X[te])
                    acc = s >= gate.threshold
                    m = selective_metrics(acc, wrong[te], a)
                    m.update(threshold=gate.threshold, aurc=aurc(s, wrong[te]), ece=ece(s, y[te]),
                             brier=float(np.mean((s - y[te]) ** 2)),
                             value_at_risk_inr=float(amounts[te][acc & (wrong[te] == 1)].sum()))
                    try:
                        from sklearn.metrics import roc_auc_score
                        m["auroc"] = float(roc_auc_score(y[te], s))
                    except ValueError:
                        m["auroc"] = None
                    results[(f"{fs}-{kind}", a)].append(m)
                    if fs == "P+dup" and kind == "hgb" and a == SECONDARY_ALPHA:
                        idx = np.where(te)[0][acc & (wrong[te] == 1)]
                        accepted_wrong[si] = [rows[i]["doc_id"] for i in idx]
        if with_fc:
            X = mats["P"]
            comp_models = {c: fit_calibrator(X[tr], comp_y[c][tr], "logistic", seed=si) for c in comps}
            for a in alphas:
                acc = np.ones(te.sum(), dtype=bool)
                for c in comps:
                    gate = Gate.from_model(comp_models[c], X[tr], X[ca], comp_y[c][ca], alpha=a / len(comps), delta=DELTA)
                    acc &= gate.accept(X[te])
                m = selective_metrics(acc, wrong[te], a)
                m["value_at_risk_inr"] = float(amounts[te][acc & (wrong[te] == 1)].sum())
                results[("FC-logistic", a)].append(m)
    return results, accepted_wrong


def summarize(per_split: list) -> dict:
    out = {"splits": len(per_split)}
    for k in ("coverage", "risk", "aurc", "auroc", "ece", "brier", "value_at_risk_inr"):
        vals = [m[k] for m in per_split if m.get(k) is not None and not (isinstance(m[k], float) and math.isnan(m[k]))]
        if vals:
            out[k] = {"mean": float(np.mean(vals)), "sd": float(np.std(vals)), "min": float(np.min(vals)),
                      "max": float(np.max(vals))}
    if any("violation" in m for m in per_split):
        out["violation_rate"] = float(np.mean([m["violation"] for m in per_split]))
    return out


def bootstrap_diff(a: list, b: list, n: int = 10000, seed: int = 0) -> dict:
    """Mean paired difference over splits with a percentile bootstrap 95 % CI."""
    d = np.array(a) - np.array(b)
    rng = np.random.default_rng(seed)
    boots = rng.choice(d, size=(n, len(d)), replace=True).mean(axis=1)
    return {"mean": float(d.mean()), "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]}


def cmd_evaluate(args):
    from app.services.vendor_matching import normalize_vendor_name  # noqa: F401  (config warm-up)

    out_dir = os.path.join(DATA_DIR, f"seed{args.seed}")
    with open(os.path.join(out_dir, "world.json")) as f:
        world = json.load(f)
    extraction = {}
    with open(os.path.join(out_dir, "extraction.jsonl")) as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                extraction[r["doc_id"]] = r
    missing = [d["doc_id"] for d in world["documents"] if d["doc_id"] not in extraction]
    if missing:
        sys.exit(f"{len(missing)} documents not read yet; run `extract` first")

    t0 = time.time()
    rows = compute_evidence(world, extraction)
    evidence_ms = (time.time() - t0) / len(rows) * 1000
    splits = vendor_splits(rows, N_SPLITS, args.seed)
    print(f"evidence for {len(rows)} documents ({evidence_ms:.1f} ms each); running {N_SPLITS} splits", flush=True)
    results, accepted_wrong = run_systems(rows, splits, ALPHAS)

    summary = {f"{name}@{a}": summarize(v) for (name, a), v in results.items()}
    comparisons = {}
    for a in ALPHAS:
        cov = lambda name: [m["coverage"] for m in results[(name, a)]]  # noqa: E731
        comparisons[f"alpha={a}"] = {
            "P-B1 (logistic)": bootstrap_diff(cov("P-logistic"), cov("B1-logistic")),
            "P-B1 (hgb)": bootstrap_diff(cov("P-hgb"), cov("B1-hgb")),
            "P-B2 (logistic)": bootstrap_diff(cov("P-logistic"), cov("B2")),
            "P-FC (logistic)": bootstrap_diff(cov("P-logistic"), cov("FC-logistic")),
            "P+dup - P (logistic, exploratory)": bootstrap_diff(cov("P+dup-logistic"), cov("P-logistic")),
        }

    # RS-07: ablation (P without one evidence group)
    ablation = {}
    sets = {f"P-minus-{g}": [x for x in CORE_GROUPS if x != g] for g in ENTERPRISE_GROUPS}
    abl, _ = run_systems(rows, splits, (SECONDARY_ALPHA,), calibrators=("logistic",), with_fc=False, feature_sets=sets)
    for (name, a), v in abl.items():
        if name.startswith("P-minus"):
            ablation[name.replace("-logistic", "")] = summarize(v)
    # RQ3: stale master data
    robustness = {}
    for noise in (0.0, 0.05, 0.1, 0.2, 0.4):
        noisy = rows if noise == 0 else compute_evidence(world, extraction, noise=noise, noise_seed=args.seed)
        res, _ = run_systems(noisy, splits, (SECONDARY_ALPHA,), calibrators=("logistic",), with_fc=False)
        robustness[str(noise)] = {
            "P": summarize(res[("P-logistic", SECONDARY_ALPHA)]), "B1": summarize(res[("B1-logistic", SECONDARY_ALPHA)]),
            "P+dup": summarize(res[("P+dup-logistic", SECONDARY_ALPHA)]),
            "B2": summarize(res[("B2", SECONDARY_ALPHA)]),
            "P-B1": bootstrap_diff([m["coverage"] for m in res[("P-logistic", SECONDARY_ALPHA)]],
                                   [m["coverage"] for m in res[("B1-logistic", SECONDARY_ALPHA)]]),
        }

    # RS-09: what P accepted wrongly (alpha = 2 %, logistic), across splits
    by_id = {r["doc_id"]: r for r in rows}
    failures = Counter()
    examples = []
    for si, ids in accepted_wrong.items():
        for i in ids:
            r = by_id[i]
            bad = [c for c in ("vendor", "total", "currency", "number") if not r["labels"][c]]
            failures[(r["injection"] or "none", r["visual"], ",".join(bad) or "-")] += 1
            if len(examples) < 15:
                examples.append({"split": si, "doc_id": i, "injection": r["injection"], "visual": r["visual"],
                                 "misread": bad, "p_features": {k: round(v, 3) for k, v in r["features"].items()
                                                                if k in ("overall_conf", "vendor_score", "po_matched",
                                                                         "bank_differs", "is_duplicate")}})

    y = np.array([r["labels"]["correct"] for r in rows])
    dataset = {
        "documents": len(rows), "vendors": len({r["vendor_id"] for r in rows}),
        "correct_share": float(y.mean()),
        "fields_read_right_share": float(np.mean([r["labels"]["fields"] for r in rows])),
        "injections": dict(Counter(r["injection"] or "none" for r in rows)),
        "visual": dict(Counter(r["visual"] for r in rows)),
        "correct_by_visual": {v: float(np.mean([r["labels"]["correct"] for r in rows if r["visual"] == v]))
                              for v in sorted({r["visual"] for r in rows})},
        "fields_right_by_visual": {v: float(np.mean([r["labels"]["fields"] for r in rows if r["visual"] == v]))
                                   for v in sorted({r["visual"] for r in rows})},
        "extraction_seconds_median_by_visual": {
            v: float(np.median([r["seconds"] for r in rows if r["visual"] == v])) for v in sorted({r["visual"] for r in rows})},
        "evidence_ms_per_document": evidence_ms,
    }
    commit = os.environ.get("GIT_COMMIT")  # git refuses a repo mounted from the host; pass it in
    if not commit:
        try:
            commit = subprocess.run(["git", "-C", REPO_ROOT, "rev-parse", "--short", "HEAD"], capture_output=True,
                                    text=True).stdout.strip() or None
        except OSError:
            commit = None
    out = {
        "generated": time.strftime("%Y-%m-%d %H:%M"), "git_commit": commit,
        "config": {"seed": args.seed, "generator_version": GENERATOR_VERSION, "alphas": ALPHAS, "delta": DELTA,
                   "splits": N_SPLITS, "split": "vendor-grouped 50/25/25 train/calibration/test",
                   "secondary_alpha": SECONDARY_ALPHA, "failure_analysis_system": "P+dup-hgb",
                   "feature_groups": FEATURE_GROUPS},
        "dataset": dataset, "systems": summary, "comparisons": comparisons, "ablation": ablation,
        "robustness": robustness,
        "failures": [{"injection": k[0], "visual": k[1], "misread": k[2], "count": n}
                                           for k, n in failures.most_common()],
        "failure_examples": examples,
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "selective.json"), "w") as f:
        json.dump(out, f, indent=2)
    with open(os.path.join(RESULTS_DIR, "selective.md"), "w") as f:
        f.write(render_markdown(out))
    print(f"wrote docs/results/selective.json and selective.md ({time.time() - t0:.0f} s)")


def render_markdown(r: dict) -> str:
    pct = lambda x: f"{100 * x:.1f} %"  # noqa: E731
    s, ds, cfg = r["systems"], r["dataset"], r["config"]

    def row(name, a):
        m = s.get(f"{name}@{a}")
        if not m:
            return None
        auroc = m.get("auroc", {}).get("mean")
        a_rc = m.get("aurc", {}).get("mean")
        return (f"| {name} | {pct(m['coverage']['mean'])} ± {pct(m['coverage']['sd'])} | {pct(m['risk']['mean'])} "
                f"(max {pct(m['risk']['max'])}) | {pct(m.get('violation_rate', 0))} | "
                f"{'' if auroc is None else f'{auroc:.3f}'} | {'' if a_rc is None else f'{a_rc:.3f}'} | "
                f"₹{m['value_at_risk_inr']['mean'] / 1e5:,.1f} L |")

    out = [
        "# Selective automation: results",
        "",
        f"Generated {r['generated']} by `services/document-vendor-agent/scripts/eval_selective.py` "
        f"(commit `{r['git_commit']}`, generator {cfg['generator_version']}, seed {cfg['seed']}). "
        "Every number below is in `selective.json`. Plan and hypotheses: "
        "[../RESEARCH_PAPER_PLAN.md](../RESEARCH_PAPER_PLAN.md).",
        "",
        "## Setup",
        "",
        f"- **Data**: {ds['documents']} synthetic invoices from {ds['vendors']} vendors (procurement-world "
        "generator), each against a purchase order in a generated ledger; "
        f"{pct(1 - ds['injections'].get('none', 0) / ds['documents'])} carry an injected business error. "
        f"Visual conditions: {', '.join(f'{k} {v}' for k, v in sorted(ds['visual'].items()))}.",
        "- **Reading**: the production code (pdfplumber for text PDFs, PaddleOCR for images, the ML "
        "classifier, the field extractor), run in-process, not through Kafka and the database.",
        "- **Enterprise evidence**: computed against the generated vendor master, PO ledger and invoice "
        "history with the production rules (vendor matching, the ledger's three-way match, duplicate "
        "detection, GSTIN check digit, bank details vs master).",
        "- **Correct** = vendor, total, currency and invoice number read right and no business error. "
        f"{pct(ds['correct_share'])} of documents are correct; fields are read right on "
        f"{pct(ds['fields_read_right_share'])}.",
        f"- **Splits**: {cfg['splits']} × {cfg['split']} (test vendors never seen in training or calibration). "
        f"Gates: Learn-then-Test, δ = {cfg['delta']}.",
        "",
        "## RQ1 / RQ2: coverage at a fixed document-level error budget",
        "",
        "Coverage = share of test invoices accepted without review. Risk = share of accepted invoices that are "
        "wrong (target ≤ α). Violation = share of splits where risk > α (target ≤ δ = 10 %). "
        "Value at risk = rupee total of wrongly accepted invoices per test set (L = lakh).",
        "",
    ]
    for a in cfg["alphas"]:
        out += [f"### α = {pct(a)}", "",
                "| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |",
                "|---|---|---|---|---|---|---|"]
        for name in ("B0", "B2", "B1-logistic", "B1-hgb", "P-logistic", "P-hgb", "FC-logistic",
                     "P+dup-logistic", "P+dup-hgb"):
            line = row(name, a)
            if line:
                out.append(line)
        c = r["comparisons"][f"alpha={a}"]
        out += ["", "Paired differences in coverage over the splits (95 % bootstrap CI):", ""]
        for k, v in c.items():
            out.append(f"- {k}: {100 * v['mean']:+.1f} pp [{100 * v['ci95'][0]:+.1f}, {100 * v['ci95'][1]:+.1f}]")
        out.append("")
    out += ["B0 and B2 are fixed rules with no α: the same accept set is scored against every α.", "",
            f"## Ablation (P, logistic, α = {pct(cfg['secondary_alpha'])})", "",
            "| Without | Coverage | Risk | Violations | AUROC |", "|---|---|---|---|---|"]
    for name, m in r["ablation"].items():
        out.append(f"| {name.replace('P-minus-', '')} | {pct(m['coverage']['mean'])} | {pct(m['risk']['mean'])} | "
                   f"{pct(m.get('violation_rate', 0))} | {m['auroc']['mean']:.3f} |")
    out += ["", f"## RQ3: stale master data (α = {pct(cfg['secondary_alpha'])})", "",
            "A share of vendors have out-of-date bank details and no GSTIN on file, and the same share of POs is "
            "missing from the ledger.", "",
            "| Stale share | P coverage | P risk | P violations | P AUROC | P+dup coverage | B1 coverage | P − B1 (95 % CI) |",
            "|---|---|---|---|---|---|---|---|"]
    for noise, m in r["robustness"].items():
        d = m["P-B1"]
        out.append(f"| {pct(float(noise))} | {pct(m['P']['coverage']['mean'])} | {pct(m['P']['risk']['mean'])} | "
                   f"{pct(m['P'].get('violation_rate', 0))} | {m['P']['auroc']['mean']:.3f} | "
                   f"{pct(m['P+dup']['coverage']['mean'])} | {pct(m['B1']['coverage']['mean'])} | "
                   f"{100 * d['mean']:+.1f} pp [{100 * d['ci95'][0]:+.1f}, {100 * d['ci95'][1]:+.1f}] |")
    out += ["", f"## Failure analysis ({cfg['failure_analysis_system']}, α = {pct(cfg['secondary_alpha'])}, all splits)", ""]
    if r["failures"]:
        out += ["| Injected error | Visual | Fields misread | Count |", "|---|---|---|---|"]
        out += [f"| {f['injection']} | {f['visual']} | {f['misread']} | {f['count']} |"
                for f in r["failures"][:15]]
    else:
        out.append("No accepted-but-wrong invoices.")
    out += ["", "## Reading quality and cost", "", "| Visual | Fields read right | Correct | Median read time |",
            "|---|---|---|---|"]
    for v in sorted(ds["visual"]):
        out.append(f"| {v} | {pct(ds['fields_right_by_visual'][v])} | {pct(ds['correct_by_visual'][v])} | "
                   f"{ds['extraction_seconds_median_by_visual'][v]:.2f} s |")
    out += ["", f"Enterprise evidence adds {ds['evidence_ms_per_document']:.1f} ms per document (in memory).", "",
            "## Limitations", "",
            "- Synthetic documents and enterprise records: one generator, one family of layouts, "
            "injected errors at chosen rates. External validity on public invoices (RS-08) is not done.",
            "- Reading runs in-process; the live pipeline's Docling path for scanned PDFs and the LayoutLMv3 "
            "cross-check are not part of the evidence.",
            "- The reviewer is an oracle: history and ledger record the true values after review.",
            "- Splits are by vendor; time drift and recalibration (RQ4, RS-10) are not studied.", ""]
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["extract", "evaluate"])
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--vendors", type=int, default=100)
    p.add_argument("--invoices", type=int, default=3000)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    {"extract": cmd_extract, "evaluate": cmd_evaluate}[args.stage](args)


if __name__ == "__main__":
    main()
