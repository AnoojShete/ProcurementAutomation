#!/usr/bin/env python3
"""Field-level extraction accuracy on the synthetic corpus, with and
without image preprocessing (BR-2 / FR-11).

Run inside the document-vendor-agent image, from /app:
  python scripts/eval_extraction.py --data /data --out /out
where /data is data/synthetic-invoices (manifest.json = ground truth).

Image documents are also tested as harder variants made here — rotated
4°, noisy, half resolution — since real scans are rarely clean. PDFs with
a text layer don't go through OCR, so they're scored once as a baseline.
Writes extraction.json and extraction.md.
"""
import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.classification import classify_document  # noqa: E402
from app.services.field_extraction import extract_fields  # noqa: E402
from app.services.ocr import _text_from_image_paddleocr, extract_text  # noqa: E402
from app.services.preprocess import preprocess_image  # noqa: E402

FIELDS = ["doc_type", "vendor", "document_number", "document_date", "total", "currency"]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def score(truth: dict, text: str) -> dict:
    fields, _ = extract_fields(text, document_type=truth["doc_type"])
    got_type = classify_document(text).document_type
    vendor = _norm(fields.vendor_name_raw or "")
    tv = _norm(truth["vendor_name"])
    return {
        "doc_type": got_type == truth["doc_type"],
        "vendor": bool(vendor) and (tv in vendor or vendor in tv),
        "document_number": (fields.document_number or "").strip().upper() == truth["document_number"].upper(),
        "document_date": fields.document_date == truth["document_date"],
        "total": fields.total is not None and abs(float(fields.total) - float(truth["total"])) < 0.01,
        "currency": (fields.currency or "") == truth["currency"],
    }


def _encode(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def variants(data: bytes) -> dict:
    """The original plus harder copies of an image document."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    rot = cv2.warpAffine(img, cv2.getRotationMatrix2D((w / 2, h / 2), 4, 1.0), (w, h),
                         borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    rng = np.random.default_rng(7)
    noisy = np.clip(img.astype(np.int16) + rng.normal(0, 28, img.shape).astype(np.int16), 0, 255).astype(np.uint8)
    small = cv2.resize(img, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    return {"original": data, "rotated_4deg": _encode(rot), "noisy": _encode(noisy), "half_resolution": _encode(small)}


def ocr(data: bytes, preprocess: bool) -> tuple[str, float, dict]:
    steps = {}
    if preprocess:
        data, steps = preprocess_image(data)
    text, quality, _ = _text_from_image_paddleocr(data)
    return text, quality, steps


def evaluate(data_dir: str) -> dict:
    manifest = json.load(open(os.path.join(data_dir, "manifest.json")))["documents"]
    rows = []
    for truth in manifest:
        path = os.path.join(data_dir, truth["filename"])
        raw = open(path, "rb").read()
        if truth["filename"].lower().endswith(".pdf"):
            started = time.time()
            text = extract_text(raw, truth["filename"], "application/pdf").text
            rows.append({"file": truth["filename"], "kind": "pdf", "variant": "original", "preprocess": None,
                         "fields": score(truth, text), "seconds": round(time.time() - started, 1)})
            continue
        for name, data in variants(raw).items():
            for pre in (False, True):
                started = time.time()
                text, quality, steps = ocr(data, pre)
                rows.append({"file": truth["filename"], "kind": "image", "variant": name, "preprocess": pre,
                             "ocr_confidence": quality, "steps": steps, "fields": score(truth, text),
                             "seconds": round(time.time() - started, 1)})
            print(f"{truth['filename']} {name}: without {sum(rows[-2]['fields'].values())}/6, "
                  f"with {sum(rows[-1]['fields'].values())}/6", flush=True)
    return summarise(rows)


def accuracy(rows: list) -> dict:
    if not rows:
        return {}
    out = {f: round(sum(r["fields"][f] for r in rows) / len(rows), 3) for f in FIELDS}
    out["all_fields"] = round(sum(sum(r["fields"].values()) for r in rows) / (len(rows) * len(FIELDS)), 3)
    out["documents"] = len(rows)
    return out


def summarise(rows: list) -> dict:
    images = [r for r in rows if r["kind"] == "image"]
    by_variant = {}
    for v in ("original", "rotated_4deg", "noisy", "half_resolution"):
        by_variant[v] = {"without": accuracy([r for r in images if r["variant"] == v and not r["preprocess"]]),
                         "with": accuracy([r for r in images if r["variant"] == v and r["preprocess"]])}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pdfs": accuracy([r for r in rows if r["kind"] == "pdf"]),
        "images_without_preprocessing": accuracy([r for r in images if not r["preprocess"]]),
        "images_with_preprocessing": accuracy([r for r in images if r["preprocess"]]),
        "by_variant": by_variant,
        "rows": rows,
    }


def to_markdown(r: dict) -> str:
    def pct(x):
        return f"{x * 100:.0f} %" if isinstance(x, (int, float)) else "—"
    head = "| | " + " | ".join(FIELDS) + " | all fields |"
    sep = "|---" * (len(FIELDS) + 2) + "|"
    def line(label, a):
        return f"| {label} | " + " | ".join(pct(a.get(f)) for f in FIELDS) + f" | **{pct(a.get('all_fields'))}** |"
    lines = [
        "# Extraction accuracy", "",
        f"Generated {r['generated_at']} by `services/document-vendor-agent/scripts/eval_extraction.py` on "
        "`data/synthetic-invoices` (ground truth in `manifest.json`). Image documents are also tested as "
        "rotated (4°), noisy and half-resolution copies.", "",
        "## Overall", "", head, sep,
        line(f"PDFs ({r['pdfs'].get('documents', 0)})", r["pdfs"]),
        line(f"Images, no preprocessing ({r['images_without_preprocessing'].get('documents', 0)})", r["images_without_preprocessing"]),
        line(f"Images, with preprocessing ({r['images_with_preprocessing'].get('documents', 0)})", r["images_with_preprocessing"]),
        "", "## Images by variant (all fields)", "",
        "| Variant | Without preprocessing | With preprocessing |", "|---|---|---|",
        *[f"| {v.replace('_', ' ')} | {pct(d['without'].get('all_fields'))} | {pct(d['with'].get('all_fields'))} |"
          for v, d in r["by_variant"].items()], "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/data")
    ap.add_argument("--out", default="/out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    result = evaluate(a.data)
    json.dump(result, open(os.path.join(a.out, "extraction.json"), "w"), indent=2)
    open(os.path.join(a.out, "extraction.md"), "w").write(to_markdown(result))
    for k in ("pdfs", "images_without_preprocessing", "images_with_preprocessing"):
        print(k, result[k])


if __name__ == "__main__":
    main()
