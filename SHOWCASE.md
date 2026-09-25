# IT Procurement Intelligence Platform — Showcase Guide

The presentation-facing summary: what's built, how finished it is, how to
demo it, what comes next, and answers to the questions we're likely to get.
State as of **Sep 25, 2026** (the `anjali` branch after merging `anooj2`).
For the full technical reference see [README.md](README.md).

> **ClamAV malware scanning: ADDED BACK.** Removed by Niraj on Sep 24
> because it took 2–3 min to start; re-added by Anjali on Sep 25 on a
> native image that's healthy in **about 5 seconds** (measured; the target
> was under 20s). Every upload is scanned; if ClamAV is down, uploads are
> refused rather than let through.

---

## 0. The 30-second pitch

IT procurement is mostly manual glue work: someone reads an invoice, types
it into a system, chases an approver on email, drafts a contract from a
template, checks whether the vendor is trustworthy, and a year later nobody
notices half the SaaS seats are unused.

We built **five cooperating AI agents** that each own one part of that
lifecycle and talk to each other through events, so a document uploaded at
one end flows through approval, contracting, risk scoring and notifications
without a human copying data between systems. Humans only step in where
judgment is needed: low-confidence extractions, approvals, signatures and
flagged risks.

```
 upload invoice/PO/quote ─► document-vendor-agent ─┐
                                                    │  Kafka events
 purchase request ───────► approval-inventory-agent ├──────────────► notification-agent ─► email
                                                    │
 approved request ───────► contract-risk-agent ─────┘
                           (contract, e-sign, vendor risk)

 auth-service: login, roles, business rules  ·  one gateway (nginx) · one React frontend
```

---

## 1. What's built — per agent

| # | Agent | Owner | Core job | Estimate |
|---|---|---|---|---|
| 1 | document-vendor-agent | Vaidehi (+ Niraj) | Read documents, classify, extract, match/vet vendors | **~85%** |
| 2 | approval-inventory-agent | Niraj | Spend-tier approvals, inventory, license intelligence | **~90%** |
| 3 | contract-risk-agent | Anjali | Contracts, e-signature, vendor risk ML | **~60%** |
| 4 | notification-agent | Anooj | Event-driven email | **~90%** |
| 5 | auth-service | Anooj (+ Niraj) | JWT auth, roles, business-rules engine | **~95%** |

Percentages are against the **full** spec each agent was given, including
stretch goals that need paid or rate-limited external services. They're our
own estimates, not a measurement.

### Agent 1 — document-vendor-agent (~85%)

**Built**
- Upload → object storage (MinIO) → a **six-stage agent pipeline**, each
  stage passing a JSON "envelope" to the next: parsing → classification →
  field extraction → vendor matching → duplicate detection → confidence scoring.
- **Parsing**: Docling (layout-aware PDF parsing that keeps tables intact)
  with a pdfplumber fallback; **PaddleOCR** for scanned images, run in a
  separate subprocess so a native crash can't take the worker down.
- **LayoutLMv3 cross-check**: a document-understanding model second-guesses
  the extracted fields; every model choice and fallback is logged
  (`model_routing_log`, visible on the System Health page).
- **Doc-type aware**: invoices, POs and quotes each take their own path
  (quotes go to a `vendor_quotes` table; invoices are 3-way matched against
  approved POs).
- **Vendor vetting (India-specific)**: GSTIN format + checksum + optional
  live registry lookup, IFSC bank-code validation, spend-based vendor
  tiers (petty < ₹5k, standard < ₹50k, full vetting above).
- **Malware scanning (ClamAV)**: every upload is scanned before it's
  stored. Infected files are rejected and audit-logged; if the scanner is
  down, uploads are refused (fail closed).
- **Controls**: duplicate-invoice detection, confidence-gated human review
  queue (below 0.8 → review), and **dual control on vendor bank-detail
  changes** (the person who submits a change can never also approve it —
  classic payment-fraud control).

**Not done / next**
- `uploaded_by` still comes from the form, not the login token.
- No screen yet for finance to approve a bank-detail change (API exists).

### Agent 2 — approval-inventory-agent (~90%)

**Built**
- **Spend-tier routing**: ≤ ₹500 auto-approved, ₹500–5,000 needs a manager,
  > ₹5,000 needs manager + finance. Thresholds live in the business-rules
  engine and can be edited live by an admin.
- A **Temporal workflow per request**: waits for each approver, escalates
  automatically if the SLA (48h) is breached.
- **Inventory**: Redis locks prevent double-booking stock; short stock
  splits into "fulfil now" + "backorder".
- **License intelligence (ML)**: reads SSO login logs, and an
  **IsolationForest** anomaly model scores each SaaS license 0–1, with
  **SHAP** explaining the top reasons ("days since last login",
  "utilisation ratio"...). Anomalous licenses trigger a **reclaim**
  workflow with a 7-day grace period and a 45-day cooldown; users can
  decline. The Licenses page shows scores, trends and estimated savings.

**Not done / next**
- The inventory lock isn't released after a successful reservation (only
  on a 5-minute timeout), and the approval step doesn't yet check that the
  approver is the one assigned to that level.
- The anomaly model's ranking needs tuning (see Q&A: "Is the ML any good?").

### Agent 3 — contract-risk-agent (~60%)

**Built**
- Contract generation from templates (hardware / SaaS / services), then
  **clause extraction** on the generated text (renewal type, notice period,
  end date) with a regex → keyword fallback router.
- Renewal reminders via a long-running Temporal timer.
- **E-signature**: choice of provider in the UI (Documenso recommended,
  DocuSign sandbox), and a real **HMAC-signed, replay-protected webhook**
  that marks the contract signed. Covered by unit and e2e tests.
- **Vendor risk ML**: scikit-learn RandomForest trained on a documented
  synthetic dataset, tracked in **MLflow**, returns a Low/Medium/High band
  with per-vendor contributing factors; a weekly **drift monitor** (PSI)
  flags when live scores stop looking like training data.
- Vendor offboarding: revokes access, flags contracts for human
  reconciliation, never deletes records.

**Not done / next**: this is our biggest gap.
- The call *to* the e-sign provider is still simulated (we generate a
  reference id). The webhook coming back is real.
- Real external risk data (OpenCorporates, SEC EDGAR, ISO certs, SSL
  grade), sanctions screening (OFAC / OpenSanctions), and validating clause
  extraction against the CUAD benchmark.
- Renewal reminders count from the contract end date, not the notice deadline.

### Agent 4 — notification-agent (~90%)

**Built**: listens to 11 event types, renders an email template per event
(strict mode, so a missing field fails loudly rather than sending a blank
email), sends urgent emails immediately and batches the rest into digests,
and keeps a searchable log. Includes a fraud alert when vendor bank details change.

**Next**: a real email provider instead of Mailpit (the dev inbox); a cap
on retries for digests that keep failing.

### Agent 5 — auth-service (~95%)

**Built**: JWT access + refresh tokens, 4 roles (requester, approver,
finance, admin), self-registration with a 12-character minimum and a
breached-password check, and the **business-rules engine**: 27 tunable
rules (spend tiers, SLA hours, confidence thresholds, anomaly thresholds,
renewal milestones...) editable on an admin page with full change history.
Services pick up changes through Kafka.

**Next**: password reset, account deactivation, HTTP-level auth tests.

### The platform glue (~100% for what the demo needs)

Kafka event bus (15 topics), a shared response format, idempotency keys,
one nginx gateway, Prometheus + Grafana dashboards (including Kafka lag),
structured JSON logs, retry-on-boot for every dependency, and a role-aware
React frontend, and ClamAV for upload scanning. **21 containers** come up
from one command.

### Overall

- **The demo flow works end to end, live**: one fresh invoice passes all
  56 checks of the lifecycle test through every agent, with a real 3-way
  match and no database shortcuts. `make e2e` passes 17/17 and 275 unit
  tests pass.
- **Against the full spec**: roughly **80–85%**. The gap is mostly
  external integrations (real e-sign sending, external risk data,
  sanctions) and a handful of hardening items, not the core flow.

---

## 2. What changed since the last review (Sep 5 → Sep 25)

- **License intelligence** (IsolationForest + SHAP, Licenses pages, reclaim
  and reinstate workflows): Niraj
- **GSTIN / IFSC vendor vetting, PaddleOCR, LayoutLMv3, doc-type-specific
  processing, 3-way invoice matching**: Niraj
- **Business rules engine + admin page**, System Health page, Kafka lag: Niraj
- **E-sign provider selection, simulated-sign guard, webhook tests**: Niraj
- **Self-registration + breached-password check, stricter token checks**: Anooj
- **ClamAV**: removed by Niraj (Sep 24) because startup took 2–3 min;
  **added back by Anjali (Sep 25)** on a native image that starts in ~5s
- **Audit + fixes during the merge** (Anjali): permission holes on new
  endpoints, identity spoofing on approvals, a leaked API key, document
  uploads failing, the anomaly model never running inside Docker, a race
  that could silently lose approvals, and the Apple Silicon build failure.
  Details: [AUDIT_CHANGES.md](AUDIT_CHANGES.md).

---

## 3. Demo script

### Before the demo (do this the evening before, and again 30 min before)

```bash
./run.sh                        # full stack; several minutes the first time
./scripts/seed-demo-data.sh     # vendor, approved request, 5 licenses, 4 hardware SKUs
./scripts/download-models.sh    # once per machine: LayoutLMv3 (~500 MB), else the cross-check is skipped
make e2e                        # should print "17 passed, 0 failed"
python tests/e2e/invoice_lifecycle.py   # should print "56 passed, 0 failed"
```

Checklist:
- [ ] `make e2e` and `invoice_lifecycle.py` green.
- [ ] `docker compose ps clamav` shows `(healthy)`.
- [ ] Open http://localhost:8080 and log in as each role once.
- [ ] Upload one sample document once, because the **first upload takes ~45s**
      while the models load. Later uploads take a few seconds.
- [ ] Licenses page shows scores (not "insufficient history").
- [ ] Port 3000 must be free for Grafana (stop any other dev server using it).
- [ ] Keep Mailpit (http://localhost:8025) open in a tab.

### Live walkthrough (~10 min)

Every login button is on the login page (one click per role; password for
all demo accounts is `DemoPass123!`).

1. **Requester → New Request.** Walk the 5-step wizard. Attach
   `data/synthetic-invoices/02_quote_delltechnologiesindi_QT-2026-00003.pdf`
   and point out the live pipeline status, detected type = *quote*, per-field
   confidence. Submit for about ₹2,500 (manager tier).
2. **Documents.** Open the upload: extracted fields, confidence per field,
   "needs review" when below 0.8. Upload the same invoice twice to show the
   **duplicate flag**.
   *Optional, malware scan:* in a terminal, create the EICAR test file and
   upload it. It's rejected with "malware detected (Eicar-Test-Signature)".
   ```bash
   printf '%s' 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' > /tmp/eicar.pdf
   ```
   Then upload `/tmp/eicar.pdf` from the Documents page.
3. **Approver → Approval Inbox.** Approve it. The status flips a moment later.
   Explain that this is a Temporal workflow, which is why it's asynchronous
   and survives restarts.
4. **Admin → Contracts.** Generate a contract from the approved request →
   send for signature (Documenso) → sign. Show extracted clauses.
5. **Risk.** Recompute the vendor's risk and show the band + top factors.
6. **Licenses** (admin or finance). The anomaly summary shows 2 anomalous,
   2 watch, 1 normal and **~₹3.4L potential annual savings**. Open JetBrains
   (120 seats, ~35 used): score, SHAP reasons, usage trend.
7. **Business Rules** (admin). Change the manager tier limit and show the
   history entry. This is how the business tunes the agents without a deploy.
8. **System Health** (admin). Live-verification toggle with API quota
   protection, model-routing log, Kafka lag.
9. **Mailpit.** Show the emails each step produced.
10. **Grafana** (http://localhost:3000). Request rate, latency, errors per
    service. **Temporal UI** (http://localhost:8088) shows the approval
    workflow history.

If something breaks live, `make e2e` in a terminal is the fallback. It
walks the whole chain in about 30 seconds with green ticks.

---

## 4. What's next (priority order)

1. **Real e-signature sending** (Documenso API), so the whole contract
   loop is real, not just the callback.
2. **External vendor-risk data + sanctions screening**, replacing the
   synthetic risk features with OpenCorporates / SEC EDGAR / SSL Labs /
   OpenSanctions.
3. **Hardening found in audit**: inventory-lock release, per-level
   approver check, uploader identity from the token, finance UI for
   bank-detail approvals.
4. **Run the tests in CI.** Today CI only builds images; two stale tests
   this week would have been caught.
5. **Tune the license-anomaly model** and validate clause extraction on
   CUAD, so both come with measured accuracy.
6. **Production basics**: resource limits, pinned image versions, a real
   email provider, password reset.

---

## 5. Likely questions — and short answers

### About the idea

**What makes this "agentic" rather than just microservices?**
Each agent owns a goal and makes decisions on its own: classify this
document, decide whether it needs a human, route this request to the right
approvers, decide a license is being wasted and start a reclaim, decide a
vendor is high risk and alert someone. They coordinate by reacting to each
other's events, not through a central script, and they hand off to a human
when their confidence is low.

**Where is AI/ML actually used?**
1. Document understanding: Docling layout parsing, PaddleOCR, LayoutLMv3
   field cross-check, classification.
2. License-usage anomaly detection (IsolationForest + SHAP explanations).
3. Vendor risk scoring (RandomForest), with drift monitoring (PSI).
4. Fuzzy vendor matching (rapidfuzz) and duplicate detection.
Rules still do the things that must be predictable, such as approval tiers
and dual control.

**Why not just use an LLM for everything?**
Cost, speed, determinism and auditability. Procurement decisions need to
be explainable and repeatable; a small model with SHAP reasons or a rule
with a change history is easier to defend to an auditor than a prompt.
LLM-based extraction is a sensible future addition for messy documents.

### About the architecture

**Why Kafka?** Agents shouldn't call each other directly. With events, any
agent can be down or slow without breaking the others, new consumers can
be added without changing producers, and every event is a record of what
happened.

**Why Temporal?** Approvals and renewal reminders run for days or months.
Temporal keeps that state durable across restarts and handles timers, SLA
escalations and retries for us. Without it we'd be writing our own cron
jobs and state machines.

**Why one shared Postgres?** It keeps the project simple for a 4-person
team, and each service still owns its own tables and migrations. The
trade-off is tighter coupling. In production we'd split databases per service.

**What happens if a service goes down?** The others keep running. Events
wait in Kafka until it comes back, Temporal resumes workflows where they
stopped, and every service retries its dependencies on boot.

**How does it scale?** Services are stateless behind the gateway, workers
can be replicated (Kafka consumer groups split the load), and heavy ML runs
in separate worker containers.

### About security

**How does auth work?** Log in → short-lived JWT (60 min) + refresh token.
Every service checks the token and role on every request; the frontend's
role checks are only for convenience. Identity for audit fields (who
requested, who approved) is taken from the token, never from the request
body.

**What stops fraud?** Dual control on bank-detail changes, duplicate-invoice
detection, spend-tier approvals, structuring detection (splitting
purchases to stay under limits, via 90-day spend), an HMAC-signed and
replay-protected e-sign webhook, and a full audit log.

**Is there malware scanning?** Yes. ClamAV scans every upload before it's
stored, in about 7 ms per file. Infected files are rejected (we demo this
with EICAR, the standard harmless test virus). If the scanner is down,
uploads are refused rather than let through unscanned ("fail closed").

**Didn't you remove ClamAV?** Briefly. It took 2–3 minutes to start on our
Macs because the old image only existed for Intel and ran under
emulation. We switched to the official multi-arch image, which runs
natively and is ready in about 5 seconds, so we put it back.

### About the ML

**Why IsolationForest for license usage?** We don't have labelled
"wasted license" data. IsolationForest is unsupervised: it learns what
normal usage looks like and flags outliers. SHAP tells the admin *why*
each license was flagged.

**Is the ML any good?** Honest answer: it's trained on synthetic data, so
we can show it works mechanically and explains itself, but we haven't
measured accuracy on real data. For example, one license at 76%
utilisation currently scores as anomalous because of its day-to-day login
pattern. Tuning is on the next-steps list.

**Why synthetic data?** Real procurement, SSO and vendor-risk data is
confidential. Every dataset's provenance is documented in `data/`, and the
pipelines are built so real data can be plugged in without code changes.

**What's drift monitoring?** Every week we compare this week's risk-score
distribution to the training distribution (Population Stability Index).
A large shift means the model may be out of date. It raises a flag but
never retrains on its own.

### About India-specific checks

**What's GSTIN / IFSC?** GSTIN is the 15-character GST tax registration
number; we check its format and checksum, and optionally look it up in the
live registry. IFSC identifies a bank branch; we validate it against
Razorpay's free API. Both are stronger vendor identifiers than a fuzzy name match.

**Why is live GSTIN lookup off by default?** The free API allows about 20
lookups in total. An admin enables "Live Verification Mode", and it switches
itself off before the quota runs out.

### About testing

**How do you know it works?** 275 unit tests, plus a lifecycle test that
takes one freshly generated invoice through all five agents on the real
running system, with 56 checks and no database shortcuts: login → malware
upload rejected → quote → vendor created → request → approval → invoice →
matched to the request → contract → e-signature → fulfilled → risk →
emails → audit trail. We run it live rather than showing screenshots.
Writing it turned up four bugs that unit tests had missed, including
invoice matching never working at all.

**What was the hardest bug?** A good one to tell: approvals sent right
after a request was created were being silently lost. The workflow cleared
its "decision received" flag *after* the decision had already arrived.
It only showed up once a new business-rules lookup made the workflow
slightly slower to start, which is typical of timing bugs in distributed systems.

### Questions to be careful with

- **"Does it send real e-signatures?"** Not yet. The signing callback is
  real and secured; the outgoing request is simulated.
- **"Is the risk score based on real data?"** No, it uses synthetic
  features today. Real sources are next on the list.
- **"Is it production-ready?"** It's a working, tested prototype with
  production patterns (auth, observability, durable workflows, audit logs).
  Before production it still needs CI test gates, resource limits, a real
  email provider and the hardening items in section 4.

---

## 6. Useful URLs and logins

| What | URL |
|---|---|
| App | http://localhost:8080 |
| Mailpit (emails) | http://localhost:8025 |
| Grafana | http://localhost:3000 (admin / admin) |
| Temporal UI | http://localhost:8088 |
| MLflow | http://localhost:5050 |
| MinIO console | http://localhost:9001 (minioadmin / minioadmin) |
| Prometheus | http://localhost:9090 |

Demo accounts (password `DemoPass123!`): `requester@`, `approver@`,
`finance@`, `admin@demo.example.com`.
