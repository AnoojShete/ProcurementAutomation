# TODO

Open work as of **Sep 27, 2026**, grouped by priority, each with why it
matters. Owner in brackets where it's someone's area. Everything here was
checked against the code on Sep 27; history is in CHANGELOG.md.

- **P0**: broken now, or a security exposure. Fix before the next demo /
  any shared deployment.
- **P1**: real gap in a feature or in safety; next in line.
- **P2**: hardening, cleanup, nice to have.

## P0

- [ ] **Invoices never finish processing.** approval-inventory-agent's
  ledger insert violates `fk_invoice_matches_vendor` (confirmed from the
  logged 500): the document pipeline sends a vendor id it created inside
  its own uncommitted transaction, which the ledger can't see. Every
  invoice from a new vendor retries 5 times then fails;
  `tests/e2e/document_pipeline.py` fails because of it. The FK was added
  on Sep 26. Options: drop that one FK (the vendor row belongs to another
  service's transaction), or commit the vendor before calling the ledger.
  *Why: the core invoice path is down.* [Anjali]
- [ ] **Rotate the GSTINCheck API key** (`67d40c75…`): committed as a
  default before Sep 25 and still in git history. Put the new one in
  `.env` only. *Why: leaked credential.* [Niraj]
- [ ] **Any non-local deployment**: set `APP_ENV=production` and real
  `JWT_SECRET`, `ESIGN_WEBHOOK_SECRET`, `RULES_ENGINE_INTERNAL_SECRET`,
  `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `KAFKA_PASSWORD_*`, Grafana
  admin password; `EMAIL_MODE=smtp`; `AUTH_COOKIE_SECURE=true` behind
  HTTPS; build the frontend with `VITE_SHOW_DEMO_ACCOUNTS=false`.
  Services refuse to start with the published defaults outside
  development. *Why: the demo secrets are public.*

## P1

**Security audit follow-ups**
- [ ] Upgrade FastAPI/Starlette (starlette 0.37.2 advisories), Pillow
  10.4.0, pdfminer.six 20231228 (via pdfplumber) — all parse untrusted
  uploads; needs a coordinated upgrade and a retest of Docling/Paddle.
  *Why: known CVEs on the upload path.*
- [ ] MLflow 2.14.3 has many advisories; bound to localhost for now.
  *Why: must not be exposed as is.*
- [ ] Contracts and contract PDFs are readable by any signed-in user;
  restrict to staff + the request's requester. *Why: commercial data
  leak to requesters.*
- [ ] Access tokens stay valid for up to `JWT_EXPIRY_MINUTES` (60) after a
  user is disabled or demoted — other services verify tokens without a
  DB lookup. Shorten to ~15 min (the frontend refreshes silently) or add
  a revocation check. *Why: disabling an account isn't immediate.*

**Document pipeline**
- [ ] Scanned PDFs pay Docling's cold model load (~60 s) per document,
  since extraction runs in a killable child process. Keep a warm process
  pool. *Why: throughput.*
- [ ] Images OCR badly on Apple Silicon: PaddleOCR crashes in the aarch64
  worker image, so PNG/JPG uploads fail with "couldn't read any text".
  Reproduce: `docker compose exec document-vendor-agent-worker python -c
  "from paddleocr import PaddleOCR"`. *Why: image uploads don't work on
  the team's Macs.* [Anjali/Vaidehi]
- [ ] The ML document classifier (`ml/train_classifier.py` →
  `classifier.joblib`) is wired in but no model is trained or shipped, so
  classification is always keyword-based. Train it in the image build or
  remove the dead path. *Why: docs and pitch mention ML classification.*
  [Vaidehi]

**Approvals / inventory** [Niraj]
- [ ] Anomaly model ranking looks wrong on the seeded data (a license at
  76 % utilisation scores anomalous). Tune before quoting savings.
- [ ] Two different SSO log generators: the committed dataset comes from
  `services/approval-inventory-agent/scripts/generate_sso_logs.py`
  (5 licenses); the repo-root `scripts/generate_sso_logs.py` makes a
  different 8-license set and would break the seeded licenses if run.
  Keep one. *Why: regenerating the data silently breaks the demo.*
- [ ] Seed or stub a demo reclaim request so the license page's approval
  panel can be shown without creating one first; and add
  `tests/e2e/ui_flows.py` (Playwright) to CI once tests run there.
- [ ] Signing up doesn't create an approval-authority assignment: a user
  promoted to approver can't approve until an admin adds one on the
  Controls page. Surface this on the Users page. *Why: confusing for
  real users.*

**Contracts** [Anjali]
- [ ] Renewal reminders fire 60/30/15 days before `contract_end_date`,
  not before the notice deadline (`end_date − notice_period_days`).
  *Why: reminders can arrive after the notice window closed.*
- [ ] The Documenso client is only tested against mocked HTTP; run it once
  against a real Documenso instance before calling it integrated.
  Without Documenso settings, signing is simulated.

**Platform**
- [ ] CI only builds images. Run `scripts/test-service.sh all`, the root
  tests and `npm run typecheck` in `.github/workflows/ci.yml` (e2e needs
  the full stack). *Why: this audit found three bugs a CI run of the
  fresh-clone e2e would have caught.*
- [ ] Wrap notification-agent's consumer with `shared/eventing.deliver`
  (retry + DLQ) like the other consumers. *Why: a failing event is
  dropped.* [Anooj]
- [ ] Move the remaining direct publishes to the outbox:
  `approval.requested`, `license.usage.updated`, `risk.score.updated`,
  `vendor.offboarded`, renewal alerts. *Why: an event can be lost on a
  crash between commit and publish.*
- [ ] `digest_service.flush_due_digests` retries a permanently failing
  digest forever. [Anooj]
- [ ] notification-agent: real SMTP (reuse `shared/mailer.py`) and real
  recipients (resolve approval levels through `approver_assignments`
  instead of placeholder role addresses), plus links to the item. Its
  mail still goes to Mailpit only. [Anooj — email automation]
- [ ] Assistant/chatbot must call `/orders/summary/latest` with a staff or
  service token (requesters get 403). [Anooj]

## P2

- [ ] approval-inventory-agent registers its own `HTTPException` handler
  with uppercase codes (`NOT_FOUND`) over the shared one (`not_found`).
- [ ] Lint: ~78 unused imports and ~15 redefinitions (e.g. duplicate
  imports in approval-inventory-agent `main.py` / `api/requests.py`).
  Add ruff to the repo and CI.
- [ ] `GET /inventory` runs the anomaly scorer per license per request
  (N+1); read the stored `anomaly_score`.
- [ ] Exact duplicate detection covers invoices only (POs/quotes
  uploaded twice aren't flagged).
- [ ] Batch upload scans files one at a time on one DB session.
- [ ] `mem_limit` / `cpus` on heavy containers (document worker: Docling
  + Paddle + LayoutLMv3, up to 4 in parallel).
- [ ] Health checks for `temporal-ui`, `mlflow`, `prometheus`, `grafana`,
  `nginx`; pin the `latest` images (redpanda, minio, prometheus, grafana,
  kafka-exporter, temporal-ui, mailpit) — a Temporal UI breakage already
  came from an unpinned image.
- [ ] Refresh tokens aren't rotated and there's no per-session revocation
  list (logout clears this browser's cookie; "sign out everywhere" ends
  all sessions). Fine for now; revisit for production.
- [ ] Kafka traffic is SASL_PLAINTEXT (no TLS); fine on one Docker host.
- [ ] TLS/HSTS at the gateway for anything beyond localhost.
- [ ] Sign-up returns 503 when HaveIBeenPwned is unreachable (offline
  demos can't create accounts). Decide: keep failing closed, or allow
  with a warning.
- [ ] The "you already have an account" email has no cooldown (the gateway
  per-IP limit is the only brake).
- [ ] Purge used/expired `auth_tokens` and old `auth_login_attempts` rows.
- [ ] `/documents/learning/stats` is readable by any signed-in user
  (vendor names and review counts only).
- [ ] Frontend: react-router 6 → 7 (open-redirect advisory), vite/esbuild
  major (dev server only); no ESLint configured.
- [ ] notification-agent: aiosmtplib 3.0.1 → 5.x. [Anooj]
- [ ] Classifier retraining from `extraction_feedback`; today learning
  covers field labels and per-vendor thresholds only.
- [ ] `seed_demo_users.py` prints the demo password to stdout; fine
  locally, not in a shared log pipeline.
- [ ] Remove the dead `vendorsApi.logOutcome` frontend call or wire it up.
- [ ] Repo cleanup: `install.sh` points to a `README-VM.md` that doesn't
  exist; `docker-compose.override.yml.example` is a stale 15-line stub;
  `infra/k8s/` is empty; `frontend/legacy-static/` is unused.
- [ ] External data for vendor risk (OpenCorporates, SEC EDGAR, SSL Labs),
  sanctions screening (OFAC / OpenSanctions), and validating clause
  extraction against CUAD — the "future scope" items; all current risk
  data is synthetic.
- [ ] Built-in e-sign seal is an unkeyed SHA-256 (tamper-evident only if
  the audit log is trusted); sign it with a server key (HMAC) if it has to
  stand on its own. The certificate also stores the drawn signature image
  in the audit row.
- [ ] Grafana: an approval SLA-breach panel needs a counter in
  approval-inventory-agent.

## The five platform capabilities (proposed and built Sep 26)

Outbox / DLQ / state machine / reconciler, approval authority, invoice
ledger, bank-detail quarantine + payment hold, learning from corrections —
all built and on the Controls page. What's partial is listed above:
outbox coverage, notification-agent DLQ, classifier retraining, and the
P0 ledger foreign key.
