# Changelog

Newest first. Dates are 2026. Nothing below the Sep 25 merge has been
committed yet (branch `anjali`); see TODO.md for open items.

## Sep 28 — Old branches cleaned up

Checked every remote branch against `anjali`. Only `first` (Aug 24) had
something still useful: its inventory-lock fix, now ported —
`reserve_stock` holds the Redis lock only while it updates the database
(unique token, released in `finally`); the reservation itself lives in
`reserved_quantity`. Before, the lock (keyed by SKU, 5-minute TTL) was
kept after a successful reservation, so a second order for a well-stocked
SKU looked out of stock. Regression test `test_inventory_reservation.py`.
The rest of `first` and `combine` were August versions of files that have
moved on; the other branches had no commits missing from `anjali`.

Deleted (tip commits, restorable with `git push origin <sha>:refs/heads/<name>`
while GitHub still has them): anooj1 7843c54, anooj2 ef8dcc2,
combine 64e9ab2, copilot/research-procurement-agent-capabilities 0d06e67,
demo 0d06e67, first 1d11488, main-old 14ed52e, niraj 258d175,
niraj2 27f77a4, without_clamav 4bd5ea4. Kept: `main`, `anjali`.

## Sep 28 — Merged `withesign` (Niraj)

Brought in built-in e-signing: `POST /contracts/{id}/sign` (typed or drawn
signature, consent, SHA-256 seal stored in the audit log),
`GET /contracts/{id}/signature-certificate`, the signature and certificate
modals, `pool_pre_ping` on every service's DB engine, null-safe document
saving, and a 50-char checkpoint status column.

Changed while merging:
- Kept our Documenso client (uploads the PDF, places the signature field,
  reports failures) over the branch's, which sent no file, silently
  returned a fake reference on any error, and read a setting that doesn't
  exist.
- Did **not** take the branch's unauthenticated Documenso handling on
  `/webhooks/esign` (no signature check; an empty document id matched any
  contract, so anyone could mark a contract signed). Documenso callbacks
  use the authenticated `/webhooks/documenso`; the esign payload is strict
  again. Test added.
- `/sign`: the signer is the signed-in user (the body's email is ignored),
  approver/finance/admin only (was any role, including requesters),
  draft / awaiting-signature contracts only, not for live Documenso
  documents; `contract.signed` goes through the outbox. nginx now passes
  `X-Real-IP` so the certificate records the client, not the gateway.
- The certificate endpoint no longer invents a certificate (made-up seal
  and IP) for contracts signed another way — it returns 404.
- Kept: `APP_ESIGN_WEBHOOK_SECRET` (the branch reverted to the unprefixed
  name the service ignores), the `asyncio.sleep` renewal timer, the retry
  path for temporary pipeline failures, and outbox publishing for
  document events (the branch's direct publish would have sent them twice).
- The Documenso settings are now actually passed into the container
  (they never were).
- UI wording no longer states the signature is "verified" or "legally
  executed".

Verified: 419 service tests + 116 root tests, `make e2e` 17/17, invoice
lifecycle 63/63, auth flows 42/42, `test_flow.py`, and a live signing check
(requester 403, spoofed email ignored, certificate + signed PDF, unsigned
Documenso payload 422).

## Sep 27 — Docs audit

Every `.md` file checked against the code; a fresh clone was set up by
following only the README (separate Docker project, fresh volumes) and
every test suite was run on it.

**Docs**: README rewritten (setup, env vars, testing, structure); TODO
regrouped by priority; SHOWCASE rewritten to claim only what exists;
new CLAUDE.md; history from README, SHOWCASE and AUDIT_CHANGES.md merged
here (AUDIT_CHANGES.md deleted); approval-inventory-agent README,
`data/README.md` and `data/synthetic-sso-logs/README.md` corrected.

**Fixes the audit proved necessary** (each reproduced first):
- **Account emails never sent on a fresh clone.** `install.sh` copies
  `.env.example` to `.env`, and `.env.example` set `SMTP_PORT=587` /
  `SMTP_SECURITY=starttls`, which overrode the Mailpit defaults. Those two
  are now blank; `tests/test_mailer.py` loads `.env.example` as-is.
- **E-sign webhook returned 500 on a fresh database.** `shared/db/init.sql`
  creates `processed_webhook_events` with `event_id` / `source NOT NULL`,
  columns the service never sets. contract-risk-agent migration 0005 makes
  them nullable (non-destructive).
- **Unhandled 500s were never logged.** The shared error handler now logs
  the exception and traceback (the client still gets a generic message);
  the auth mailer logs the failure reason in the message, since the JSON
  log formatter drops `extra` fields.
- **Declining a license reclaim crashed** (`NameError: get_rule` in
  `approval_service.decline_reclaim`, found by lint). Import added,
  regression test `test_decline_reclaim.py`.
- `tests/e2e/requirements.txt` lacked `pytest` (needed by `test_flow.py`).

## Sep 26 — Ready for real users

- **Accounts**: sign-up → email confirmation → login → logout / sign out
  everywhere → forgot / reset password → change password; admin Users page
  (role, enable/disable). New accounts are requesters.
- **Passwords**: argon2id (argon2-cffi defaults: 64 MiB, t=3, p=4);
  legacy bcrypt hashes verify and are upgraded at login; 12–128 chars, not
  containing the email, HaveIBeenPwned check (fails closed).
- **Email**: `shared/mailer.py`, `EMAIL_MODE=dev` (Mailpit) or `smtp`
  (Gmail app password, Brevo, Resend, SendGrid, SES…); multipart
  text + HTML, From / Reply-To; refuses incomplete or unencrypted SMTP
  settings, and dev mode outside development.
- **Safety**: single-use expiring links (24 h / 30 min, SHA-256 in the DB,
  new link cancels old, 60 s resend cooldown); generic answers on sign-up,
  resend and forgot-password; lockout after 5 wrong passwords in 15 min
  (per address, known or not); `token_version` in refresh tokens ends
  other sessions on password change / reset / role change / disable;
  gateway rate limits on all auth endpoints (stricter on email-sending
  ones) with a JSON 429; 422 responses no longer echo submitted values.
- **Database**: auth migration 0003 (account columns, `auth_tokens`,
  `auth_login_attempts`, case-insensitive unique email, role check);
  foreign keys, CHECK constraints and indexes for documents, purchase
  requests, invoice matches and contracts (document migration 0006,
  approval integrity section, contract migration 0004);
  `shared/db/sql_runner.py` splits SQL files safely (quotes, `$$`,
  comments). Existing data was checked first; nothing destructive.
- **Tests**: 23 account-flow tests against a throwaway Postgres DB,
  `tests/e2e/auth_flows.py` (42 checks via the gateway and Mailpit),
  mailer tests; 10 deliberate-break mutations all caught.

## Sep 26 — Document pipeline hardening

Real files (normal, large, over-limit, corrupt, empty, blank, wrong type,
pathological, duplicates, outages) run through the whole pipeline;
`tests/e2e/document_pipeline.py` covers them. Among the fixes: text
extraction in a separate process with a 120 s limit (a crafted PDF used to
block the worker); magic-byte type checks, PDF page / image pixel caps,
sanitised storage keys; JSON 413 at the gateway; an advisory lock around
the duplicate check; retry with growing delay (5 attempts) when a
dependency such as the invoice ledger is down; a sweep that re-queues
stranded documents; Redis for the document agent's idempotency keys;
`workflow.sleep` (not in temporalio 1.6) replaced in the renewal
workflow.

## Sep 26 — Sessions and Kafka logins

- Refresh token moved to an httpOnly, SameSite=Strict cookie scoped to
  `/api/auth`, with double-submit CSRF on refresh / logout.
- Every service logs in to Redpanda with its own SASL/SCRAM account;
  `infra/redpanda/acls.conf` limits each to its own topics
  (`redpanda-init` applies it); `tests/test_kafka_acls.py` keeps the
  table in sync with the code.

## Sep 26 — Security audit

Uploader identity from the JWT; requesters see only their own documents
and requests; bank numbers masked for non-finance roles; invoice ledger
writes limited to the pipeline's service token; approval decisions bound
to their level; `APP_ENV` (default production) refuses published default
secrets and disables demo features; all ports but the gateway bound to
127.0.0.1; CSP / Permissions-Policy; per-user idempotency keys; GSTINCheck
key redacted from logs; dependency bumps (pyjwt, jinja2,
python-multipart, pydantic-settings).

## Sep 26 — Platform controls

Transactional outbox, consumer retry + dead-letter table, purchase-request
state machine and reconciler; approval authority matrix with separation
of duties and delegations; invoice ledger (line-level three-way match,
partial invoicing, 1 % tolerances); first-seen bank details held for
verification with payment hold; learning from reviewer corrections;
Controls page with live scenarios.

## Sep 26 — Meeting-minutes items

Parallel Kafka document processing, multi-file upload, contract PDF
generation, signed-copy download, Documenso API client and webhook
(unit-tested against mocked HTTP only), order monitor agent
(`/orders/summary/latest`), UI redesign.

## Sep 25 — Invoice lifecycle test

`tests/e2e/invoice_lifecycle.py` (one fresh vendor's quote and invoice
through all five agents, no DB shortcuts). Its first run found: 3-way
matching could never match (no service token on `/requests/search`);
`invoice.matched` / `contract.signed` handlers crashing; a too-short
checkpoint column marking documents failed; LayoutLMv3 never running
(torch too old, model not downloaded); reclaim automation failing every
scan; no audit entries for uploads. All fixed.

## Sep 25 — System Health page crash

`/admin/model-routing-log` returned NUMERIC columns as strings and the
page called `.toFixed()` on them; API casts to float, page coerces.

## Sep 25 — ClamAV added back

Removed on Sep 24 because it took 2–3 min to start (x86 emulation on
Apple Silicon). Switched to the native multi-arch `clamav/clamav-debian:1.5`
with a 1 s health check: healthy in ~5 s (measured on an M-series Mac).
Uploads fail closed (503) if it's down; 25 MB limit at nginx, API and
clamd.

## Sep 25 — Merge of `anooj2` into `anjali`

Brought in (Niraj) license-anomaly ML (IsolationForest + SHAP), reclaim /
reinstate workflows, GSTIN / IFSC vendor vetting, PaddleOCR in a
subprocess, LayoutLMv3 cross-check, doc-type-specific processing,
business-rules engine and admin page, System Health page, kafka-exporter,
e-sign provider selection; (Anooj) self-registration with breached-password
check, stricter JWT claim checks, notification routes behind JWT.

Fixed during the merge: an approve route with no role check; request and
decision identity taken from the body instead of the JWT; role gaps on
`confirm-no-gstin` and `mark-reviewed`; a hard-coded GSTINCheck API key
(**still in git history — rotate it**); every upload failing
(`overall_confidence` dropped); the anomaly model never running in Docker;
a race that lost approval signals; the Apple Silicon build; Temporal UI
unreachable; two nginx routes to the wrong service.

## Sep 5 — First audit pass

E-sign webhook secret silently ignored (wrong env prefix); payment-change
dual control bypassable via a body field; approval inbox and notification
log readable by any user; webhook replay race returning 500; vendor-name
review crashing (missing import); MinIO console unreachable; gateway
security headers added.
