"""Document pipeline end to end: real files through upload -> scan ->
storage -> outbox -> Kafka -> worker -> extraction -> matching -> events,
checking the actual data at every layer, not just HTTP codes.

Covers: a normal invoice; a large scan just under the 25 MiB limit; a file
over the limit; a corrupt PDF; an empty file; a blank page; a ZIP and a PNG
renamed .pdf; a PDF crafted to be extremely slow to parse; the same upload
twice (Idempotency-Key, and without a key); the worker, Kafka and the
invoice ledger (approval-inventory-agent) each being down mid-flight.

Asserts: each document ends in the right final state with a readable
message; stored bytes equal uploaded bytes; rejected uploads leave no row
and no file; no document is left pending/processing; no event is left
unsent; no unexpected traceback in the pipeline's logs.

Needs the stack running (./run.sh) and the Docker CLI (for DB/log checks
and for stopping services). Takes ~6 minutes. Usage:
    python tests/e2e/document_pipeline.py            # everything
    python tests/e2e/document_pipeline.py --quick    # skip the outage scenarios
Requires: requests, reportlab, pillow.
"""
import io
import json
import os
import random
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import date

import requests
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "services", "document-vendor-agent", "scripts"))
from synthetic_invoice_lib import build_pdf_bytes, render_document  # noqa: E402

GW = os.getenv("GATEWAY", "http://localhost:8080") + "/api"
PASSWORD = "DemoPass123!"
LIMIT = 25 * 1024 * 1024
EXTRACTION_TIMEOUT = 120

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    return bool(cond)


def step(title):
    print(f"\n── {title}")


# ── infrastructure helpers ─────────────────────────────────────────────

def sh(cmd, timeout=120):
    return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=timeout).stdout.strip()


def sql(query):
    return sh(f"docker compose exec -T postgres psql -U postgres -tAF'|' -c {json.dumps(query)}")


def stored_bytes(minio_path):
    bucket, _, key = (minio_path or "").partition("/")
    code = f"from app.services.storage import get_minio_client as g; print(g().stat_object({bucket!r}, {key!r}).size)"
    out = sh(f"docker compose exec -T document-vendor-agent python -c {json.dumps(code)}")
    return int(out) if out.isdigit() else None


def minio_objects():
    code = "from app.services.storage import get_minio_client as g; print(sum(1 for _ in g().list_objects('documents', recursive=True)))"
    out = sh(f"docker compose exec -T document-vendor-agent python -c {json.dumps(code)}")
    return int(out) if out.isdigit() else -1


def service(action, name):
    sh(f"docker compose {action} {name}", timeout=300)
    if action == "start":
        for _ in range(90):
            status = sh(f"docker compose ps --format '{{{{.Status}}}}' {name}")
            if "(healthy)" in status or (status.startswith("Up") and "health" not in status):
                break
            time.sleep(2)
        sh("docker compose restart nginx")  # nginx re-resolves upstreams
        time.sleep(2)


# ── API helpers ────────────────────────────────────────────────────────

def login(role="requester"):
    r = requests.post(f"{GW}/auth/login", json={"email": f"{role}@demo.example.com", "password": PASSWORD})
    return r.json()["data"]["access_token"]


def upload(token, name, data, key=None):
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    r = requests.post(f"{GW}/documents/upload", headers=headers, files={"file": (name, data, "application/pdf")}, timeout=120)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:200]}
    return r.status_code, body


def doc_row(doc_id):
    cols = ["status", "document_type", "vendor_name_raw", "total", "needs_review", "is_likely_duplicate",
            "duplicate_of_document_id", "error_message", "minio_path", "processing_attempts"]
    row = sql(f"select {', '.join(f'coalesce({c}::text, {chr(39)}{chr(39)})' for c in cols)} from documents where id='{doc_id}'")
    return dict(zip(cols, row.split("|"))) if row else {}


def wait_final(doc_id, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = doc_row(doc_id)
        if row.get("status") in ("classified", "failed"):
            return row
        time.sleep(1)
    return doc_row(doc_id)


def outbox(doc_id):
    return sql("select string_agg(topic || case when published_at is null then '(UNSENT)' else '' end, ',' "
               f"order by created_at) from event_outbox where event::text like '%{doc_id}%'")


# ── test files ─────────────────────────────────────────────────────────

RUN = uuid.uuid4().hex[:6].upper()
RNG = random.Random(RUN)
VENDOR = {"name": f"Brightline Office Systems {RUN} Pvt Ltd", "currency": "INR"}
ITEMS = [{"name": "Ergonomic Chair", "quantity": 4, "unit_price": 12500.0},
         {"name": "Standing Desk", "quantity": 2, "unit_price": 38900.0}]


def invoice(number):
    lines, total = render_document(RNG, "invoice", "A", VENDOR, ITEMS, number, date.today(), "Acme Corp IT Department")
    return build_pdf_bytes(lines), total


def scan_pdf(side, number, inline=False):
    img = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Courier", 10)
    y = 800
    for line in render_document(RNG, "invoice", "A", VENDOR, ITEMS, number, date.today(), "Acme Corp IT Department")[0]:
        c.drawString(50, y, line)
        y -= 16
    c.showPage()
    if inline:  # image inside the page content: pdfminer decodes it in pure Python (very slow)
        c.drawInlineImage(img, 40, 200, 500, 500)
    else:
        c.drawImage(ImageReader(img), 40, 200, 500, 500)
    c.showPage()
    c.save()
    return buf.getvalue()


def near_limit_scan():
    side = 2400
    for _ in range(8):
        data = scan_pdf(side, f"INV-{RUN}-L")
        if LIMIT - 800_000 < len(data) < LIMIT - 1_000:
            return data, side
        side = int(side * ((LIMIT - 300_000) / len(data)) ** 0.5)
    return data, side


def blank_pdf():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.showPage()
    c.save()
    return buf.getvalue()


# ── the test ───────────────────────────────────────────────────────────

def main():
    quick = "--quick" in sys.argv
    started = int(time.time())
    tok = login()
    happy, happy_total = invoice(f"INV-{RUN}-01")
    accepted = {}  # doc_id -> (name, bytes, expectation)

    step("Rejected at upload — must leave no row and no stored file")
    rows0, objs0 = int(sql("select count(*) from documents")), minio_objects()
    large, side = near_limit_scan()
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("invoice.txt", "not a pdf")
    png = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(png, "PNG")
    rejected = [
        ("over_limit.pdf", scan_pdf(int(side * 1.04), f"INV-{RUN}-X"), 413, "too large"),
        ("empty.pdf", b"", 400, "empty"),
        ("zip_renamed.pdf", zbuf.getvalue(), 415, "unsupported file type"),
        ("png_renamed.pdf", png.getvalue(), 415, "name says .pdf"),
    ]
    for name, data, code, phrase in rejected:
        status, body = upload(tok, name, data)
        msg = json.dumps(body)
        check(f"{name} ({len(data):,} B) -> {code} with a clear message", status == code and phrase in msg, f"{status} {msg[:120]}")
    check("rejected uploads created no documents", int(sql("select count(*) from documents")) == rows0)
    check("rejected uploads stored no files", minio_objects() == objs0)

    step("Accepted uploads")
    cases = [
        ("happy_invoice.pdf", happy, "classified"),
        ("large_scan_under_limit.pdf", large, "classified"),
        ("corrupt.pdf", happy[: len(happy) // 3] + os.urandom(2000), "failed:damaged or incomplete"),
        ("blank_page.pdf", blank_pdf(), "failed:couldn't find any text"),
        ("slow_to_parse.pdf", scan_pdf(int((((24_300_000 / 1.272) - 400_000) / 3) ** 0.5), f"INV-{RUN}-S", inline=True),
         f"failed:within {EXTRACTION_TIMEOUT} seconds"),
    ]
    for name, data, expect in cases:
        status, body = upload(tok, name, data)
        if check(f"{name} ({len(data):,} B) accepted -> 201", status == 201, f"{status} {json.dumps(body)[:120]}"):
            accepted[body["data"]["document_id"]] = (name, data, expect)

    step("Same file twice")
    key = f"e2e-{RUN}"
    s1, b1 = upload(tok, "happy_again.pdf", happy, key=key)
    s2, b2 = upload(tok, "happy_again.pdf", happy, key=key)
    check("same Idempotency-Key -> same document, one row",
          s1 == s2 == 201 and b1["data"]["document_id"] == b2["data"]["document_id"], f"{s1} {s2}")
    accepted[b1["data"]["document_id"]] = ("happy_again.pdf (dup, keyed)", happy, "classified:duplicate")

    step("Final states (the slow file is stopped at the extraction time limit)")
    happy_id = next(d for d, v in accepted.items() if v[0] == "happy_invoice.pdf")
    for doc_id, (name, data, expect) in accepted.items():
        row = wait_final(doc_id, timeout=EXTRACTION_TIMEOUT + 120)
        want_status, _, detail = expect.partition(":")
        ok = row.get("status") == want_status
        if want_status == "failed":
            ok = ok and detail in row.get("error_message", "")
        check(f"{name}: {expect}", ok, f"{row.get('status')} {row.get('error_message', '')[:90]}")
        size = stored_bytes(row.get("minio_path"))
        check(f"{name}: stored file is byte-identical ({len(data):,} B)", size == len(data), f"stored={size}")
        if want_status == "classified":
            if detail == "duplicate":
                # Processed side by side, either copy may be seen first;
                # exactly one must be flagged, pointing at the other.
                first = doc_row(happy_id)
                pair = [(row, doc_id, happy_id), (first, happy_id, doc_id)]
                flagged = [(r, of) for r, me, of in pair if r["is_likely_duplicate"] == "true"]
                check(f"{name}: exactly one of the two copies flagged as a duplicate of the other",
                      len(flagged) == 1 and flagged[0][0]["duplicate_of_document_id"] == flagged[0][1],
                      [(r["is_likely_duplicate"], r["duplicate_of_document_id"][:8]) for r, _, _ in pair])
            else:
                check(f"{name}: vendor and total read correctly",
                      row["vendor_name_raw"] == VENDOR["name"] and abs(float(row["total"] or 0) - happy_total) < 0.01,
                      f"{row['vendor_name_raw']!r} {row['total']}")
            check(f"{name}: all 9 pipeline stages recorded",
                  sql(f"select count(*) from pipeline_checkpoints where document_id='{doc_id}'") == "9")
            check(f"{name}: events published (ingested, classified, vendor.matched)",
                  set(outbox(doc_id).split(",")) >= {"document.ingested", "document.classified", "vendor.matched"}
                  and "UNSENT" not in outbox(doc_id), outbox(doc_id))
            check(f"{name}: no leftover error message", row["error_message"] == "", row["error_message"])
        else:
            check(f"{name}: no vendor created, no downstream events",
                  outbox(doc_id) == "document.ingested" and row.get("vendor_name_raw", "") == "", outbox(doc_id))
            check(f"{name}: failure is in the audit trail",
                  "failed" in sql(f"select string_agg(action, ',') from audit_log where entity_id='{doc_id}'"))
        visible = requests.get(f"{GW}/documents/{doc_id}", headers={"Authorization": f"Bearer {tok}"}).json()["data"]
        check(f"{name}: uploader sees the same state via the API", visible["status"] == want_status)

    if not quick:
        step("Dependencies down mid-flight")
        outages = [
            ("worker stopped", "document-vendor-agent-worker", "pending", ""),
            ("Kafka stopped", "redpanda", "pending", "document.ingested(UNSENT)"),
            ("invoice ledger stopped", "approval-inventory-agent", "pending", ""),
        ]
        for label, svc, during, during_outbox in outages:
            service("stop", svc)
            data, _ = invoice(f"INV-{RUN}-{svc[:4].upper()}")
            status, body = upload(tok, f"outage_{svc}.pdf", data)
            check(f"{label}: upload still accepted", status == 201, f"{status} {json.dumps(body)[:100]}")
            doc_id = body.get("data", {}).get("document_id")
            time.sleep(15)
            row = doc_row(doc_id)
            check(f"{label}: document waits as '{during}' (not failed, not lost)", row.get("status") == during,
                  f"{row.get('status')} {row.get('error_message', '')[:80]}")
            if during_outbox:
                check(f"{label}: event held in the outbox", outbox(doc_id) == during_outbox, outbox(doc_id))
            service("start", svc)
            if svc == "redpanda":
                # Every Kafka client reconnects; give the consumer groups a moment.
                time.sleep(10)
            tok = login()
            row = wait_final(doc_id, timeout=420)
            check(f"{label}: processed after it came back", row.get("status") == "classified",
                  f"{row.get('status')} {row.get('error_message', '')[:80]}")
            check(f"{label}: stored file intact", stored_bytes(row.get("minio_path")) == len(data))

    step("Nothing left behind")
    since = f"{started}"
    stuck = sql(f"select count(*) from documents where status in ('pending', 'processing') "
                f"and uploaded_at > to_timestamp({started})")
    check("no document stuck pending/processing", stuck == "0", stuck)
    unsent = sql(f"select count(*) from event_outbox where published_at is null and created_at > to_timestamp({started})")
    check("no event left unsent in the outbox", unsent == "0", unsent)
    missing = [d for d in accepted if stored_bytes(doc_row(d).get("minio_path")) is None]
    check("every document row has its stored file", not missing, missing)
    tracebacks = sh(f"docker compose logs --since {since} document-vendor-agent document-vendor-agent-worker 2>&1 "
                    "| grep -c Traceback")
    check("no unexpected traceback in the pipeline's logs", tracebacks == "0", f"{tracebacks} tracebacks")

    passed = sum(ok for _, ok in results)
    print(f"\n{'=' * 66}\n  document pipeline: {passed} passed, {len(results) - passed} failed\n{'=' * 66}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
