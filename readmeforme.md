# IT Procurement Intelligence Platform

Five cooperating services ("agents") that automate IT procurement:
reading invoices, POs and quotes; routing purchase requests for approval;
tracking inventory and SaaS license usage; generating contracts and
collecting e-signatures; scoring vendor risk; and emailing the people
involved. They share one Postgres database, talk over Kafka, and sit
behind one nginx gateway that also serves the React frontend.

A student team project (Anjali, Vaidehi, Niraj, Anooj). It's a working,
tested prototype, not a production deployment — see [TODO.md](TODO.md)
for what's open (with the roadmap), `git log` for what changed, and
[docs/showcase.html](docs/showcase.html) for how to present it (full walkthrough for external evaluators, what's-new run for mentors).

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

| Service | Port | Does |
|---|---|---|
| document-vendor-agent (+ worker) | 8001 | Upload (virus scan, type checks) → MinIO; worker extracts text, classifies, extracts fields, matches/vets vendors, books invoices against the ledger, flags duplicates |
| approval-inventory-agent (+ worker) | 8002 | Purchase requests, Temporal approval workflows, approval authority, inventory, license usage anomaly model + reclaim, invoice ledger, order monitor |
| contract-risk-agent (+ worker) | 8003 | Contract generation (text + PDF), e-sign webhook / Documenso client, renewal reminders, vendor risk model (RandomForest, MLflow) and drift check, offboarding |
| notification-agent | 8004 | Consumes events, renders email templates, sends immediately or in digests (to Mailpit) |
| auth-service | 8005 | Accounts, login/sessions, email verification and password reset, roles, business-rules engine |

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

## Run on Linux (Ubuntu VM in UTM on a Mac)

Measured Oct 16: the running stack uses ~3.2 GB RAM idle and more while
reading scans; its images are ~15 GB, plus build cache and data volumes.

1. **Create the VM.** UTM → Create a New Virtual Machine →
   **Virtualize** (not Emulate: an Apple Silicon Mac runs ARM64 Linux at
   full speed, emulated x86 would be far too slow) → Linux → the
   **Ubuntu Server 24.04 LTS ARM64** ISO. Give it **4+ CPU cores, 10 GB
   RAM (8 GB minimum), 80 GB disk**; network "Shared Network". Install
   with the defaults and tick **Install OpenSSH server**.
2. **Install Docker and git** (inside the VM):
   ```bash
   sudo apt update && sudo apt install -y git curl python3-venv
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER && newgrp docker   # or log out and back in
   docker run --rm hello-world
   ```
3. **Get the code and start it:**
   ```bash
   git clone https://github.com/AnoojShete/ProcurementAutomation.git
   cd ProcurementAutomation && git checkout anjali   # the branch with the latest work
   ./run.sh                          # first run builds everything: 20-40 min on 4 cores
   ./scripts/download-models.sh      # optional: LayoutLMv3 cross-check (~500 MB)
   ./scripts/seed-demo-data.sh       # demo vendor, requests, licences, stock
   ```
   `.env` is created from `.env.example`; don't copy the Mac's `.env`
   (it holds real keys).
4. **Open it from the Mac.** Find the VM's address with `ip -4 addr`
   (e.g. `192.168.64.5`). Simplest is an SSH tunnel, so every link and
   email works as `localhost` (only the app on :8080 listens outside the
   VM; Grafana, Mailpit, Temporal UI, MinIO listen inside it only):
   ```bash
   ssh -N -L 8080:localhost:8080 -L 8025:localhost:8025 -L 3000:localhost:3000 \
       -L 8088:localhost:8088 -L 9001:localhost:9001 <user>@192.168.64.5
   ```
   then http://localhost:8080 (stop the Mac's own stack first, or use
   other local ports). Without the tunnel, http://192.168.64.5:8080 also
   works for the app, but email links point at `APP_BASE_URL`
   (`localhost:8080`).
5. **Tests in the VM:** `./scripts/test-service.sh all`, and for the e2e
   scripts `python3 -m venv .venv && . .venv/bin/activate && pip install
   -r tests/e2e/requirements.txt`, then `make e2e` etc. (wait a minute
   between suites — gateway rate limits).

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
users/topics/ACLs and the MinIO bucket) → builds the images that need it →
builds the frontend in a `node:20-alpine` container if it changed → starts
the services (each applies its own migrations on start) → recreates nginx
last → waits for health checks. It prints one line per step plus an agent
health table; full output goes to `.run/run.log` and its tail is shown on
failure.

Images are rebuilt only when files under `services/<name>/` or `shared/`
changed since their last build, so the first run takes several minutes and
later runs take seconds. `./run.sh --build` rebuilds everything,
`./run.sh --no-build` just starts the existing images, `--verbose` shows all
output. Each worker runs its service's image (it isn't built separately).

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
| `PUBLIC_BASE_URL` | `http://localhost:8080` | External gateway URL used for email action links (`/email-action/*`). In production, **must be HTTPS** because plain HTTP exposes action tokens to network sniffing. |
| `INTERNAL_SERVICE_TOKEN` | `dev-internal-service-token-change-me` | Secret for internal service-to-service calls (`POST /internal/email-actions/mint`). Never exposed at the gateway. |
| `ENABLE_SIGN_SIMULATED` | `false` | When false, `POST /contracts/{id}/sign-simulated` is disabled. Set true only for demo/dev without Documenso/DocuSign. |
| `AUTH_LOCKOUT_THRESHOLD` / `_WINDOW_MINUTES` / `_MINUTES` | 5 / 15 / 15 | Wrong passwords per address before a temporary lock. |
| `AUTH_COOKIE_SECURE` | off in development | Turn on behind HTTPS. |
| `APP_SHOWCASE_MODE` | on in development only | Enables the Controls page scenario endpoints. |
| `GSTINCHECK_API_KEY` | placeholder | Only for live GSTIN lookups (off by default, admin toggle). |
| `APP_DOCUMENSO_API_URL` / `_API_TOKEN` / `_WEBHOOK_SECRET` | unset | With these, "Send for signature" uses Documenso; unset = simulated signing. |
| `VITE_SHOW_DEMO_ACCOUNTS` (frontend build) | shown | Set to `false` when building for real users to hide the demo-login buttons. |

> [!NOTE]
> **Authorization vs. Signature**: An email approval records an **AUTHORIZATION** decision; the e-signature provider's flow (Documenso / DocuSign) produces the legally binding **DIGITAL SIGNATURE**. An email approval button is never described or treated as a digital signature.

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
| Email action (single-action token) | http://localhost:8080/email-action/… |
| Mailpit (all dev email) | http://localhost:8025 |
| Grafana (admin / admin) — Logs dashboard by correlation id | http://127.0.0.1:3000 |
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

### Finding your way around the app

- **Every item has one home page, and its actions live there.** A request
  (approve / reject) → `/app/requests/:id`; a contract (download, send
  for signature, sign, signature certificate) → `/app/contracts/:id`; a
  license (usage, anomaly reasons, reclaim, and any open reclaim request's
  approve / reject) → `/app/licenses/:id`; a vendor (risk, bank-detail
  verification) → `/app/vendors/:id`; a document (review) →
  `/app/documents/:id`. Lists, dashboards and the approval inbox open
  those pages — a license reclaim in the approval inbox opens the license
  page, the same page the Licenses tab opens.
- **The same action panel everywhere.** Each agent's actions are one
  component (`frontend/src/components/approvals/ApprovalActions.tsx`,
  `components/contracts/ContractActions.tsx`,
  `components/vendors/PaymentChangeVerify.tsx`) that talks only to that
  agent's API, reused wherever the item appears — so approving or signing
  works the same from every entry point.
- **Clickable lifecycle.** On a request, click any step of the Procurement
  Lifecycle for its details; the Approval step has approve / reject, the
  Contract step the contract's actions, and the Signature step opens the
  signing dialog. `?step=approval` in the URL opens a step directly.
- **Back arrow** at the top left of every page except the dashboard (and
  on the signed-out pages, back to sign-in).

API example:

```bash
curl -s -X POST http://localhost:8080/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"approver@demo.example.com","password":"DemoPass123!"}'
# {"data": {"access_token": "…", "token_type": "bearer", "expires_in_minutes": 60}}
# (the refresh token is set as an httpOnly cookie, not returned)
curl -s http://localhost:8080/api/requests/ -H "Authorization: Bearer <access_token>"
```

## Testing

Counts from Oct 16 unless a row says otherwise; the fresh-clone setup was
last verified on Sep 27 (separate Docker project, empty volumes).

| Command | What | Result |
|---|---|---|
| `./scripts/test-service.sh all` (or `make test`) | Each service's pytest suite inside its image, source mounted | 530 passed, 2 skipped (contract-risk 103, approval-inventory 113, document-vendor 215, notification 39, auth 60) |
| root tests (command below) | `shared/` code and config checks (Kafka ACLs vs code, nginx rules, lifecycle, outbox, mailer) | 123 passed, 1 failed (`test_mailer`: `.env.example` points at Gmail, not Mailpit), 4 skipped; `test_email_action.py` needs `redis` in the image |
| `make e2e` | Bash flow through the gateway: login, ClamAV reject/accept, request → approve → contract → signed webhook → risk → email → business-rule change | 17/17 (Sep 28) |
| `python tests/e2e/auth_flows.py` | Sign-up → email → confirm → login → change password → logout → forgot/reset, expired / reused links, lockout, enumeration, rate limit (reads Mailpit) | 42/42 |
| `python tests/e2e/invoice_lifecycle.py` | One fresh vendor's quote + invoice through all five agents, no DB shortcuts | 71/71 (adds auto-send after approval, mark-as-received, risk signal coverage) |
| `python -m pytest tests/e2e/test_flow.py` | Core flow + webhook bad-signature / replay | passed |
| `python tests/e2e/document_pipeline.py [--quick]` | Normal / huge / corrupt / empty / wrong-type / pathological files, duplicates, outages | 52/52 (`--quick`, Oct 15) |
| `python tests/e2e/ui_flows.py` | Browser (Playwright): back arrow, clickable lifecycle, approve and sign from lifecycle steps, approval-inbox routing, license page's open-request panel | 11/11 (needs `pip install playwright && python -m playwright install chromium`) |
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
frontend/        React + TypeScript + Vite + Tailwind: src/pages (one home page per item), src/api (one module per agent),
                 src/components/<agent>/ (each agent's action panels); legacy-static/ = old version, unused
infra/           nginx/nginx.conf, redpanda/ (acls.conf, bootstrap.sh), prometheus/, grafana/ (k8s/ is empty)
tests/           root tests; e2e/ (run.sh, auth_flows.py, invoice_lifecycle.py, document_pipeline.py, test_flow.py, ui_flows.py)
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
| Read the file | separate process, 120 s limit | pdfplumber for text PDFs, Docling for scans, PaddleOCR for images (deskewed and upscaled ≤ 1.5× first while the rule `document.image_preprocessing` is on; numbers in `docs/results/extraction.md`); unreadable / blank / too slow → `failed` with a readable message |
| Understand | `services/pipeline.py` | keyword classifier (an ML classifier is wired in but no trained model is shipped) → field extraction → LayoutLMv3 cross-check (if downloaded) → vendor match / GSTIN / IFSC, first-seen bank details held → learned labels → invoice ledger match → duplicate check (per-vendor lock) → confidence (< 0.8 → review queue) |
| Save | one transaction | `classified` + events; a dependency down → back to `pending`, retried after 1–4 min, `failed` after 5 attempts |

A sweep every minute re-queues documents stranded in `pending` or
`processing`.

Re-measure extraction accuracy (adds rotated / noisy / half-resolution
copies of every image, with and without preprocessing):

```bash
docker run --rm -e LD_PRELOAD=libz.so.1 -v "$PWD/services/document-vendor-agent:/app" \
  -v "$PWD/shared:/app/shared" -v "$PWD/data/synthetic-invoices:/data:ro" -v "$PWD/docs/results:/out" \
  -w /app --entrypoint python procurementautomation-document-vendor-agent scripts/eval_extraction.py
```

### Reorder suggestions

Each hardware item has a reorder point and a reorder quantity — set per
item (Inventory → pencil, admin/finance; `PATCH
/inventory/{id}/reorder-settings`) or, when empty, a share of the item's
total stock from the rules `inventory.reorder_point_pct` (20) and
`inventory.reorder_quantity_pct` (25). An item needs reordering when the
stock left after its backordered requests is at or below the reorder
point; the suggestion is *owed + top-up to the reorder point + reorder
quantity*, explained on the Inventory page
(`app/services/reorder.py`).

### Vendor onboarding

Finance / admin: Vendors → **Onboard vendor**. The profile is checked
by `POST /vendors/onboard/validate` as you go and again on save
(`POST /vendors/onboard`, `app/services/vendor_onboarding.py`):

| Check | Result |
|---|---|
| Name missing, bad email / phone / account number, GSTIN format or check digit, IFSC format or not in the directory | error — blocks |
| Same GSTIN as a vendor, or a name ≥ the fuzzy-match threshold (88) | error — duplicate |
| Name 70–87 % similar to a vendor | must be confirmed (possible impostor) |
| No GSTIN | must be confirmed with a reason (audit-logged) |

Bank details are never written onto the vendor: they become a pending
payment change (`source="onboarding"`) that a second person verifies.

### Email intake

Documents emailed to `invoices@procurement.local` (setting
`EMAIL_INTAKE_ADDRESS`) enter the same path as an upload — virus scan,
MinIO, pipeline — read by the document worker over POP3 or IMAP
(`EMAIL_INTAKE_PROTOCOL/HOST/PORT/SSL/USER/PASSWORD`; in development it
reads Mailpit's POP3, so mail sent to Mailpit's SMTP on :1025 is picked up
within 30 s). The mailbox is only read: each message is handled once
(`email_intake` table, with the reason for any rejected attachment), and
mail to other addresses is ignored. The document page shows "By email from
<sender>". Emailed documents follow the normal reviewed flow.

### Drop folder → signed contract (fully automated)

Put a vendor quote (PDF/PNG/JPEG) in `./inbox`. No clicks after that:

| Step | Who | Kafka event |
|---|---|---|
| File noticed (size stable for one 3 s poll), moved to `inbox/.processing/` | document-vendor-agent-worker (`inbox_watcher.py`) | — |
| ClamAV scan → MinIO → `documents` row, uploader `inbox@procurement.local` | same code as a UI upload | `document.ingested` |
| Read / classify / match vendor | worker pipeline | `document.classified`, `vendor.matched` |
| Quote → purchase request (skipped while it needs review, for duplicates, or without vendor/total) | approval-inventory-agent consumer | `approval.requested` |
| Auto-approved under the spend threshold, else the normal approvers | approval-inventory-agent | `approval.decided` |
| Contract generated, then sent for signature **once** (built-in e-sign: an authorised signatory signs in the app) | contract-risk-agent consumer | `contract.generated` |
| Signed in the app → request `ordered` | contract-risk-agent → approval-inventory-agent | `contract.signed` |

The file ends up in `inbox/processed/`, or in `inbox/failed/` with a
`.error.txt`. Since Oct 16 requests made in the app are auto-sent for
signature too (rule `contract.auto_send_scope`, `drop_folder` restores the
old behaviour).

**Control Panel** (admin, `/app/control-panel`) shows it live: the Kafka
event log (every topic, read through a read-only `event-monitor` Kafka
login, payloads reduced to ids and statuses — no bank details; stored in
`event_log`, so it survives restarts, filterable by topic, time, text and
correlation id, kept `monitor.event_log_retention_days`), a **Failed
events** panel (open dead-letter entries with their error), each
dropped file's current step with links to its document / request /
contract, and the MinIO and DocuSign connections.

**Risk before signing.** The contract page and the signing dialog show
the vendor's latest risk (band, score, main factors, any hard override).
Signing a contract whose vendor is High risk — or not scored, or not
linked — needs the signer to tick an acknowledgement; the API refuses
it otherwise (409 `risk_acknowledgement_required`) and the signature
certificate records the band and the acknowledgement
(`contract_service.signing_risk`).

**Sanctions screening.** `./scripts/download-sanctions.sh` (once; ~80 MB,
no API key, OpenSanctions consolidated list, CC BY-NC 4.0) builds an index
of listed companies in the `sanctions-data` volume; contract-risk-agent
refreshes it daily afterwards. Each vendor is screened when scored (and
from the vendor page); a name at or above `risk.sanctions_match_threshold_pct`
(90) is a potential match and a hard override (High) until finance clears
it with a reason (`POST /vendors/{id}/clear-sanctions-flag`, audit-logged).

**Risk signals.** Before every score the model's inputs are refreshed
from platform history: tenure (since the vendor's first record) and
on-time delivery (contract signed → goods received within
`vendor.expected_delivery_days`, default 14). A sweep re-scores vendors
after a delivery. Finance records the compliance signals (security
certification, breach disclosures, high-risk geography, financial
stability) on the vendor page — audit-logged, re-scores at once
(`app/services/risk_signals.py`, `PATCH /vendors/{id}/risk-signals`).
The drift check compares each vendor's latest score with ≥ 3 signals on
file against the training distribution.

The DocuSign client is kept but unused (built-in e-sign only since
Oct 15). To try it anyway: the DocuSign block in `.env.example`,
`APP_ESIGN_AUTO_PROVIDER: docusign` in contract-risk-agent's environment
in `docker-compose.override.yml` (compose doesn't pass it through
otherwise), restart contract-risk-agent, then
**Grant consent** on the Control Panel once.

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
  generated text; sent for signature automatically after every approval
  (business rule `contract.auto_send_scope`); signed with the **built-in
  e-sign** — the only option offered in the UI since Oct 15 (an
  approver/finance/admin signs in the app — typed or drawn signature,
  consent, and a SHA-256 seal of the contract and signer details in the
  audit log, viewable as a signature certificate; the signer is always the
  signed-in account). The HMAC-signed, replay-protected
  `POST /api/webhooks/esign` remains for tests and integrations; the
  DocuSign / Documenso clients are kept in the code but unused. Signed
  copy download. Signing sets the request to `ordered`; "Mark as
  received" sets `fulfilled`. The
  seal is an unkeyed hash: it shows tampering only as far as the audit log
  itself is trusted.
  Renewal reminders via a Temporal workflow, counted back from the notice
  deadline (end date − notice period); the contract page shows the next one.
- **Vendor risk**: hard overrides first (cancelled/suspended GSTIN → High),
  then a RandomForest trained at image build on 2,000 seeded synthetic
  vendors; missing signals are left out, and the vendor page shows "based
  on N of 6 signals". Evaluation in `docs/risk-model.md` (ROC-AUC 0.715,
  red-team 12/12). Weekly PSI drift flag (never retrains itself).
- **Vendor vetting**: GSTIN format + checksum (+ optional live lookup with
  quota auto-cutoff), IFSC via Razorpay's free API, spend-based tiers.
- **Business rules**: 28 tunable rules edited live on an admin page with
  history; services refresh via Kafka.
- **Order monitor**: hourly summary of open orders (`/api/orders/summary/latest`).
- **Reminders** (`reminder.due`, `shared/reminders.py`): approvers at 50 % /
  80 % of the SLA (Temporal timers, stopped by a decision); signers after
  3 days; bank-detail verifiers and document reviewers after 24 h — all
  business rules, each item reminded once per threshold. Emails for them
  are notification-agent work (spec in TODO FR-03).
- **Observability**: Prometheus metrics on every service, a provisioned
  Grafana dashboard (request rate, latency, errors, Kafka lag), JSON logs.
  Every API request gets a correlation id (nginx `X-Correlation-ID`,
  echoed in the response) that follows it through events into every
  service; Loki + Promtail collect all logs, and Grafana's **Logs**
  dashboard shows one id's lines across services. Open Grafana at
  `http://127.0.0.1:3000` (admin / admin) if `localhost:3000` is taken by
  something else on your machine.

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
