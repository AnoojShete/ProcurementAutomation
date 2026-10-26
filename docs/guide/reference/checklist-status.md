# Checklist status

Review of the *Project Deliverables and Implementation Checklist* against the
`main` branch, 23 Oct 2026; re-checked 25 Oct after the Oct 24 merges. Where each item lives in the code:
[Final checklist](checklist.md).

## A. End-to-end workflow

| # | Checklist item | Remark | Notes |
|---|---|---|---|
| A1 | Input, Processed and Failed folders | Done | `./inbox/input`, `processed/`, `failed/`. Re-checked live: quote → processed, blank scan → failed |
| A1 | Folder watcher sends documents to Kafka | Done | Polls every 3 s; publishes `document.ingested` |
| A1 | Failure reasons and logs captured | Done | `<file>.error.txt` (file, time, document id, reason) |
| A1 | Processing status per document | Done | Control Panel → Documents |
| A2 | Email notifications at every approval stage | Done | Each level's approvers, reminders, escalation, outcome, signer, vendor. Escalation fixed 23 Oct: the next level was never asked. Unit-tested only, not run live (needs an SLA to expire). Levels with nobody assigned still go to placeholder addresses |
| A3 | Templates created, viewed and edited in the Control Panel | Done | Control Panel → Notifications |
| A3 | Subject, body, recipient and placeholders editable without code changes | Done | Placeholders checked on save; a broken edit falls back to the original |
| A4 | Contract generated after approval | Done | Only after the final approval level |
| A4 | Sent for e-signature by email | Done | Signer gets a signing link |
| A4 | Signature status tracked automatically | Done | Built-in e-signature only; not a legally recognised provider |
| A5 | Unsigned/signed PDFs with status in the Control Panel | Done | *Pending E-Signature* / *E-Signature Complete* |
| A5 | No need to open MinIO or the e-sign site | Done | |
| A6 | Extracted fields, confidence, validation, exceptions | Done | Document page |
| A7 | Structured Control Panel with status indicators and error details | Done | 8 sections, plus Email Settings (added 22 Oct) |

## B–F. Diagrams, slides, documentation

| # | Checklist item | Remark | Notes |
|---|---|---|---|
| B | System architecture diagram | Done | `docs/assets/architecture.svg` |
| C | Functional flow diagram | Done | `docs/assets/functional-flow.svg`. Too tall for one slide; the deck redraws it as five cards |
| D | Presentation slides | Done | 16 slides, claude.ai Slides artifact. Private until shared; team still to rehearse |
| E | Standardised documentation | Done | Follows the Overall Documentation Template v2 and the agent template |
| F | MkDocs site | Done | Published 23 Oct at <https://anoojshete.github.io/ProcurementAutomation/>; `mkdocs build --strict` clean on 25 Oct. Republish after doc changes (Actions → Docs → Run workflow, tick deploy) |

## Expected deliverables

| # | Deliverable | Remark |
|---|---|---|
| 1–7 | Workflow, document lifecycle, notifications, contract/e-sign, Control Panel, both diagrams | Done |
| 8 | Presentation slides | Done (share and rehearse) |
| 9 | Standardised documentation | Done |
| 10 | MkDocs site | Done (published; republish after changes) |

## Issues found in this review

- **Stale image:** notification-agent's image was built before the SMTP-settings
  commit added `cryptography`, so its tests failed to start and the running service
  was out of date. Rebuilt; after any change to a service's `requirements.txt`,
  rebuild that service.
- **Escalation emails** went to the level that missed its SLA, as a placeholder
  address, with a generic subject. Fixed (see A2).
- **SMTP encryption key (needs a decision):** since 24 Oct a missing key stops
  the service outside development, but `shared/security/encryption.py` reads a
  missing `APP_ENV` as development, so it can still fall back to a key that is
  public in the repo. Set `APP_ENV=production` and `MASTER_ENCRYPTION_KEY`
  (32+ characters) before any shared deployment, then re-save the SMTP password.
- **Test data** from these checks is still in the stack (`checklist_*` and
  `recheck_*` files). Run `./scripts/reset-demo.sh` before the review.
- **Re-check after the Oct 24 merges (25 Oct):** the running images predated
  the bulk-approval change, and once rebuilt the merge broke contract
  generation and auto-send (missing imports, uncommitted risk-check sessions),
  approval and contract e-mails (wrong users table) and the request list for
  admin and finance. All fixed, each with a test that fails without the fix.
  Bulk and e-mail approval now check a vendor's clearance with the internal
  service token (they got 401 before). The signing-mandate password is
  re-checked by auth-service (it called the wrong port), and the daily
  batch-approval digest email is built, so its four rules now apply.
- **Tests (25 Oct):** 1,330 service tests pass, plus 169 + 14 root tests; invoice lifecycle 71/71 and the demo script 28/28 through the gateway; frontend typecheck and `mkdocs build --strict` are clean.
