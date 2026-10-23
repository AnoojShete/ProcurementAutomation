# Checklist status

Review of the *Project Deliverables and Implementation Checklist* against the
`main` branch, 23 Oct 2026. Where each item lives in the code:
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
| F | MkDocs site | Partially done | Builds cleanly; **not yet published to GitHub Pages** (repo owner: Actions → Docs → Run workflow) |

## Expected deliverables

| # | Deliverable | Remark |
|---|---|---|
| 1–7 | Workflow, document lifecycle, notifications, contract/e-sign, Control Panel, both diagrams | Done |
| 8 | Presentation slides | Done (share and rehearse) |
| 9 | Standardised documentation | Done |
| 10 | MkDocs site | Partially done (not published) |

## Issues found in this review

- **Stale image:** notification-agent's image was built before the SMTP-settings
  commit added `cryptography`, so its tests failed to start and the running service
  was out of date. Rebuilt; after any change to a service's `requirements.txt`,
  rebuild that service.
- **Escalation emails** went to the level that missed its SLA, as a placeholder
  address, with a generic subject. Fixed (see A2).
- **SMTP encryption key (needs a decision):** compose doesn't pass
  `SMTP_ENCRYPTION_SECRET` to notification-agent, so saved company SMTP passwords
  are encrypted with the default key in `shared/security/encryption.py`, which is
  public in the repo and not refused in production. Pass a real secret before any
  shared deployment, then re-save the SMTP password (old ones won't decrypt).
- **Test data** from these checks is still in the stack (`checklist_*` and
  `recheck_*` files). Run `./scripts/reset-demo.sh` before the review.
- **Tests (23 Oct):** 1,276 service tests pass, plus 165 + 14 root tests; frontend typecheck and `mkdocs build --strict` are clean.
