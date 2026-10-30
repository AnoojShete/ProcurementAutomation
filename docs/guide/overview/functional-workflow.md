# Functional workflow

<div class="figure-flow" markdown>
[![Functional flow from document ingestion to signed contract, with decision points and failure paths](../assets/functional-flow.svg)](../assets/functional-flow.svg)
</div>

*Figure 2. Functional flow. Yellow: inputs; purple: automated steps; blue:
decisions; pink: a person acts; red: failure or stop; green: success.
Click the diagram to open it full size. Source: `docs/assets/functional-flow.mmd`,
rendered by `scripts/render_diagrams.py`.*

## Steps and decisions

| # | Step | Decision / exception | Outcome |
|---|---|---|---|
| 1 | **Ingestion**: upload, intake mailbox or `./inbox/input` | Allowed type, size, virus-free? | No → rejected; a drop-folder file moves to `failed/` with a `.error.txt` |
| 2 | **Read**: pdfplumber, Docling or PaddleOCR | Any text? Finished within 120 s? | No → document `failed` with the reason; drop-folder file → `failed/` |
| 3 | **Classify and extract**: quote / invoice / PO / other, fields with confidence | | |
| 4 | **Validate**: vendor match, currency, GST, duplicates, invoice match | Confidence ≥ 80 % and no flags? | No → manual review queue |
| 5 | **Route**: quotes start a purchase request; invoices are matched to orders | Spend tier (business rule) | ≤ ₹500 auto-approved; ≤ ₹5,000 manager; above, manager + finance |
| 6 | **Approve**: each level's approvers are emailed | Decided before the SLA? | Reminders at 50 % / 80 %; escalation on breach; rejection ends the request |
| 7 | **Contract**: generated from the template with the approved data | Vendor cleared? | Sanctions match or prohibited country → signing blocked; High band or checks still incomplete → signer must acknowledge |
| 8 | **E-signature**: signer emailed a signing link | Signed? | Reminder after 3 days |
| 9 | **Store and track**: signed PDF and certificate kept; request → *ordered* | | Requester and vendor emailed; Control Panel shows *E-Signature Complete* |

## Status transitions

| Item | Statuses |
|---|---|
| Document | `pending` → `processing` → `classified` (or `failed`); retried after an outage, `failed` after 5 attempts |
| Drop-folder file | `input/` → `.processing/` → `processed/` or `failed/` |
| Purchase request | `pending_approval` → `approved` / `rejected` → `ordered` → `partially_received` / `fulfilled` → `partially_invoiced` / `invoice_received` |
| Contract | `draft` → `pending_signature` → `signed` (later `terminated` / `expired`) |

Purchase-request transitions are enforced by a state machine
(`shared/lifecycle.py`) and a database check constraint.
