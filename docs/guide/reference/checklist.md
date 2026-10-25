# Final checklist

Where each item of the *Project Deliverables and Implementation Checklist*
is implemented, and how it was checked (21 Oct 2026; re-checked 23 Oct, see
[Checklist status](checklist-status.md)).

## A. End-to-end workflow

| Item | Implemented in | Checked by |
|---|---|---|
| **A1** Input, Processed, Failed folders | `./inbox/input`, `./inbox/processed`, `./inbox/failed` (`inbox_watcher.py`) | Live: a quote → `processed/`, a blank scan → `failed/` with the pipeline's reason, a `.txt` → `failed/` (unsupported type) |
| A1 Folder watcher feeding Kafka | Worker polls every 3 s; each file becomes `document.ingested` | `test_drop_folder.py` |
| A1 Failure reasons and logs | `<file>.error.txt` (file, time, document id, reason); worker log; Control Panel → Documents | `TestSettle` |
| A1 Processing status per document | Control Panel → Documents (stage per file); document page | Screenshot `cpanel/02-documents.png` |
| **A2** Notifications at every approval stage | Each level's approvers asked (real people from the approval authority); SLA reminders; on escalation the next level is asked; outcome to the requester; signer asked; vendor told when signed | `test_expansion_notifications.py`; live two-level request: finance emailed after the manager approved |
| **A3** Templates managed in the Control Panel | Control Panel → Notifications: create, view, edit, preview, turn off, restore | `test_template_store.py`; live edit received in Mailpit by signer and copy recipient |
| A3 Subject, body, recipient, placeholders | All four editable; placeholders checked on save | same |
| **A4** Contract generated after approval | After the **final** approval level, from the template and the approved data | `TestContractOnlyAfterFinalApproval`; live two-level request |
| A4 Sent for signature by email | Signer receives "Please sign" with a link to the signing page | `test_templates.py`; live in Mailpit |
| A4 Signature status tracked automatically | `pending_signature` → `signed`; request → *ordered*; requester and vendor emailed | `invoice_lifecycle.py` 71/71 |
| **A5** Unsigned / signed PDFs with status in the Control Panel | Control Panel → Contracts and e-signatures: *Pending E-Signature* / *E-Signature Complete* | `TestEsignTracking`; signed PDF downloaded live |
| A5 No need for MinIO or the e-sign site | PDFs fetched through the app | — |
| **A6** Extracted fields, confidence, validation, exceptions | Document page: every field with its confidence; validation result of each pipeline stage with errors and warnings; failure reason | Screenshot `cpanel/06-extraction.png` |
| **A7** Structured Control Panel | Sections: Overview, Documents, Processing and logs, Approvals, Notifications, Contracts and e-signatures, Storage, Administration; status badges and error details everywhere | Screenshots `cpanel/*` |

## B–F. Diagrams, slides and documentation

| Item | Where |
|---|---|
| **B** System architecture diagram | [System architecture](../overview/architecture.md), `docs/assets/architecture.svg/.png` (generated from the code's structure) |
| **C** Functional flow diagram | [Functional workflow](../overview/functional-workflow.md), `docs/assets/functional-flow.svg/.png` (decisions, failure paths, status transitions) |
| **D** Presentation slides | See the slide deck shared with the team (outline: problem, solution, architecture, flow, features, stack, results, demo) |
| **E** Standardised documentation | This site: project pages follow the overall template; every agent page follows the four-part agent template |
| **F** MkDocs site | `mkdocs.yml`, `docs/guide/`, [About these docs](docs-site.md) |

## Expected deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | End-to-end workflow | Done, checked live and by `invoice_lifecycle.py` |
| 2 | Document lifecycle | Done |
| 3 | Notification management | Done |
| 4 | Contract and e-signature integration | Done (built-in e-signature) |
| 5 | Centralised Control Panel | Done |
| 6 | System architecture diagram | Done |
| 7 | Functional flow diagram | Done |
| 8 | Presentation slides | Done (team to rehearse) |
| 9 | Standardised documentation | Done |
| 10 | MkDocs documentation site | Done: builds cleanly, published on GitHub Pages 23 Oct (republish after changes) |
