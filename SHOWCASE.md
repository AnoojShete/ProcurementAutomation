# IT Procurement Intelligence Platform — Showcase Guide

A one-stop doc for presenting this project: what each agent does and how
finished it is, an overall completion estimate, a step-by-step demo
script (UI and API), and an honest list of what's still missing. For the
full technical reference (architecture, shared contracts, per-service
internals, every bug found and fixed along the way), see
[README.md](README.md) — this doc is the presentation-facing summary of
that.

## What this is

An agentic AI platform that automates the IT procurement lifecycle —
five independent backend services ("agents"), each owned by a different
team member, talking to each other over a shared Kafka event bus and a
shared Postgres database, fronted by one gateway and one frontend:

1. A requester uploads an invoice/PO/quote → **document-vendor-agent**
   extracts and classifies it, matches or creates a vendor record.
2. A purchase request routes through **approval-inventory-agent** for
   spend-tier-appropriate approval, with SLA escalation and inventory
   reservation.
3. Once approved, **contract-risk-agent** generates the contract, routes
   it for e-signature, and scores the vendor's risk.
4. **notification-agent** emails every stakeholder at each step.
5. **auth-service** issues the JWTs that gate all of the above by role.

## 1. Agents — what's built and how complete

| # | Agent | Owner | Core job | Completion |
|---|---|---|---|---|
| 1 | document-vendor-agent | Vaidehi | Document intake, extraction, vendor matching | **~75%** |
| 2 | approval-inventory-agent | Niraj | Spend-tier approvals, inventory, license reclaim | **~90%** |
| 3 | contract-risk-agent | Anjali | Contract generation, e-signature, vendor risk scoring | **~55%** |
| 4 | notification-agent | Anooj | Event-driven email notifications | **~90%** |
| 5 | auth-service | Anooj | JWT auth, roles, demo users | **~95%** |

*(Percentages are against the full spec each agent was assigned,*
*including the "stretch" external-integration requirements added in a*
*later revision — not against a minimal MVP. See the per-agent notes*
*below for exactly what that last 10–45% is.)*

### Agent 1 — document-vendor-agent (~75%)

**Built:** malware-scanned upload → MinIO, an explicit six-stage agent
pipeline (parsing → classification → field extraction → vendor matching →
duplicate detection → confidence scoring) that passes a JSON envelope
between each stage, Docling for layout-aware PDF parsing (table structure
recovery, not just a flat text dump) with a pdfplumber fallback,
pytesseract OCR for scanned images, rapidfuzz vendor deduplication,
duplicate-invoice detection, a confidence-gated human review queue, and a
dual-control workflow for vendor bank/payment-detail changes (the
submitter can never also verify their own change — a BEC-fraud control).

**Missing:** PaddleOCR (the spec's requested OCR engine) was evaluated
and rejected — its native inference engine crashes the host process
(SIGABRT/SIGSEGV, not a catchable exception) on every version tried, on
both native ARM and emulated x86_64; pytesseract covers the same need
today. GSTIN format+checksum validation and IFSC bank-code validation
(both named in the spec as vendor-identity checks) aren't built yet.

### Agent 2 — approval-inventory-agent (~90%)

**Built:** config-driven spend-tier routing (auto / manager /
manager+finance), a Temporal workflow per request with SLA-timeout
auto-escalation, Redis-backed reservation locks preventing hardware
double-booking, automatic split into immediate + backordered portions
when stock is short, synthetic SSO-login-based license utilization
scoring with automatic reclaim requests below a threshold, and consuming
`contract.signed` to close the loop back to `fulfilled`.

**Missing:** nothing named in the original spec is outstanding; the
remaining gap is polish (e.g., more configurable escalation policies)
rather than an unbuilt requirement.

### Agent 3 — contract-risk-agent (~55%)

**Built:** Jinja2 contract generation across three contract types,
clause extraction (renewal type, notice period, end date) that runs on
the actually-generated text, a per-contract Temporal workflow firing
renewal reminders at 60/30/15 days out, an HMAC-verified and
replay-protected e-signature webhook, a real scikit-learn
`RandomForestClassifier` vendor risk model (trained on a documented
synthetic dataset, tracked in MLflow) with per-vendor explainability, a
weekly population-stability-index drift monitor, and a vendor
offboarding flow that revokes access and flags contracts for human
reconciliation rather than auto-closing them.

**Missing:** this is the agent with the largest gap against its expanded
spec. Not yet built: validating clause extraction against CUAD (the
real, citable Contract Understanding Atticus Dataset) instead of just
hand-written test contracts; the four real external risk-data sources
named in the spec (OpenCorporates for company legitimacy, SEC EDGAR for
financial stability, IAF CertSearch for ISO certification, Qualys SSL
Labs for live TLS grade) — risk scoring today runs entirely on the
synthetic feature set; OFAC/OpenSanctions sanctions screening; and a real
e-signature provider (OpenSign/Documenso) — the webhook path is real and
tested, but nothing live is wired in front of it yet, so "send for
signature" returns a simulated reference.

### Agent 4 — notification-agent (~90%)

**Built:** consumes every event topic that names it as a subscriber,
renders the matching Jinja2 email template (with strict-undefined
checking, so a template referencing an undocumented field fails loudly
instead of silently rendering blank), routes by priority (immediate for
urgent, batched digest otherwise), sends via SMTP, and keeps a searchable
send/queue/fail audit log.

**Missing:** nothing named in the spec is outstanding; would benefit from
a real transactional-email provider in place of Mailpit for anything
beyond a demo.

### Agent 5 — auth-service (~95%)

**Built:** JWT access + refresh tokens, role-based demo users, its own
migration-managed table.

**Missing:** production-grade concerns only (password reset flow, token
revocation list, real user self-registration) — everything the platform
itself needs from auth is done.

### The wiring between agents (~100%)

Not one of the five "prompt" agents, but arguably the hardest part to get
right: the shared Kafka event envelope, the shared REST response
envelope, idempotency keys, the nginx gateway's path-stripping routing,
Prometheus/Grafana observability, and — from this pass — a cross-service
**tracking dashboard** (the frontend's Records tab: every purchase
request, document, contract, and vendor in one filterable, sortable
view, so nothing is a black box). This layer is what makes five
separately-built services behave like one product, and it's fully
working end-to-end, verified by a 12-step automated test that walks the
entire request → approval → contract → signature → risk-score →
notification chain and by 119 unit tests across the five services.

## 2. Overall completion

**The demoable product is 100% functional end-to-end** — every step
below actually runs, live, against the real running stack, no mocked
steps. Against the **full ambitious spec** (including every
external-integration stretch goal — GSTIN/IFSC checks, CUAD-validated
clauses, four live risk-data APIs, sanctions screening, a real
e-signature provider, PaddleOCR), the platform is roughly **80%
complete** — a weighted average of the five agents above, where the gap
is concentrated almost entirely in contract-risk-agent's external-data
integrations and document-vendor-agent's identity-verification checks,
not in anything the core flow depends on.

## 3. How to show it

### Prerequisites

Docker Desktop running, nothing else — the whole stack (5 services, each
with its own worker, plus Postgres/Kafka/Redis/MinIO/Temporal/MLflow/
Prometheus/Grafana/Mailpit/nginx) comes up from one command.

### Bring it up

```bash
git clone <repo-url>
cd ProcurementAutomation
./run.sh                        # full stack — a few minutes on a clean clone
./scripts/seed-demo-data.sh     # one vendor + one already-approved request, for instant clicking
```

Open **http://localhost:8080/**.

### Live walkthrough (UI)

1. **How It Works tab** — open this first if presenting to people new to
   the project: the why, an architecture diagram, and a role matrix.
2. **Log in** — the login screen has one-click buttons for each demo
   role (requester / approver / finance / admin), no retyping
   credentials to switch hats.
3. **Document Review** (as requester) — upload a sample invoice or PO
   from `data/synthetic-invoices/`. Watch it come back classified, with
   vendor auto-matched and a confidence score; low-confidence fields are
   editable right there.
4. **Approver Inbox** — create a purchase request as requester, then
   switch to the approver role and approve it. The status flip is
   asynchronous (a Temporal workflow signal, not a synchronous HTTP
   response) — the UI polls briefly and updates live.
5. **Contracts & Vendor Risk** (as admin) — generate a contract from the
   approved request, send it for signature, and recompute the vendor's
   risk score to see the band (Low/Medium/High) and its top contributing
   factors.
6. **Records tab** — the tracking dashboard: every request, document,
   contract, and vendor in one place, filterable, with copyable IDs —
   this is the "nothing is a black box" view.
7. **Mailpit** (http://localhost:8025) — show the actual notification
   emails that fired at each step.
8. **Grafana** (http://localhost:3000) — live request rate / latency /
   error rate per service, for the "this is production-observable, not
   just a demo" point.

### API-level walkthrough (for a more technical audience)

The same flow, scripted end to end — good for showing the platform is
real infrastructure, not just a UI:

```bash
# Log in
TOKEN=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"requester@demo.example.com","password":"DemoPass123!"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")

# Upload a document — triggers the document-vendor-agent pipeline
curl -X POST http://localhost:8080/api/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@data/synthetic-invoices/00_invoice_hpindiasalespvtltd_INV-2026-00001.pdf"

# Create a purchase request
curl -X POST http://localhost:8080/api/requests/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"request_type":"saas","requested_by":"demo@company.com","department":"Engineering","amount":2500,"currency":"INR"}'
```

Or just run the whole thing as one automated script:

```bash
make e2e                              # 12/12 steps, the exact flow above plus contract + signature + risk + notification
./scripts/test-service.sh all         # 119 unit tests across all five services
```

Both are real proof, not narration — worth running live so the audience
sees green output rather than taking a slide's word for it.

## 4. Future scope — what's still missing

Ranked by how much it would change the story, not alphabetically:

1. **Real external vendor-risk data** (contract-risk-agent) — wiring in
   OpenCorporates, SEC EDGAR, IAF CertSearch, and Qualys SSL Labs so risk
   scores reflect real-world signal instead of a synthetic training set.
   This is the single biggest gap against the original spec.
2. **CUAD-validated clause extraction** (contract-risk-agent) — swapping
   hand-written test contracts for the real, published CUAD benchmark
   (510 contracts, 13k+ expert-labeled clauses) so extraction accuracy is
   a citable number.
3. **Sanctions screening** (contract-risk-agent) — an OFAC/OpenSanctions
   check as a real KYC/AML control, refreshed on a schedule rather than
   baked into the image once.
4. **GSTIN + IFSC vendor-identity verification** (document-vendor-agent)
   — a stronger vendor-dedup key than name-fuzzy-matching, with a live
   registry check rather than just a format check.
5. **A real e-signature provider** (contract-risk-agent) — the webhook
   receiver side is real and tested; nothing live (OpenSign/Documenso)
   sends the signature request yet.
6. **PaddleOCR** (document-vendor-agent) — evaluated and shelved after
   reproducible native crashes across two version pairs and two CPU
   architectures; pytesseract fills the same role today. Worth
   revisiting on a different deployment target.
7. **CI running the test suites** — `scripts/ci-build.sh` builds every
   image on push but doesn't yet run the 119 unit tests or the e2e suite
   as a gate.
8. **Deeper Grafana panels** — Kafka consumer lag and an approval
   SLA-breach panel, which need a bit more instrumentation to be real
   rather than decorative.

None of the above blocks the current demo — every one of the 12 e2e
steps and all 119 unit tests pass today, live, against the real running
stack. This is the honest list of what a longer engagement adds next,
not what today's demo is quietly missing.
