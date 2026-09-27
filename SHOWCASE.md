# IT Procurement Intelligence Platform — Showcase

For someone evaluating the project: what it does, what makes it
technically solid, how to demo it, and honest answers to likely
questions. State as of **Sep 27, 2026**. Setup and reference:
[README.md](README.md). Open items: [TODO.md](TODO.md).

## The pitch

IT procurement is manual glue work: someone reads an invoice and types it
in, chases an approver, drafts a contract, checks whether the vendor is
trustworthy, and a year later nobody notices half the SaaS seats are
unused. We built five cooperating services ("agents"), each owning one
part of that lifecycle and reacting to each other's events, so a document
uploaded at one end flows through approval, contracting, risk scoring and
notifications without anyone copying data between systems. People step in
where judgement is needed: low-confidence extractions, approvals,
signatures, flagged payments.

```
 upload invoice/PO/quote ─► document-vendor-agent ─┐
 purchase request ───────► approval-inventory-agent ├── Kafka events ──► notification-agent ─► email
 approved request ───────► contract-risk-agent ─────┘
 auth-service: accounts, roles, business rules · one nginx gateway · one React app
```

## What each agent does

**document-vendor-agent** (Vaidehi, with Niraj). Uploads are virus-scanned
(ClamAV) and type-checked by content, stored in MinIO, and processed by a
worker: text extraction (pdfplumber / Docling / PaddleOCR) in a separate,
time-limited process → keyword classification (PO / invoice / quote) →
field extraction → optional LayoutLMv3 cross-check → vendor matching and
India-specific vetting (GSTIN checksum + optional live lookup, IFSC) →
invoice ledger match → duplicate check → confidence scoring, with
low-confidence documents sent to a review queue. It learns vendor-specific
field labels from reviewers' corrections.

**approval-inventory-agent** (Niraj). Spend-tier routing (auto / manager /
manager + finance, thresholds editable live), a Temporal workflow per
request with SLA escalation, an approval authority matrix with separation
of duties, inventory with backorder splits, and license intelligence: an
IsolationForest scores each SaaS license's usage, SHAP explains why, and
anomalous licenses get a reclaim request with a grace period. It also
keeps the invoice ledger (line-level three-way match) and an hourly order
summary.

**contract-risk-agent** (Anjali). Contracts from templates (text and PDF),
clause extraction, e-signature through an HMAC-signed, replay-protected
webhook (or Documenso when configured), signed-copy download, renewal
reminders, a RandomForest vendor-risk model tracked in MLflow with
per-vendor explanations and a weekly drift check, and vendor offboarding
that flags contracts for reconciliation instead of deleting anything.

**notification-agent** (Anooj). Listens to 11 event types, renders a
template per event (strict, so a missing field fails loudly), sends urgent
mail immediately and batches the rest into digests, and keeps a searchable
log. Delivers to Mailpit, the local mail catcher.

**auth-service** (Anooj; accounts by Anjali). Sign-up with email
confirmation, login, logout and "sign out everywhere", forgot / reset /
change password, admin user management, four roles, and a business-rules
engine: 28 tunable rules (spend tiers, SLA hours, confidence and anomaly
thresholds…) edited live with a change history.

## What makes it technically strong

**Reliable event handling.** Events are written to an outbox table in the
same database transaction as the change they describe, then relayed to
Kafka, so a crash can't commit a change and lose its event. Consumers
retry, then park failures in a dead-letter table that can be replayed.
Purchase-request status changes go through a state machine (a late
"invoice matched" can't resurrect a rejected request), and a reconciler
repairs requests left inconsistent.

**A document pipeline built for bad input.** Tested with corrupt, empty,
blank, oversized, renamed (ZIP/PNG as `.pdf`) and deliberately slow-to-parse
files, duplicates, and outages of Kafka, the worker and the ledger. Each
ends in a clear state with a readable message; a stuck document is swept
and retried with growing delays; a slow file can't block the worker
because extraction runs in a killable child process.

**Fraud controls a finance team would recognise.** Dual control on bank
details (the person who uploads a change can't verify it); first-seen bank
details and lookalike vendor names ("At1asslan" for Atlassian) put the
invoice on payment hold; line-level three-way matching with 1 %
tolerances; duplicate-invoice detection; separation of duties on
approvals; everything audit-logged.

**Security.** Passwords hashed with argon2id; email links single-use,
expiring and stored only as hashes; no way to tell from the answers
whether an address has an account; lockout after repeated wrong passwords;
per-IP rate limits at the gateway; refresh token in an httpOnly cookie with
CSRF protection; identity always taken from the login token, never the
request body; role checks on every endpoint; each service logs in to
Kafka with its own account and may only use its own topics; uploads
virus-scanned and failing closed; published default secrets refused
outside development; every port but the gateway bound to localhost.

**Testing.** Measured on a fresh clone on Sep 27: 409 service unit tests
+ 116 root tests; end-to-end scripts against the running system —
`make e2e` 17/17, account flows 42/42 (reading real emails from Mailpit),
and an invoice lifecycle through all five agents with no database
shortcuts, 63/63 with the LayoutLMv3 model downloaded. Security fixes
were checked by reverting each one and confirming a test fails. Writing
these tests found real bugs (invoice matching never worked; approvals
could be lost in a race; account emails and the e-sign webhook broke on a
fresh install).

**Observability.** Prometheus metrics on every service, a provisioned
Grafana dashboard (rates, latency, errors, Kafka lag), JSON logs, Temporal
UI for workflow history, MLflow for model runs.

## Honest status

- **Broken right now:** processing an invoice from a vendor seen for the
  first time — a database constraint added on Sep 26 rejects the ledger
  booking (TODO.md P0). Quotes, POs and invoices from known vendors are
  unaffected.
- **Simulated / partial:** e-signatures are simulated unless Documenso is
  configured (the Documenso client has only been tested against mocks);
  notification emails go to Mailpit only; the ML document classifier
  isn't trained, so classification is keyword-based; images don't OCR on
  Apple Silicon; all ML runs on synthetic data.
- **Not a production deployment:** CI only builds images, no resource
  limits, several images unpinned, dependency upgrades pending on the
  upload path.

## Demo script

### Before the demo

```bash
./run.sh
./scripts/seed-demo-data.sh
./scripts/download-models.sh             # once per machine
make e2e                                 # expect 17 passed, 0 failed
python tests/e2e/invoice_lifecycle.py    # expect 63 passed (wait a minute after make e2e)
```

- [ ] `docker compose ps clamav` shows healthy.
- [ ] Log in as each role once; upload one document (the first one is
      slow while models load, ~45 s).
- [ ] Licenses page shows 2 anomalous / 2 watch / 1 normal.
- [ ] Keep Mailpit (http://localhost:8025) open.
- [ ] Until the P0 is fixed, don't demo an invoice from a brand-new vendor
      (including the Controls → Payment protection lookalike scenario).

### Walkthrough (~10 min)

1. **Sign up** at `/signup` with a new address, open the confirmation
   email in Mailpit, confirm, sign in. Show "Forgot password?" and the
   lockout message after five wrong passwords.
2. **Requester → New Request.** The 5-step wizard; attach
   `data/synthetic-invoices/02_quote_delltechnologiesindi_QT-2026-00003.pdf`
   and point out live pipeline status, detected type *quote*, per-field
   confidence. Submit about ₹2,500 (manager tier).
3. **Documents.** Extracted fields and confidence; upload the same file
   again to show the duplicate flag. Optional: upload the EICAR test file
   (`printf '%s' 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' > /tmp/eicar.pdf`)
   — rejected as malware.
4. **Approver → Approval Inbox.** Approve; the status flips a moment later
   (Temporal workflow).
5. **Admin → Contracts.** Generate from the approved request, send for
   signature, sign, download the signed copy.
6. **Risk.** Recompute the vendor's risk: band and top factors.
7. **Licenses.** 2 anomalous, 2 watch, 1 normal, about ₹3.4 lakh potential
   annual savings; open one for SHAP reasons and the usage trend.
8. **Admin → Business Rules** (change a tier limit, show history),
   **Users** (promote the account from step 1), **System Health**.
9. **Mailpit, Grafana** (http://localhost:3000), **Temporal UI**
   (http://localhost:8088).

### Controls page (~6 min, admin)

1. **Event reliability**: send an out-of-order "invoice matched" for an
   unapproved request → lands in the dead-letter table with the reason;
   the outbox shows nothing waiting.
2. **Approval authority**: "approve my own request" → blocked (separation
   of duties).
3. **Invoice matching**: simulate an invoice 2 % over the agreed unit
   price → held for review.
4. **Learning**: three invoices from one vendor; correct the total on two,
   the third arrives pre-filled from the learned label. (Uses the ledger —
   check it after the P0 fix.)
5. **Payment protection** (lookalike vendor): after the P0 fix.

If something breaks live, `make e2e` walks the whole chain in about 30
seconds.

## Likely questions

**What makes it "agentic" rather than microservices?** Each agent owns a
goal and decides on its own — classify this document, send it for review,
route a request, start a license reclaim, flag a risky vendor — and they
coordinate through events rather than a central script, handing off to a
person when confidence is low.

**Where is ML used?** Document understanding (Docling layout parsing,
PaddleOCR, LayoutLMv3 cross-check), license-usage anomaly detection
(IsolationForest + SHAP), vendor risk (RandomForest + drift check), fuzzy
vendor matching. Document classification is keyword-based today. Rules do
what must be predictable: approval tiers, dual control.

**Why not an LLM for everything?** Cost, speed, determinism and
auditability; a small model with SHAP reasons or a rule with a change
history is easier to defend to an auditor.

**Why Kafka / Temporal / one Postgres?** Kafka so agents don't call each
other and can be down independently; Temporal because approvals and
renewals run for days with timers and retries; one Postgres to keep a
4-person project simple, with each service owning its tables and
migrations (the trade-off is coupling — the current P0 is exactly that).

**How are passwords and logins protected?** argon2id hashing, lockout,
rate limits, email confirmation, single-use expiring reset links, a
refresh cookie JavaScript can't read, sessions ended everywhere on a
password change. We can show the database holds only hashes.

**Can anything on the network fake an event?** Not without that service's
Kafka password: the broker enforces per-service permissions, and a test
keeps the permission table in sync with the code.

**Is the ML any good?** It works mechanically and explains itself, but it's
trained on synthetic data and not measured on real data; one license at
76 % utilisation currently scores as anomalous, which needs tuning.

**Is it production-ready?** No. It's a working, tested prototype with
production patterns. Before production: fix the P0, run tests in CI,
resource limits, pinned images, dependency upgrades, real email for
notifications, real e-sign integration.

## URLs and logins

App http://localhost:8080 · Mailpit :8025 · Grafana :3000 (admin/admin) ·
Temporal UI :8088 · MLflow :5050 · MinIO console :9001
(minioadmin/minioadmin) · Prometheus :9090. Demo accounts, password
`DemoPass123!`: `requester@`, `approver@`, `finance@`, `admin@demo.example.com`.
