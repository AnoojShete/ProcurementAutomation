# IT Procurement Intelligence Platform

Five cooperating services ("agents") that automate IT procurement:
reading invoices, POs and quotes; routing purchase requests for approval;
tracking inventory and SaaS license usage; generating contracts and
collecting e-signatures; scoring vendor risk; and emailing the people
involved. They share one Postgres database, talk over Kafka, and sit
behind one nginx gateway that also serves the React frontend.

A student team project (Anjali, Vaidehi, Niraj, Anooj). It's a working,
tested prototype, not a production deployment — see [TODO.md](TODO.md)
for what's open, [CHANGELOG.md](CHANGELOG.md) for what changed, and
[SHOWCASE.md](SHOWCASE.md) for a presentation-oriented overview.

- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Configuration](#configuration)
- [Using it](#using-it)
- [Testing](#testing)
- [Project structure](#project-structure)
- [How it works](#how-it-works)
- [Troubleshooting](#troubleshooting)

## Architecture

```
 browser ──► nginx :8080 ──┬─ /            React app (frontend/dist)
                           └─ /api/<svc>/  ─► FastAPI services
                                              │
      document-vendor-agent  approval-inventory-agent  contract-risk-agent
      notification-agent     auth-service
                                              │
   Postgres · Kafka (Redpanda) · Temporal · Redis · MinIO · ClamAV · Mailpit
```

| Service | Port | Owner | Does |
|---|---|---|---|
| document-vendor-agent (+ worker) | 8001 | Vaidehi | Upload (virus scan, type checks) → MinIO; worker extracts text, classifies, extracts fields, matches/vets vendors, books invoices against the ledger, flags duplicates |
| approval-inventory-agent (+ worker) | 8002 | Niraj | Purchase requests, Temporal approval workflows, approval authority, inventory, license usage anomaly model + reclaim, invoice ledger, order monitor |
| contract-risk-agent (+ worker) | 8003 | Anjali | Contract generation (text + PDF), e-sign webhook / Documenso client, renewal reminders, vendor risk model (RandomForest, MLflow) and drift check, offboarding |
| notification-agent | 8004 | Anooj | Consumes events, renders email templates, sends immediately or in digests (to Mailpit) |
| auth-service | 8005 | Anooj | Accounts, login/sessions, email verification and password reset, roles, business-rules engine |

Infrastructure (22 containers in total, `docker-compose.yml` +
`docker-compose.override.yml`): Postgres, Redis, Redpanda (Kafka API) and
its one-shot `redpanda-init`, Temporal + Temporal UI, MinIO, ClamAV,
Mailpit, MLflow, Prometheus, Grafana, kafka-exporter, nginx.

Shared contracts:
- Kafka events: [`shared/schemas/events.md`](shared/schemas/events.md)
  (envelope + payload per topic), topic list `shared/kafka-topics.yaml`,
  per-service permissions `infra/redpanda/acls.conf`.
- REST envelope: `{"data": …, "meta": …}` or
  `{"error": {"code", "message"}}`, enforced by
  `shared/http/error_handlers.py`.
- Auth: `shared/auth/` (JWT verification, `require_role`), used by every
  service at router level; only `/health`, `/metrics` and the signed
  e-sign webhooks are unauthenticated.

## Prerequisites

- **Docker** with Compose v2 (`docker compose`): Docker Desktop on macOS /
  Windows, Docker Engine + compose plugin on Linux. Give Docker about
  8 GB of memory (ClamAV alone holds ~1 GB; the document worker loads
  Docling and, if downloaded, LayoutLMv3).
- **Internet** for the first build, for the breached-password check at
  sign-up (HaveIBeenPwned; sign-up returns 503 without it), and for the
  optional LayoutLMv3 download (~500 MB).
- **Python 3 + pip** on the host only for the end-to-end test scripts.
- Node is **not** needed: `run.sh` builds the frontend in a container.
- **Windows**: WSL2 with Docker Desktop's WSL integration; run `./run.sh`
  inside WSL (`run.ps1` / `run.bat` re-launch it there — not re-verified
  in the Sep 27 audit).

## Setup

```bash
git clone <repo-url>
cd ProcurementAutomation
./run.sh                        # whole stack; ends with "All services healthy."
./scripts/seed-demo-data.sh     # demo vendor, approved request, 5 licenses, 4 hardware SKUs
./scripts/download-models.sh    # optional, once per machine: LayoutLMv3 (~500 MB)
```

Then open **http://localhost:8080** and sign in with a
[demo account](#demo-accounts), or create your own.

What `run.sh` does: `install.sh` (creates `.env` from `.env.example` if
missing, starts infrastructure, applies `shared/db/init.sql`, creates Kafka
users/topics/ACLs and the MinIO bucket) → builds every image → builds the
frontend in a `node:20-alpine` container → starts the services (each
applies its own migrations on start) → recreates nginx last → waits for
health checks. The first run takes several minutes (image builds);
later runs are much faster.

`scripts/ensure-docker.sh` starts Docker Desktop / the daemon if it isn't
running. `make run | up | down | logs | reset | test | e2e` are shortcuts
(`make reset` deletes all data: `docker compose down -v` + `install.sh`).

Teardown: `docker compose down` (keeps data) or `docker compose down -v`
(deletes all volumes).

## Configuration

Everything is read from `.env` (git-ignored; created from `.env.example`).
The demo compose defaults work without editing it.

| Setting | Default in the demo | Notes |
|---|---|---|
| `APP_ENV` | `development` (set by compose) | Unset means **production**: services refuse the published default secrets below, don't seed demo accounts, disable showcase endpoints and simulated signing, and refuse `EMAIL_MODE=dev`. |
| `JWT_SECRET`, `ESIGN_WEBHOOK_SECRET`, `RULES_ENGINE_INTERNAL_SECRET`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `KAFKA_PASSWORD_*` | published dev values | Must be real secrets outside development. |
| `JWT_EXPIRY_MINUTES` / `JWT_REFRESH_EXPIRY_DAYS` | 60 / 7 | Access token lifetime is also how long a disabled user's current token keeps working. |
| `EMAIL_MODE` | `dev` | `dev` = Mailpit (nothing leaves the machine, read mail at :8025); `smtp` = real delivery. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD` | blank | Leave blank for `dev`. For `smtp`: port defaults to 587, security to `starttls` (`ssl` for 465). |
| `EMAIL_FROM`, `EMAIL_REPLY_TO` | `Procurement Platform <noreply@procurement.local>`, blank | With Gmail, `EMAIL_FROM` must be your Gmail address. |
| `APP_BASE_URL` | `http://localhost:8080` | Used to build the links in emails. |
| `AUTH_LOCKOUT_THRESHOLD` / `_WINDOW_MINUTES` / `_MINUTES` | 5 / 15 / 15 | Wrong passwords per address before a temporary lock. |
| `AUTH_COOKIE_SECURE` | off in development | Turn on behind HTTPS. |
| `APP_SHOWCASE_MODE` | on in development only | Enables the Controls page scenario endpoints. |
| `GSTINCHECK_API_KEY` | placeholder | Only for live GSTIN lookups (off by default, admin toggle). |
| `APP_DOCUMENSO_API_URL` / `_API_TOKEN` / `_WEBHOOK_SECRET` | unset | With these, "Send for signature" uses Documenso; unset = simulated signing. |
| `VITE_SHOW_DEMO_ACCOUNTS` (frontend build) | shown | Set to `false` when building for real users to hide the demo-login buttons. |

Only **auth-service** uses the email settings. notification-agent still
sends every notification to Mailpit (its recipients are placeholder role
addresses; its email work belongs to Anooj).

### Real email with Gmail

1. Turn on 2-Step Verification on the Google account, then create an app
   password at https://myaccount.google.com/apppasswords.
2. In `.env`:
   ```
   EMAIL_MODE=smtp
   SMTP_HOST=smtp.gmail.com
   SMTP_USERNAME=you@gmail.com
   SMTP_PASSWORD=<16-character app password>
   EMAIL_FROM=Procurement Platform <you@gmail.com>
   ```
3. `docker compose up -d auth-service && docker compose restart nginx`.
   auth-service refuses to start if the SMTP settings are incomplete.
4. Sign up at http://localhost:8080/signup with a real address, click the
   link in the email, sign in, then use "Forgot password?" and reset it.
5. Check the stored password is a hash:
   ```bash
   docker compose exec postgres psql -U postgres -c \
     "SELECT email, left(hashed_password, 30) AS hash_prefix, email_verified_at
      FROM auth_users WHERE email = 'you@gmail.com';"
   ```
   `hash_prefix` shows `$argon2id$v=19$m=65536,t=3,p=4` (argon2id and its settings), never the password.

Other SMTP providers take the same settings (see `.env.example`). Steps
1–5 with a real Gmail account were not run in the audit; the same flow
runs automatically against Mailpit in `tests/e2e/auth_flows.py`.

## Using it

| What | URL |
|---|---|
| App | http://localhost:8080 |
| API (through the gateway) | http://localhost:8080/api/… |
| Mailpit (all dev email) | http://localhost:8025 |
| Grafana (admin / admin) | http://localhost:3000 |
| Temporal UI | http://localhost:8088 |
| MLflow | http://localhost:5050 |
| MinIO console (minioadmin / minioadmin) | http://localhost:9001 |
| Prometheus | http://localhost:9090 |

Only :8080 is reachable from other machines; every other port is bound to
127.0.0.1. Service ports 8001–8005 are for debugging only.

### Demo accounts

Seeded when `APP_ENV=development`, password `DemoPass123!` for all:
`requester@`, `approver@`, `approver2@`, `finance@`, `admin@demo.example.com`.
The login page has one-click buttons for them.

### Roles and accounts

- **requester**: create purchase requests, upload documents, see own items.
- **approver** / **finance**: approval inbox (only levels they're assigned
  to in the approval authority matrix), licenses, vendors, risk (finance).
- **admin**: everything, plus Users, Business Rules, System Health, Audit.

Sign-up creates a *requester* after the email is confirmed; an admin
changes roles on **Users** (`/app/users`). A new approver also needs an
assignment on the Controls → Approval authority tab before they can
approve. Everyone can change their password and sign out of all devices
on **Account** (`/app/account`, click your name in the sidebar).

API example:

```bash
curl -s -X POST http://localhost:8080/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"approver@demo.example.com","password":"DemoPass123!"}'
# {"data": {"access_token": "…", "token_type": "bearer", "expires_in_minutes": 60}}
# (the refresh token is set as an httpOnly cookie, not returned)
curl -s http://localhost:8080/api/requests/ -H "Authorization: Bearer <access_token>"
```

## Testing

Results from the Sep 27 audit, on a fresh clone set up with the steps
above (separate Docker project, empty volumes):

| Command | What | Result |
|---|---|---|
| `./scripts/test-service.sh all` (or `make test`) | Each service's pytest suite inside its image, source mounted | 409 passed, 2 skipped |
| root tests (command below) | `shared/` code and config checks (Kafka ACLs vs code, nginx rules, lifecycle, outbox, mailer) | 116 passed |
| `make e2e` | Bash flow through the gateway: login, ClamAV reject/accept, request → approve → contract → signed webhook → risk → email → business-rule change | 17/17 |
| `python tests/e2e/auth_flows.py` | Sign-up → email → confirm → login → change password → logout → forgot/reset, expired / reused links, lockout, enumeration, rate limit (reads Mailpit) | 42/42 |
| `python tests/e2e/invoice_lifecycle.py` | One fresh vendor's quote + invoice through all five agents, no DB shortcuts | 63/63 after `download-models.sh` (62/63 without it: the LayoutLMv3 check) |
| `python -m pytest tests/e2e/test_flow.py` | Core flow + webhook bad-signature / replay | passed |
| `python tests/e2e/document_pipeline.py [--quick]` | Normal / huge / corrupt / empty / wrong-type / pathological files, duplicates, outages | **failing** — see TODO.md P0 (invoices stuck on the invoice ledger) |
| `cd frontend && npm run typecheck` | TypeScript | clean |

```bash
# once, for the e2e scripts
pip install -r tests/e2e/requirements.txt
# root tests, in any built service image
docker run --rm -e APP_ENV=development -v "$PWD:/w" -w /w --entrypoint sh \
  procurementautomation-auth-service -c "pip -q install pyyaml; python -m pytest -q tests --ignore=tests/e2e"
```

Notes:
- auth-service's account-flow tests need Postgres: with the stack running,
  `test-service.sh` gives them a throwaway `auth_test` database; otherwise
  they're skipped.
- The gateway rate-limits auth endpoints per IP. Running several e2e
  scripts back to back can hit it — wait a minute between suites.
- The image name in the root-test command follows the folder name
  (`<folder>-auth-service`).
- There's no Python linter configured; CI (`.github/workflows/ci.yml`)
  only builds images.

## Project structure

```
services/
  document-vendor-agent/     app/ (api, services/pipeline.py, kafka, worker), migrations/*.sql, tests/
  approval-inventory-agent/  app/ (api, services, workflows, ml), migrations/0001_*.sql, ml/, tests/, README.md
  contract-risk-agent/       app/ (api, services, workflows), migrations/ (Alembic), ml/, templates, tests/
  notification-agent/        app/ (kafka, services, templates/*.j2), migrations/*.sql, tests/
  auth-service/              app/ (api/auth.py, api/users.py, account_tokens, lockout, emails), migrations/ (Alembic), tests/
shared/
  auth/          JWT create/verify, require_role
  eventing/      transactional outbox, consumer inbox / retry / dead-letter
  db/            init.sql (base schema), sql_runner.py
  http/          error envelope handlers
  mailer.py      SMTP / Mailpit sender
  lifecycle.py   purchase-request state machine
  rules_engine/  business-rules client
  runtime_env.py APP_ENV rules
  kafka_security.py, idempotency.py, logging/, infra/, taxonomy/, live_mode/, audit/, schemas/events.md
frontend/        React + TypeScript + Vite + Tailwind (src/pages, src/api, src/components); legacy-static/ = old version, unused
infra/           nginx/nginx.conf, redpanda/ (acls.conf, bootstrap.sh), prometheus/, grafana/ (k8s/ is empty)
tests/           root tests; e2e/ (run.sh, auth_flows.py, invoice_lifecycle.py, document_pipeline.py, test_flow.py)
data/            synthetic datasets + provenance READMEs
scripts/         test-service.sh, seed-demo-data.sh, download-models.sh, ensure-docker.sh, ci-build.sh, generate_sso_logs.py
run.sh, install.sh, Makefile, docker-compose.yml, docker-compose.override.yml, .env.example, simulate_esign.py
```

## How it works

### Security and accounts

- **Passwords**: argon2id (64 MiB, t=3, p=4); legacy bcrypt hashes still
  verify and are re-hashed at login. 12–128 characters, must not contain
  the email, checked against HaveIBeenPwned (k-anonymity; fails closed).
- **Sign-up** → confirmation email (link valid 24 h) → login. Links are
  single-use, only their SHA-256 is stored, and the token sits after `#`
  so it never reaches server logs. Password reset links last 30 min.
- **No account enumeration**: sign-up, resend and forgot-password always
  give the same answer; a wrong email and a wrong password give the same
  401; timing is equalised with a dummy hash.
- **Lockout**: 5 wrong passwords for an address in 15 min lock it for
  15 min (tracked for unknown addresses too). Gateway rate limits: 30/min
  per IP on login / register / verify / reset / change-password, 6/min on
  forgot-password / resend.
- **Sessions**: access token (60 min) in memory; refresh token (7 days) in
  an httpOnly, SameSite=Strict cookie scoped to `/api/auth`, with
  double-submit CSRF on refresh and logout. Refresh tokens carry the
  user's `token_version`; changing / resetting a password, a role change,
  disabling the account or "sign out everywhere" bumps it, ending other
  sessions at their next refresh.
- **Everywhere**: identity for audit fields comes from the JWT, never the
  request body; role checks on every route; uploads virus-scanned (fail
  closed) and type-checked by content; bank numbers masked for non-finance
  roles; published default secrets refused outside development; every
  port except the gateway bound to localhost; CSP and security headers;
  unexpected errors logged with a traceback but returned as a generic 500;
  validation errors never echo submitted values.
- **Kafka**: each service logs in with its own SASL/SCRAM account and may
  only use its own topics (`infra/redpanda/acls.conf`, kept in sync with
  the code by `tests/test_kafka_acls.py`). Traffic is not TLS-encrypted
  (single Docker host).

### Document pipeline

| Stage | Where | Outcome |
|---|---|---|
| Gateway | nginx | Over 25 MB → JSON 413 |
| Upload checks | `api/documents.py`, `upload_service.py` | Empty → 400; virus → 422; ClamAV down → 503; type from bytes (not extension) → 415; PDF page / image pixel caps; sanitised names |
| Store + record | MinIO + `documents` row `pending` + audit + outbox event, one transaction | MinIO down → 503, nothing half-written |
| Claim | worker (Kafka, 6 partitions) | `pending → processing`; a redelivered event can't process twice |
| Read the file | separate process, 120 s limit | pdfplumber for text PDFs, Docling for scans, PaddleOCR for images; unreadable / blank / too slow → `failed` with a readable message |
| Understand | `services/pipeline.py` | keyword classifier (an ML classifier is wired in but no trained model is shipped) → field extraction → LayoutLMv3 cross-check (if downloaded) → vendor match / GSTIN / IFSC, first-seen bank details held → learned labels → invoice ledger match → duplicate check (per-vendor lock) → confidence (< 0.8 → review queue) |
| Save | one transaction | `classified` + events; a dependency down → back to `pending`, retried after 1–4 min, `failed` after 5 attempts |

A sweep every minute re-queues documents stranded in `pending` or
`processing`.

### Platform controls

Visible on the **Controls** page (`/app/controls`, finance + admin), each
with a live scenario (showcase mode):

| Control | Where |
|---|---|
| Transactional outbox, consumer retry + dead-letter table, purchase-request state machine, reconciler | `shared/eventing/`, `shared/lifecycle.py`, `approval-inventory-agent/app/services/order_monitor.py`, `/api/ops/*` |
| Approval authority + separation of duties + delegations | `approval-inventory-agent/app/services/approval_authority.py`, `/api/authority/*` |
| Invoice ledger: line-level three-way match, partial invoicing, 1 % tolerances (business rules) | `approval-inventory-agent/app/services/invoice_ledger.py`, `/api/invoices/*` |
| First-seen bank details → verification queue + payment hold (dual control) | `document-vendor-agent/app/services/pipeline.py`, `/api/vendors/payment-changes/pending` |
| Learning from reviewer corrections (per-vendor field labels and review thresholds) | `document-vendor-agent/app/services/learning.py` |

Not everything is covered yet: some events are still published directly
rather than through the outbox, and notification-agent's consumer isn't
wrapped with the retry / dead-letter handler (TODO.md).

### Other features

- **Approvals**: spend tiers from the business-rules engine (≤ ₹500 auto,
  ≤ ₹5,000 manager, above that manager + finance); a Temporal workflow per
  request with SLA escalation. Decisions apply asynchronously (the UI
  polls).
- **License intelligence**: IsolationForest + SHAP on synthetic SSO logs;
  anomalous licenses get a reclaim request with a grace period
  (`services/approval-inventory-agent/README.md`).
- **Contracts**: Jinja2 templates → text + PDF; clause extraction on the
  generated text; e-sign via the HMAC-signed, replay-protected
  `POST /api/webhooks/esign`, or Documenso when configured (the Documenso
  client is tested against mocked HTTP only); signed copy download.
  Renewal reminders via a Temporal workflow (they currently count from the
  end date, not the notice deadline).
- **Vendor risk**: RandomForest on a synthetic dataset, logged to MLflow,
  per-vendor contributing factors, weekly PSI drift flag (never retrains
  itself).
- **Vendor vetting**: GSTIN format + checksum (+ optional live lookup with
  quota auto-cutoff), IFSC via Razorpay's free API, spend-based tiers.
- **Business rules**: 28 tunable rules edited live on an admin page with
  history; services refresh via Kafka.
- **Order monitor**: hourly summary of open orders (`/api/orders/summary/latest`).
- **Observability**: Prometheus metrics on every service, a provisioned
  Grafana dashboard (request rate, latency, errors, Kafka lag), JSON logs.

### Migrations

Each service owns its tables and migrates on start:
Alembic for auth-service and contract-risk-agent (own version tables,
since all services share one database), ordered raw SQL files for the
others (split by `shared/db/sql_runner.py`, idempotent). Base tables come
from `shared/db/init.sql` (applied by `install.sh`; don't edit it for new
work).

## Troubleshooting

- **502 from the gateway after rebuilding a service**: nginx caches upstream
  addresses at boot — `docker compose restart nginx`.
- **429 "Too many requests from your network"**: gateway rate limit on auth
  endpoints; wait a minute.
- **429 "Too many failed sign-in attempts"**: account lockout; wait 15 min or
  reset the password.
- **Sign-up returns 503**: the breached-password service is unreachable (no
  internet).
- **No confirmation email in Mailpit**: `docker compose logs auth-service |
  grep "account email"` shows the reason.
- **First document upload is slow** (~45 s): models loading.
- **LayoutLMv3 "skipped_model_unavailable"**: run `./scripts/download-models.sh`.
- **ClamAV unhealthy / uploads 503**: it needs ~1 GB RAM; raise Docker's
  memory limit.

## Data provenance

All data is synthetic; see each folder's README under `data/`
(`synthetic-invoices`, `synthetic-vendors`, `synthetic-sso-logs`,
`synthetic-classification`) and [`data/README.md`](data/README.md) for
the retention policy and which tables hold personal data.
