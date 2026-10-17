# Testing strategy

How the procurement platform is tested: what is covered, the environment the
tests need, the scenario matrix used for the October 2026 quality audit, and
what is not covered. Findings and fixes from that audit are in
[quality-audit-report.md](quality-audit-report.md).

## 1. Scope

In scope: the five FastAPI services (document-vendor, approval-inventory,
contract-risk, notification, auth), their workers, the shared library
(`shared/`), the nginx gateway, the React frontend, and the flows between
them over Kafka, Temporal, Postgres, Redis, MinIO and ClamAV.

Out of scope for changes (tested only, by team agreement): the chatbot agent
and the email automation (Anooj's). External providers (DocuSign, Documenso,
GSTIN lookup, SMTP) are tested only through their error paths and test
doubles; nothing was sent to a real provider.

## 2. Test layers

| Layer | Where | Framework | What it proves |
|---|---|---|---|
| Unit + router tests | `services/<svc>/tests/` | pytest, FastAPI `TestClient` with dependency overrides | Business rules, validation, authorization, error mapping — no live dependencies |
| Shared / config tests | `tests/*.py` | pytest | `shared/` code, Kafka topic + ACL registry, business-rule registry, log redaction, security config |
| DB-backed auth tests | `services/auth-service/tests/test_account_flows.py` | pytest + throwaway `auth_test` database | Single-use links, lockout, enforced in SQL |
| Gateway e2e (bash) | `tests/e2e/run.sh` (`make e2e`) | curl + python | Health, auth, rules engine through nginx |
| Cross-agent e2e | `tests/e2e/invoice_lifecycle.py`, `document_pipeline.py`, `auth_flows.py` | python `requests` | One invoice through all five agents; upload pipeline; account flows with Mailpit |
| Frontend static | `frontend/` | `tsc --noEmit`, `vite build` | Types and build |
| Exploratory / audit probes | audit scratch scripts (not committed; cases listed in §5) | python `requests`, Playwright | Edge cases, IDOR, failure injection, UI crawl at 3 viewports |

New in this audit (all run inside the service images):

| File | Covers |
|---|---|
| `services/approval-inventory-agent/tests/test_qa_audit_regressions.py` (32 tests) | Amount/department/quantity validation, NaN body → 422, bounded `limit`, malformed id on approve/reject → 400, stock released when a request can't be saved |
| `services/contract-risk-agent/tests/test_contract_access.py` (22) | Requester sees only contracts on own requests (list, detail, PDFs, certificate, renewals); staff see all; Documenso non-JSON → 400; bounded `limit` |
| `services/notification-agent/tests/test_notification_log_access.py` (8) | Requester sees only notifications addressed to them, cannot widen with `?recipient=`; staff unchanged |
| `services/document-vendor-agent/tests/test_list_limits.py` (13) | Bounded `limit` on documents, review queue, vendors, model-routing log |
| `services/document-vendor-agent/tests/test_pipeline_resilience.py::test_short_digital_pdf_keeps_its_text` | One-line digital PDF is not reported as blank |

Every new test was shown to fail against the pre-fix code (run against a copy
of the service with the fixed files restored from `HEAD`), except the tests
that guard valid input from being rejected, which pass both before and after
by design.

## 3. Environment

- macOS (Apple Silicon), Docker Desktop, the full compose stack
  (`./run.sh`), `APP_ENV=development`, `EMAIL_MODE=dev` (Mailpit).
- Postgres 16.15, Redpanda, Temporal, Redis, MinIO, ClamAV, nginx on `:8080`.
- Service tests run in each service's own image with the source mounted
  (`scripts/test-service.sh`), so they test the working tree, not the image.
- Host Python for e2e: a virtualenv with `pip install -r tests/e2e/requirements.txt`
  (+ `playwright` for UI checks). Playwright used the cached Chromium build.
- Demo accounts (`requester@`, `approver@`, `approver2@`, `finance@`,
  `admin@demo.example.com`, password in `docs/readmeforme.md`).

The tests that need Postgres (auth account flows) use the separate
`auth_test` database. Audit probes used the demo database, with
disposable data tagged `QA-PROBE` (requests' `comments`, uploaded file names,
inventory SKU `QA-PROBE-SKU`) so it can be found and removed.

## 4. Commands

Start the system:

```bash
./run.sh                       # whole stack; rebuilds changed images
./scripts/seed-demo-data.sh    # demo vendor, request, licenses, inventory (first run)
```

After changing a service: `docker compose up -d --build <svc> <svc>-worker && docker compose up -d && docker compose restart nginx`, then `docker compose ps`.

Run the tests:

```bash
./scripts/test-service.sh all                 # every service suite (in its image)
./scripts/test-service.sh contract-risk-agent # one service
./scripts/test-root.sh                        # tests/ (shared code, config)
cd frontend && npm run build                  # typecheck + build
make e2e                                      # gateway e2e
python tests/e2e/invoice_lifecycle.py         # five-agent flow
python tests/e2e/document_pipeline.py --quick
python tests/e2e/auth_flows.py                # needs EMAIL_MODE=dev
```

Wait about a minute between e2e suites — the gateway rate-limits logins
per IP. `tests/e2e/demo_scenarios.py` and `showcase_screens.py` also rewrite
files under `docs/`; run them only when you mean to refresh those.

Ad-hoc lint (no linter is configured):
`docker run --rm -v "$PWD:/w:ro" -w /w --entrypoint sh procurementautomation-auth-service -c "pip -q install ruff && ruff check --no-cache --select F services shared tests"`.

## 5. Scenario matrix (October 2026 audit)

Status values: PASS, FAIL (defect found), FIXED (failed before, passes after
the fix), BLOCKED, NOT RUN. "Evidence" names the probe log line or test.

### 5.1 Authentication and sessions

| ID | Feature | Input / setup | Expected | Actual | Status |
|---|---|---|---|---|---|
| AUTH-01 | API auth | No token | 401 | 401 | PASS |
| AUTH-02 | API auth | Garbage token | 401 | 401 (message includes decoder detail) | PASS (see QA-17) |
| AUTH-03 | JWT | `alg: none`, role=admin | 401 | 401 "alg value is not allowed" | PASS |
| AUTH-04 | JWT | Role changed, original signature | 401 | 401 signature failed | PASS |
| AUTH-05 | JWT | `exp` changed | 401 | 401 | PASS |
| AUTH-06/07/08 | RBAC | Requester → admin, ops DLQ, users | 403 | 403 / 403 / 307 redirect drops port | PASS / QA-15 |
| AUTH-09/10 | Login | Wrong password / unknown email | Same 401 for both | Same message | PASS |
| AUTH-11/12 | Login | Empty / non-JSON body | 422 | 422 | PASS |
| AUTH-13 | Internal | `/internal/email-actions/mint` via gateway | Not reachable | 405 from nginx | PASS |
| SES-01 | Refresh | Cookie + CSRF header | 200 | 200 | PASS |
| SES-02 | Refresh | Cookie without CSRF header | 403 | 403 | PASS |
| SES-03 | Logout | Replay refresh cookie after `/auth/logout` | 401 | **200** | FAIL — QA-06 (open) |
| SES-04/05 | Logout-all | Other device refreshes | 401 | 401 "session has ended" | PASS |
| SES-06 | Logout-all | Old access token | 401 | 200 until expiry (≤60 min) | FAIL — known P1, open |
| e2e | Account flows | `auth_flows.py` | all pass | 42/42 | PASS |

### 5.2 Purchase requests and approvals

| ID | Input / setup | Expected | Before | After | Status |
|---|---|---|---|---|---|
| REQ-01 | amount −1000 | 422 | 500 | 422 | FIXED (QA-04) |
| REQ-02 | amount 0 | accepted (auto tier) | 200 | 200 | PASS |
| REQ-03 | amount `NaN` | 422 | 500 **and row stored**; request list then 500 for all users | 422; DB CHECK also rejects | FIXED (QA-01) |
| REQ-04/05 | `Infinity`, 1e300 | 422 | 500 | 422 | FIXED (QA-04) |
| REQ-06 | department "   " | 422 | 200 (blank stored) | 422 | FIXED (QA-12) |
| REQ-07/08/19 | bad type, missing amount, items not list | 422 | 422 | 422 | PASS |
| REQ-09 | 10k-char comment, Hindi + emoji department | stored intact | 200 | 200 | PASS |
| REQ-10 | currency "NOTACURRENCY" | 422 | 200 | 200 | FAIL — QA-13 (open, low) |
| REQ-11/18 | approver creates; requester approves | 403 | 403 | 403 | PASS |
| REQ-12/13 | GET non-UUID / unknown id | 400 / 404 | 400 / 404 | 400 / 404 | PASS |
| REQ-14/16 | `limit=-1`, `limit=10^7` | 422 | 500 | 422 | FIXED (QA-05) |
| REQ-17 | approve non-UUID id | 400 | 500 | 400 | FIXED (QA-10) |
| SOD-01 | admin approves own request | 403 | 403 SEPARATION_OF_DUTIES | — | PASS |
| RACE-01 | 10 concurrent approvals (2 approvers) | one decision, one contract | 1 history row, 1 audit row, 1 contract (2 callers got 200 — idempotent reply) | — | PASS |
| IDEM-01 | same `Idempotency-Key` twice | same request id | same id | — | PASS |

### 5.3 Inventory

| ID | Input | Expected | Before (available / reserved) | After | Status |
|---|---|---|---|---|---|
| INV-01 | hardware, `quantity: -3` | 422, stock unchanged | 200; 5/0 → **8/−3** | 422; 5/0 | FIXED (QA-02) |
| INV-02 | `quantity: "two"` | 422 | 500 | 422 | FIXED (QA-02) |
| INV-03 | valid reservation, request insert fails | reservation released | 500; **1 unit stayed reserved** | 422 at the API; failed inserts now release (unit test) | FIXED (QA-03) |
| INV-04 | `quantity: 0` | 422 | 200 | 422 | FIXED (QA-02) |
| LIC-03 | reorder settings negative | 422 | 422 | — | PASS |

### 5.4 Contracts and e-signature

| ID | Input | Expected | Before | After | Status |
|---|---|---|---|---|---|
| CON-01 | requester lists contracts | own only | all 278 (44 not theirs) | 239 = exactly own | FIXED (QA-07) |
| CON-02/03 | requester reads / downloads someone else's contract, signed copy, certificate | 404 | 200 + PDF | 404 on all four; finance still 200 | FIXED (QA-07) |
| CON-04 | non-UUID id | 400 | 400 | 400 | PASS |
| CON-05 | `within_days=-5` | empty list | empty | — | PASS |
| HOOK-01/02 | e-sign webhook bad signature / empty | 401 / 422 | 401 / 422 | — | PASS |
| HOOK-03 | Documenso non-JSON body | 400 | 500 | 400 | FIXED (QA-14) |
| HOOK-04/05 | Documenso no secret, DocuSign no signature | 401 | 401 | — | PASS |

### 5.5 Documents and vendors

| ID | Input | Expected | Actual | Status |
|---|---|---|---|---|
| DOC-01 | empty file | 400 | 400 | PASS |
| DOC-02 | `.exe` | 415 | 415 | PASS |
| DOC-03 | filename `../../etc/passwd.pdf` | name reduced, key namespaced | stored as `passwd.pdf` under `documents/<id>/` | PASS |
| DOC-04 | text file named `.pdf` | 415 | 415 | PASS |
| DOC-05 | EICAR test string | rejected | 422 "malware detected (Eicar-Test-Signature)" | PASS |
| DOC-06 | no file field | 422 | 422 | PASS |
| DOC-U | Hindi / quote in filename, then download | 200, safe header | `filename="__QA-PROBE.pdf"`, `qa_22probe.pdf` | PASS |
| DOC-09 | `limit=-1` | 422 | 500 → 422 | FIXED (QA-05) |
| DOC-SHORT | valid one-line digital PDF | processed, sent to review | failed "no text, may be blank" → classified + needs review | FIXED (QA-11) |
| VEN-02/03/05 | onboard empty, bad GSTIN, as requester | 422 / reported / 403 | as expected | PASS |
| e2e | `document_pipeline.py --quick` | all pass | 52/52 | PASS |

### 5.6 Notifications

| ID | Input | Expected | Before | After | Status |
|---|---|---|---|---|---|
| NOT-01 | requester opens Notifications page / bell | own notifications | 403 on every page (bell), error page | 200, only rows addressed to them | FIXED (QA-08) |
| NOT-02 | requester `?recipient=procurement-ops@…` | still own only | (403) | own only | FIXED (QA-08) |

### 5.7 Failure and recovery (local stack, dependency stopped then started)

| ID | Setup | Expected | Actual | Status |
|---|---|---|---|---|
| FAIL-01 | ClamAV stopped, upload | refuse, retryable | 503 "scanning unavailable, try again" | PASS |
| FAIL-02/03 | Redis stopped, create request | clear error, no partial data | generic 500; no rows written | PASS (message: QA-16) |
| FAIL-04/05 | Redis stopped, list / login | still work | 200 / 200 | PASS |
| FAIL-06 | Redis started again | creates work | 200 | PASS |
| DB-DOWN | Postgres unavailable | — | — | NOT RUN (shared stack; the other services' health and DLQ behaviour are covered by existing unit tests) |

### 5.8 Frontend (Playwright crawl)

Every route (20 + 5 detail pages) as admin at 390 / 768 / 1440 px and as
requester at 390 / 1440 px, then finance at 1440 px after the fixes.

| ID | Check | Result | Status |
|---|---|---|---|
| UI-01 | Uncaught page errors | none | PASS |
| UI-02 | Horizontal overflow at phone width | none on any page | PASS |
| UI-03 | Failed API calls (requester) | 403 on `/notifications/log` (every page) and `/vendors/<id>/payment-changes` → fixed | FIXED (QA-08, QA-09) |
| UI-04 | Form controls without an accessible name | 11 (document review form, search/filter boxes) → aria-labels added | FIXED (QA-18) |
| UI-05 | 401 on `/auth/me` at each full page load | session bootstrap before silent refresh; harmless console noise | PASS (noted) |
| UI-06 | Keyboard-only navigation, colour contrast, screen-reader pass | — | NOT RUN |

### 5.9 Static checks and dependencies

| Check | Result |
|---|---|
| `tsc` + `vite build` | pass |
| `ruff --select F` (undefined names etc.) | 0 undefined names; 130 unused / duplicate imports (cosmetic, not changed) |
| `npm audit --omit=dev` | 2 moderate: `react-router` 6.x open redirect via backslash in `<Link>`; fix only in 7.x (breaking) — not upgraded |
| Python advisories | already tracked in TODO.md (Starlette 0.37.2, Pillow 10.4.0, pdfminer.six, MLflow 2.14.3) |

## 6. Limitations

- No load or soak test was run; the only concurrency test is ten parallel
  approvals of one request. No performance claims are made.
- Postgres, Kafka and Temporal outages were not injected (shared dev stack).
- `tests/test_chatbot_e2e.py` (4 async tests) is skipped by pytest — there
  is no `pytest-asyncio` in that image — so it never runs. Chatbot is out of
  scope; flagged to its owner.
- `tests/e2e/demo_scenarios.py` was not rerun in this audit because it
  rewrites `docs/demo-script.html`, which has uncommitted changes.
- No real e-sign provider, SMTP server or GSTIN API was called.
- Accessibility was checked automatically (labels, alt text, overflow), not
  with a screen reader or keyboard-only walk-through.
