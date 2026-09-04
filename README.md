# IT Procurement Intelligence Platform

Agentic AI-based IT procurement platform: document/vendor intake, approvals
and inventory, contracts and vendor risk, and notifications — four
services, one Postgres schema, one Kafka bus, wired together behind a
single gateway, plus a lightweight frontend.

## Quickstart

```
git clone <repo-url>
cd ProcurementAutomation
./run.sh
```

That's the one script that brings up the **entire** stack from a clean
clone: core infra → builds every service image → ClamAV (first boot pulls
virus definitions, ~1–2 min) → every app service + its worker → the
gateway/frontend → a health-check pass over everything. It takes several
minutes on a clean clone (mostly image builds + ClamAV); subsequent runs
are much faster since Docker caches layers. If Docker Desktop (macOS/
Windows) or the Docker daemon (Linux) isn't already running,
`scripts/ensure-docker.sh` starts it automatically and waits for it to
become ready before continuing.

**Platform support**: macOS and Ubuntu/Linux run `./run.sh` directly.
**Windows** needs WSL2 (Docker Desktop's own requirement for Linux
containers) — either run `./run.sh` from inside a WSL2 terminal, or run
`run.ps1` / double-click `run.bat` from PowerShell/Explorer, which
re-exec it into WSL for you. Either way, enable Docker Desktop's WSL
integration for your distro first: Settings → Resources → WSL
Integration.

Then, optionally, seed one demo vendor + an already-approved purchase
request so there's something to click through immediately:

```
./scripts/seed-demo-data.sh
```

Open **http://localhost:8080/** and sign in with one of the [demo
accounts](#security--auth).

### Running things individually

`run.sh` is the one-shot path. For working on a single service:

```
docker compose up -d postgres redis redpanda minio temporal mailpit   # infra only
docker compose up -d contract-risk-agent contract-risk-agent-worker   # one service + its worker
./scripts/test-service.sh contract-risk-agent                         # that service's pytest suite
./scripts/test-service.sh all                                         # every service's pytest suite
make e2e                                                               # the full end-to-end flow (needs run.sh first)
```

`make run`, `make up`, `make down`, `make logs`, `make reset`, `make test`,
and `make e2e` are shortcuts for the equivalents above.

## Architecture

| Service | Owner | Folder | Port | Depends on |
|---|---|---|---|---|
| document-vendor-agent | Vaidehi | `services/document-vendor-agent/` | 8001 | Postgres, Kafka, MinIO, ClamAV |
| approval-inventory-agent | Niraj | `services/approval-inventory-agent/` | 8002 | Postgres, Kafka, Redis, Temporal |
| contract-risk-agent | Anjali | `services/contract-risk-agent/` | 8003 | Postgres, Kafka, Redis, Temporal, MLflow |
| notification-agent | Anooj | `services/notification-agent/` | 8004 | Postgres, Kafka, Mailpit |
| auth-service | Anooj | `services/auth-service/` | 8005 | Postgres |

Each of the four domain services also has a **worker** container (except
notification-agent and auth-service, which don't need one) running the
same image with `command: ["python", "-m", "app.worker"]`, consuming
Kafka and/or running Temporal workflows.

Shared infrastructure (`docker-compose.yml`): Postgres, Redis, Redpanda
(Kafka API), MinIO, Temporal + Temporal UI, MLflow, Prometheus, Grafana,
Mailpit, and the Nginx gateway. ClamAV and each app service live in
`docker-compose.override.yml`.

Local UIs once the stack is up:

| What | URL |
|---|---|
| Frontend | http://localhost:8080/ |
| API gateway | http://localhost:8080/api/... |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Temporal UI | http://localhost:8088 |
| MLflow | http://localhost:5050 |
| MinIO console | http://localhost:9001 |
| Mailpit | http://localhost:8025 |

## Shared contracts

Everything below is frozen once agreed — don't silently change a shape a
teammate is already coding against.

- **Event schema**: [`shared/schemas/events.md`](shared/schemas/events.md) —
  the Kafka envelope and, per-topic, the exact payload fields. Read this
  before writing any producer or consumer.
- **Kafka topics**: [`shared/kafka-topics.yaml`](shared/kafka-topics.yaml).
- **DB schema**: [`shared/db/init.sql`](shared/db/init.sql) — the shared
  base tables. Never edit this file directly; if your service needs new
  columns or tables, add your own migration inside your service folder.
  Two patterns are in use, both idempotent (`IF NOT EXISTS` everywhere, so
  it's safe to layer one service's migration on top of another's on the
  same shared tables): full Alembic (`services/contract-risk-agent/migrations/`,
  `services/auth-service/migrations/`) or a simpler raw-SQL-file-applied-
  at-startup approach (`services/approval-inventory-agent/app/database.py`'s
  `init_db()` + its `migrations/0001_schema_extensions.sql`). **If you add
  an Alembic-based migration, give it its own `version_table` name** (see
  contract-risk-agent's `migrations/env.py`) — every service shares one
  physical Postgres database, so Alembic's default `alembic_version` table
  name collides across services otherwise.
- **REST response envelope**: every endpoint returns
  `{"data": {...}, "meta": {}}` on success or
  `{"error": {"code": "string", "message": "string"}}` on failure, with an
  appropriate HTTP status. `shared/http/error_handlers.py` is a drop-in
  FastAPI exception handler that enforces this — import
  `register_error_handlers` and call it on your `app` instead of letting
  `HTTPException` fall through to FastAPI's default `{"detail": ...}` shape.
- **Auth**: `shared/auth/` — see [Security & Auth](#security--auth) below.
- **Idempotency**: `shared/idempotency.py` — `Idempotency-Key` header
  support backed by Redis for POST endpoints that create a resource. See
  `services/contract-risk-agent/app/api/contracts.py`'s `/generate`
  endpoint for the usage pattern.
- **Gateway routing**: `infra/nginx/nginx.conf` routes `/api/<prefix>/*` to
  each service by container name, stripping the `/api/<prefix>/` segment
  before forwarding (every `proxy_pass` has a trailing path for exactly
  this reason — without it the backend receives `/api/...` URIs its own
  router was never mounted at, and everything 404s). It also serves the
  static frontend from `/`.

## Security & Auth

`services/auth-service/` issues short-lived JWT access tokens (default 60
min) and longer-lived refresh tokens. `shared/auth/middleware.py`
(`get_current_user`, `require_role(...)`) is imported by every other
service to verify them — applied at the router-include level in each
service's `main.py`, so it's structurally impossible to forget on an
individual endpoint. Only `GET /health` and `GET /metrics` are exempt
everywhere; the e-sign webhook (`POST /webhooks/esign` on
contract-risk-agent) is also exempt since the provider has no platform
login — it authenticates via an HMAC signature instead
(`ESIGN_WEBHOOK_SECRET`).

**Getting a token:**

```
curl -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"approver@demo.example.com","password":"DemoPass123!"}'
# -> {"data": {"access_token": "...", "refresh_token": "...", ...}}

curl http://localhost:8080/api/requests/ -H "Authorization: Bearer <access_token>"
```

**Demo accounts** (seeded on `auth-service` boot — **DEMO ONLY, not for
production use**, all share one password):

| Email | Role | Password |
|---|---|---|
| requester@demo.example.com | requester | DemoPass123! |
| approver@demo.example.com | approver | DemoPass123! |
| approver2@demo.example.com | approver | DemoPass123! |
| finance@demo.example.com | finance | DemoPass123! |
| admin@demo.example.com | admin | DemoPass123! |

Roughly: `requester` creates purchase requests and uploads documents;
`approver`/`finance` approve/reject requests and recompute vendor risk;
`admin` generates/signs contracts and offboards vendors. Exact
per-endpoint restrictions are in each service's `app/api/*.py`
(`dependencies=[Depends(require_role(...))]`).

## Frontend

`frontend/` is a React + TypeScript + Vite + Tailwind app (source in
`frontend/src/`), built to `frontend/dist/` and served by the **same nginx
container** as the API gateway (volume-mounted at
`/usr/share/nginx/frontend` — see `docker-compose.override.yml`), so the
page and its `/api/*` calls still share one origin with no CORS to
configure. `run.sh` builds it in a throwaway `node:20-alpine` container
before (re)starting nginx, so the host doesn't need Node installed. For
local iteration: `cd frontend && npm install && npm run dev` runs Vite's
dev server on :5173 with `/api` proxied to the running gateway at :8080
(see `vite.config.ts`) — no rebuild needed between edits. The previous
no-build-step vanilla JS version is kept at `frontend/legacy-static/` for
reference.

The app is **role-aware end to end**: login routes each of the four demo
roles (`requester`/`approver`/`finance`/`admin`) to its own navigation and
dashboard rather than one shared view. Login has one-click demo-role
switching (fills in one of the seeded demo accounts below) so trying
different permissions doesn't mean retyping credentials. Route-level role
checks in the frontend are a UX convenience only — every backend endpoint
still enforces its own `require_role` check regardless of what the UI
shows.

Covers, per role: purchase-request creation (a 5-step wizard: details,
vendor, optional supporting-document upload with live pipeline status,
review with per-field confidence, submit), an approval inbox with
async-settling approve/reject, document review (extracted fields, per-field
confidence, correct-and-save), vendor profiles (risk score, contributing
factors, payment-change dual-control queue), contract generation/
send-for-signature/renewal timeline, vendor risk scoring/recompute/drift
check/offboarding, inventory (hardware + license utilisation), a
notification log, and a global `Cmd/Ctrl+K` search across already-loaded
requests/vendors/contracts/documents. Anywhere the backend doesn't expose
an API for something the UI conceptually wants (vendor creation, full-text
search, editable business rules, an aggregated health endpoint), the
frontend says so explicitly (disabled controls with a tooltip, an
"unavailable" state) rather than faking it.

The approve/reject buttons poll briefly after submitting rather than
trusting the immediate response — the decision is applied by signalling a
Temporal workflow running in a separate worker process, so the status
flip isn't synchronous with the HTTP call that triggers it. Same pattern
for document upload → classification status in the request wizard.

## Testing

- **Per-service unit tests**: `./scripts/test-service.sh <name>` (or `all`)
  runs that service's `pytest` suite inside its own built Docker image,
  with the service folder volume-mounted so it runs against current
  source. 117 tests across the five services as of this writing — all
  pure-logic/schema tests, no live infra required.
- **End-to-end test**: `make e2e` (or `./tests/e2e/run.sh`) scripts the
  real flow through the *running* gateway: log in as requester → create a
  purchase request → log in as approver → approve it (polls, since the
  decision is applied asynchronously by a signalled Temporal workflow) →
  admin generates a contract → sends it for signature → simulates the
  e-sign provider's webhook (real HMAC signature) → confirms the contract
  shows signed → recomputes vendor risk → confirms a notification landed
  in Mailpit. Needs `./run.sh` to have been run first.

## Per-service notes

### document-vendor-agent (Vaidehi) — port 8001

Upload endpoint streams the file through ClamAV (fails closed — a 503 if
ClamAV is unreachable, never a silent skip) before writing to MinIO and
publishing `document.ingested`. A separate worker consumes that event and
runs the extraction pipeline as an explicit chain of agents passing a
JSON envelope from one to the next (`app/services/pipeline.py`):
parsing (Docling for every PDF — layout-aware, recovers table structure,
falls back to plain pdfplumber if it errors; pytesseract OCR for
standalone scanned images) → classification (keyword-weighted PO/invoice/
quote classifier) → field extraction (regex-based: vendor, line items,
totals, dates, document numbers) → vendor matching (rapidfuzz name
normalization + dedup against the shared `vendors` table) → duplicate
detection (vendor + amount tolerance + date window) → confidence scoring.
Confidence below threshold (default 0.8) routes to the review queue
instead of auto-completing. Publishes `document.classified` and
`vendor.matched`. See the README's Future scope note on why PaddleOCR
isn't the image-OCR engine.

Two governance controls: vendor bank/payment-detail changes go into a
`payment_details_pending_verification` state instead of updating live
(dual control — the submitter can't also verify, via
`POST /vendors/{id}/verify-payment-change`), and every upload is
malware-scanned before storage.

### approval-inventory-agent (Niraj) — port 8002

Spend-tier routing (auto / manager / manager+finance, thresholds in
`config.yaml`) drives a Temporal `ApprovalWorkflow` per request: waits for
an `approval_signal` from `POST /requests/{id}/approve|reject` up to an
SLA timeout, auto-escalating on timeout. Redis-backed reservation locks
prevent double-booking hardware stock; oversubscribed hardware requests
split into an immediate + backordered portion. A synthetic SSO-login
generator feeds per-license utilisation scoring, auto-creating a reclaim
request when utilisation drops below threshold. Consumes `contract.signed`
to mark the originating request `fulfilled`.

Note the approval decision is **asynchronous**: `POST /.../approve`
signals the workflow and returns immediately — the actual status flip
happens in the separate worker process a moment later (see the e2e test's
polling loop). `GET /inbox/{approver_id}` takes an approver *role* (e.g.
`dept_manager`, matching `config.yaml`'s spend-tier chains), not an
individual user id.

### contract-risk-agent (Anjali) — port 8003

Jinja2 contract templates (hardware/SaaS/professional-services), with
clause extraction (renewal type, notice period, end date) run on the
*generated* text itself so the extraction logic is exercised on real
prose, not just trusted. A per-contract Temporal workflow fires
`contract.renewal.due` at 60/30/15 days before the notice deadline.
`POST /webhooks/esign` receives the signed-document callback (HMAC-verified,
replay-protected via a `processed_webhook_events` table), marks the
contract signed, and publishes `contract.signed`.

Vendor risk: a scikit-learn `RandomForestClassifier`
(`ml/train_risk_model.py`) trained on
`data/synthetic-vendors/vendor_risk_training_data.csv` (see that folder's
README for provenance), logged to MLflow. `POST /vendors/{id}/risk/recompute`
scores a vendor and publishes `risk.score.updated` (a `High` band also
fires an urgent notification); top contributing factors come from feature
importances scaled by how far the vendor's values sit from a neutral
midpoint, so they're vendor-specific, not a static ranking. A weekly
Temporal-scheduled job computes a Population Stability Index against the
training-time score distribution and logs a `model_drift_detected` flag to
MLflow — a monitoring signal only, it never retrains automatically; feed
it ground truth via `POST /vendors/{id}/log-outcome`.

Vendor offboarding revokes portal access, flags every active contract
`reconciliation_status: pending_review` (never auto-closes — a human
confirms final invoice/payment status), and sets a data-retention flag
rather than deleting records.

### notification-agent (Anooj) — port 8004

Consumes every event topic that names it as a consumer in
`shared/schemas/events.md`, renders the matching Jinja2 template
(`app/templates/*.j2`, `StrictUndefined` so a template referencing an
undocumented field fails loudly instead of rendering blank), and sends via
SMTP to Mailpit. `priority` (`urgent` vs `digest`) decides immediate send
vs a periodic batched digest email. `GET /notifications/log` is a
searchable audit trail of everything sent/queued/failed.

### auth-service (Anooj, Prompt 5) — port 8005

Own `auth_users` table (its own Alembic migration, not the shared
schema). `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`. Demo
users seeded on boot — see [Security & Auth](#security--auth).

## Known limitations / infra fixes made along the way

A number of gaps in the shared scaffold surfaced only once every service
existed and was wired together — fixed at the shared-infra level rather
than worked around per-service, since they'd have bitten whoever hit them
next:

- `.gitignore` excluded `docker-compose.override.yml` and `*.md` entirely
  — no service wiring or documentation could ever be committed.
- Redpanda had no `--advertise-kafka-addr`, so it advertised `localhost`
  in its metadata response — every producer/consumer connected for the
  initial bootstrap but failed on the first actual publish/consume.
- `temporal` had no DB environment variables, so `auto-setup` defaulted to
  Cassandra and refused to start. Now pointed at the shared Postgres.
- `mailpit` had no healthcheck, which any service trying
  `depends_on: mailpit: condition: service_healthy` needs.
- SQLAlchemy models across the codebase typed UUID primary/foreign keys as
  `String`; Postgres rejects `uuid = character varying` comparisons
  outright. All five services now use
  `sqlalchemy.dialects.postgresql.UUID(as_uuid=False)`.
- Alembic's default `alembic_version` table is shared across every
  service using the same physical Postgres database — a second
  Alembic-based service would see the first one's "0001" already recorded
  and silently skip its own migration. Each service now sets its own
  `version_table`.
- **The gateway didn't actually strip `/api/<prefix>/` before forwarding**
  — every route 404'd through nginx despite working fine hit directly on
  a service's own port, since no backend router is mounted at `/api/...`.
  Every `location` block's `proxy_pass` now has a trailing path so nginx
  performs the prefix substitution.
- nginx resolves every upstream hostname at container boot and refuses to
  start at all if one doesn't exist yet (`host not found in upstream`) —
  meaning it can't come up until every backend service is already defined
  and running. `run.sh` builds/starts everything else first, then
  (re)creates nginx last.
- `install.sh`'s `docker compose up -d` was unscoped, so once every app
  service existed in `docker-compose.override.yml` it started them all
  immediately — before `shared/db/init.sql` had even been applied. Scoped
  to core infra only; `run.sh` brings the app services up itself,
  afterward, in the right order.
- ClamAV's published image has no native `arm64` build; pinned to
  `platform: linux/amd64` (works via Rosetta/QEMU emulation on Apple
  Silicon, just slower to pull the first time).
- A Temporal signal dataclass field typed `comments: str = None` (should
  be `Optional[str]`) made the *entire* approval-decision path silently
  fail to decode — Temporal's payload converter checks annotations
  strictly. Two more instances of the same pattern in the same service's
  activities. Worth grepping for `: str = None` / `: int = None` /
  `: bool = None` if you add new Temporal signals/activities anywhere.
- Grafana had no datasource at all — `docker-compose.yml`'s `grafana`
  service never mounted `infra/grafana/provisioning/`, so the on-disk
  datasource/dashboard config did nothing. Wired in via
  `docker-compose.override.yml`, plus `infra/prometheus/prometheus.yml`
  had no scrape targets beyond itself. Both fixed; a starter dashboard
  (request rate / p95 latency / 5xx rate / service up-down, all per
  service) is provisioned automatically at http://localhost:3000.
- A malformed path parameter where a UUID was expected (e.g.
  `/vendors/2.1/risk`) reached the database driver as a bad bind value
  and surfaced as a raw 500 instead of a clean 4xx — `shared/http/error_handlers.py`
  now recognizes the database driver's own "bad input" errors and maps
  them to 400.
- **Operational gotcha, not a code bug**: because nginx resolves upstream
  hostnames to IPs once at its own boot and doesn't re-resolve
  automatically, if you `docker compose up -d --force-recreate` a backend
  service *without* also restarting nginx, the gateway will 502 for that
  service until nginx is restarted too (hitting the service's own port
  directly still works fine). `run.sh` always restarts nginx last for
  exactly this reason — do the same after manually recreating any
  service outside of `run.sh`.

## Future scope

Everything above is built and demoable end-to-end. A few things are
explicitly out of scope for this pass — either because they need paid/
rate-limited external accounts this environment doesn't have, or because
they're a genuinely separate, larger effort:

- **PaddleOCR for image OCR** (document-vendor-agent currently uses
  Docling for PDFs — layout-aware parsing with table-structure recovery,
  shipped — and pytesseract for standalone scanned images): PaddleOCR was
  evaluated as pytesseract's replacement for the image path and rejected
  for now. Its native inference engine segfaults/aborts the host process
  on every version pairing tried (current and an older 2.9.1/2.6.2 pair),
  on both native arm64 and emulated amd64 — three distinct crash
  signatures, none catchable from Python since they're C-level process
  aborts, not exceptions. Worth revisiting against a future PaddleOCR
  release or a different deployment target (bare-metal Linux rather than
  Docker Desktop's Apple Silicon virtualization) rather than this
  environment.
- **India-specific vendor identity checks**: GSTIN validation (format +
  real modulo-36 check-digit algorithm, then a live registry lookup —
  gstincheck.co.in's free tier is ~20 lookups total, not per day, so
  results need permanent caching) and IFSC bank-code validation (Razorpay's
  free, keyless API) as a stronger vendor-dedup key than name-fuzzy-
  matching, with a DB-level unique constraint on `gstin` to close the same
  race condition the Redis reservation lock addresses elsewhere. Needs a
  `GSTINCHECK_API_KEY` (free signup) — IFSC needs no key.
- **Clause extraction validated against CUAD** (the Contract Understanding
  Atticus Dataset — 510 real contracts, 13k+ expert-labeled clauses,
  CC BY 4.0, atticusprojectai.org/cuad): a real, citable benchmark instead
  of hand-written test contracts. Needs a real conversion step first — CUAD
  ships as SQuAD-style (context, question, answer-span) tuples per clause
  category, not as the (renewal_type, notice_period, end_date) records
  this service extracts, so there's no shortcut to pointing the pipeline
  at the raw download.
- **Real external data for vendor risk scoring**, replacing more of the
  synthetic feature set: OpenCorporates (company legitimacy — a name
  search returns multiple candidates, so this needs a
  `needs_manual_match` state, not blind `result[0]`), SEC EDGAR (financial
  stability for US public companies specifically — resolve to a CIK
  first, and "no CIK match" means *not applicable*, never "high risk"),
  IAF CertSearch (ISO certification status), and Qualys SSL Labs (live TLS
  grade — this one's fully real for any vendor with a website, no
  fallback needed). Every feature would need normalizing onto one 0–1
  scale before it enters the model, and an explicit `insufficient_data`
  state per feature when a rate-limited API has nothing cached — a
  silently-filled default reads as a real measurement when it isn't one.
  Needs an `OPENCORPORATES_API_TOKEN` (free signup); the rest are keyless.
- **Sanctions screening** (`POST /vendors/{id}/screen-sanctions` against
  OFAC's SDN + Consolidated lists or OpenSanctions.org, fuzzy-matched):
  a real KYC/AML control, not a synthetic one. The list needs to be
  fetched at startup and refreshed on a schedule (a daily Temporal
  workflow is enough), not baked into the image, or "screened against
  the sanctions list" stops meaning anything a week in.
- **A real e-signature provider**: the webhook path (signature
  verification, replay protection, `contract.signed` publish) is real and
  tested; there's no live OpenSign/Documenso instance actually wired in,
  so `POST /contracts/{id}/send-for-signature` returns a simulated
  provider reference rather than routing to a real signing flow. The e2e
  test simulates the provider's callback directly against the API to
  prove the rest of the chain.
- **Grafana dashboards**: the provisioned starter dashboard covers
  request rate/latency/errors; Kafka consumer lag and an approval SLA-
  breach panel would need a bit more instrumentation (a lag exporter for
  Redpanda, a counter in approval-inventory-agent) to be real rather than
  decorative.
- **CI**: `scripts/ci-build.sh` builds each service's Docker image on
  push; it doesn't yet run the pytest suites or `make e2e` in CI. Wiring
  `scripts/test-service.sh all` and `make e2e` in as pipeline steps (the
  e2e step needs the full stack up first) would close that gap.

None of the above blocks the current demo — they're the honest list of
"what a longer engagement would add next," not missing pieces the
platform depends on.

## Data provenance

- `data/synthetic-vendors/` — vendor risk model training data. See its
  own README for exact provenance (Kaggle-seeded when available,
  documented synthetic fallback otherwise).
- `data/synthetic-invoices/` — synthetic PO/invoice/quote PDFs for
  document-vendor-agent, generated from
  `services/document-vendor-agent/scripts/synthetic_invoice_lib.py`.
