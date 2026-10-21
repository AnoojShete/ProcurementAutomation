# Document & Vendor agent

## 1. Introduction

**Business problem.** Quotes, invoices and purchase orders arrive as PDFs,
scans and photos. Retyping them is slow and error-prone, and fraud (fake
invoices, changed bank details, look-alike vendors) hides in the paperwork.

**Objectives.** Take documents in from any channel, read them, decide what
they are, extract their fields with a confidence for each, validate them,
match the vendor, and send to a person only what needs a person.

| Input | Output |
|---|---|
| A PDF / PNG / JPEG by upload, email or the `./inbox/input` folder | A classified document with extracted fields, confidences and validation results; the event `document.classified`; the file moved to `processed/` or `failed/` |

## 2. Technical implementation

| Part | Detail |
|---|---|
| Components | API (`app/api/documents.py`, `vendors.py`, `control_panel.py`), worker (`app/worker.py`): Kafka consumer, drop-folder watcher (`inbox_watcher.py`), email intake (`email_intake.py`), pipeline (`services/pipeline.py`) |
| AI models | pdfplumber (text PDFs), Docling (scans), PaddleOCR (images, deskew + upscale), TF-IDF + logistic regression classifier (keywords as fallback), LayoutLMv3 cross-check |
| Storage | MinIO for files; tables `documents`, `pipeline_checkpoints`, `vendors`, `vendor_payment_change_requests`, `email_intake` |
| API | `/api/documents/*` (upload, list, detail, file, validation, review), `/api/vendors/*`, `/api/gst/*`, `/api/admin/control-panel/*` |
| Communication | Publishes `document.ingested`, `document.classified`, `vendor.matched`, `vendor.payment_details_flagged`, `reminder.due`; calls approval-inventory `POST /invoices/match` |
| Deployment | Docker image shared by API and worker; ClamAV and MinIO required; models cached in a volume (`./scripts/download-models.sh`) |

## 3. Functional implementation

1. **Intake**: type checked from the bytes, size ≤ 25 MB, ClamAV scan (fails
   closed), stored in MinIO, `documents` row and `document.ingested` in one transaction.
2. **Drop folder**: the worker polls `./inbox/input` every 3 s, claims a file once
   its size is stable, uploads it like a UI upload, holds it until the pipeline
   ends, then moves it to `processed/` or `failed/` (with `.error.txt`: file, time,
   document id, reason).
3. **Read**: in a separate process with a 120 s limit; no text → `failed` with a
   readable reason.
4. **Classify** (quote / invoice / PO / other) and **extract** fields with
   per-field confidence; LayoutLMv3 cross-checks.
5. **Validate**: vendor match (look-alike names flagged, first-seen bank details
   held for a second person), currency → INR, GST and e-invoice QR, invoice
   ledger match, duplicates.
6. **Decide**: overall confidence < 80 % or any flag → review queue; otherwise
   automatic. Each stage's result is stored (`pipeline_checkpoints`) and shown on
   the document page.
7. **Exceptions**: a dependency down → back to `pending`, retried after 1–4 min,
   `failed` after 5 attempts; a sweep re-queues stranded documents every minute.

## 4. Results and evaluation

| Measure | Result | Source |
|---|---|---|
| Classifier (held-out document kinds) | Macro-F1 1.00 vs keywords 0.84 | `docs/results/classifier.md` |
| Extraction, text PDFs | 100 % of fields | `docs/results/extraction.md` |
| Extraction, images | ~49 % of documents fully right (with preprocessing) | same |
| Tests | 373 unit/integration tests; `document_pipeline.py` e2e (corrupt, empty, huge, wrong type, outages) | `scripts/test-service.sh` |

![Extracted fields and validation results](../showcase/cpanel/06-extraction.png)

**Limitations.** Poor phone photos are read correctly only about half the
time; those go to review. **Improvement:** the research study's calibrated
gate would let more clean invoices skip review at a guaranteed error rate.
