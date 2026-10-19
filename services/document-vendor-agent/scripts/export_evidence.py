"""Export the evidence the live pipeline recorded, one row per document and
one per (document, field) (research task RS-01). Read-only.

    docker compose exec -T document-vendor-agent python scripts/export_evidence.py > evidence.jsonl
    docker compose exec -T document-vendor-agent python scripts/export_evidence.py --fields > fields.jsonl

Per document: what was read (type, totals, confidences), each pipeline
stage's confidence / status / warning count from pipeline_checkpoints, the
duplicate flag, the three-way match result and the review outcome (how
many fields a reviewer corrected; `label_correct` is true when a reviewer
looked at it and changed nothing). Per field: the extracted value, its
confidence, and the reviewer's correction from extraction_feedback.

The study itself (scripts/eval_selective.py) runs on generated documents
with known ground truth; this export is for the live data, e.g. to check
that the generated evidence looks like the real one, and for RS-11.
"""
import argparse
import json
import os
import sys

import psycopg2
import psycopg2.extras

STAGES = ["parsing_agent", "classification_agent", "field_extraction_agent", "layoutlm_crosscheck_agent",
          "vendor_matching_agent", "currency_agent", "invoice_matching_agent", "duplicate_detection_agent",
          "vendor_learning_agent", "confidence_agent"]
FIELDS = ["vendor_name", "document_number", "document_date", "total", "line_items"]


def _dsn() -> str:
    url = os.environ.get("APP_DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/postgres")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _num(v):
    return float(v) if v is not None else None


def document_rows(cur):
    cur.execute("""
        SELECT d.id, d.document_type, d.file_type, d.source, d.vendor_id, d.total, d.total_inr, d.currency,
               d.overall_confidence, d.confidence, d.needs_review, d.is_likely_duplicate, d.extracted,
               d.created_at, im.status AS match_status, im.payment_hold,
               ro.fields_corrected, ro.reviewed_at
        FROM documents d
        LEFT JOIN invoice_matches im ON im.document_id = d.id
        LEFT JOIN review_outcomes ro ON ro.document_id = d.id
        WHERE d.status = 'classified'
        ORDER BY d.created_at
    """)
    docs = cur.fetchall()
    cur.execute("SELECT document_id, agent_name, confidence, validation_status, "
                "jsonb_array_length(COALESCE(warnings, '[]'::jsonb)) AS n_warnings, duration_ms "
                "FROM pipeline_checkpoints")
    stages = {}
    for c in cur.fetchall():
        stages.setdefault(str(c["document_id"]), {})[c["agent_name"]] = c
    for d in docs:
        st = stages.get(str(d["id"]), {})
        extracted = d["extracted"] or {}
        row = {
            "document_id": str(d["id"]), "document_type": d["document_type"], "file_type": d["file_type"],
            "source": d["source"], "vendor_id": str(d["vendor_id"]) if d["vendor_id"] else None,
            "total": _num(d["total"]), "total_inr": _num(d["total_inr"]), "currency": d["currency"],
            "overall_confidence": _num(d["overall_confidence"]), "confidence_scores": d["confidence"] or {},
            "needs_review": d["needs_review"], "is_duplicate": d["is_likely_duplicate"],
            "amount_check": (extracted.get("amount_check") or {}).get("status"),
            "po_reference": extracted.get("po_reference"), "match_status": d["match_status"],
            "payment_hold": d["payment_hold"], "created_at": d["created_at"].isoformat(),
            "reviewed": d["reviewed_at"] is not None, "fields_corrected": d["fields_corrected"],
            "label_correct": (d["fields_corrected"] == 0) if d["reviewed_at"] is not None else None,
        }
        for name in STAGES:
            s = st.get(name)
            row[f"{name}.confidence"] = _num(s["confidence"]) if s else None
            row[f"{name}.status"] = s["validation_status"] if s else None
            row[f"{name}.warnings"] = s["n_warnings"] if s else None
            row[f"{name}.ms"] = _num(s["duration_ms"]) if s else None
        yield row


def field_rows(cur):
    cur.execute("SELECT document_id, field, original_value, corrected_value, label FROM extraction_feedback")
    corrections = {(str(r["document_id"]), r["field"]): r for r in cur.fetchall()}
    cur.execute("SELECT id, extracted, confidence FROM documents WHERE status = 'classified' ORDER BY created_at")
    for d in cur.fetchall():
        extracted, conf = d["extracted"] or {}, d["confidence"] or {}
        for f in FIELDS:
            key = "vendor_name_raw" if f == "vendor_name" else f
            c = corrections.get((str(d["id"]), f)) or corrections.get((str(d["id"]), key))
            yield {"document_id": str(d["id"]), "field": f, "value": extracted.get(key),
                   "confidence": conf.get(f), "corrected": c is not None,
                   "corrected_value": c["corrected_value"] if c else None, "label": c["label"] if c else None}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fields", action="store_true", help="one row per (document, field) instead of per document")
    args = p.parse_args()
    with psycopg2.connect(_dsn()) as conn:
        conn.set_session(readonly=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            rows = field_rows(cur) if args.fields else document_rows(cur)
            n = 0
            for row in rows:
                sys.stdout.write(json.dumps(row, default=str) + "\n")
                n += 1
    print(f"{n} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
