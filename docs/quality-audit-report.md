# Quality audit report — October 17, 2026

A pre-submission audit of the procurement platform: baseline checks, live
black-box testing through the gateway, controlled dependency failures, a
browser crawl, then fixes with regression tests. How to rerun everything and
the full scenario matrix are in [testing-strategy.md](testing-strategy.md).

> **Update, October 19:** QA-06 and QA-21 fixed; access tokens shortened
> to 15 minutes; Python and frontend dependencies upgraded; production
> start-up checked and backups added (`docs/deployment.md`). Status of every
> item: `docs/TODO.md`. The rest of this report is as written on Oct 17.

**Assessment: READY WITH KNOWN ISSUES** for the local demonstration and
submission. Not ready for a shared or public deployment until the open P0
(credential rotation, SEC-1 in TODO.md) and the session items below are done.
See §6.

## 1. Before and after

| Check | Before | After |
|---|---|---|
| Service suites (`test-service.sh all`) | 747 passed (176 / 146 / 314 / 46 / 65) | **823 passed** (198 / 178 / 328 / 54 / 65), 0 failed |
| Root tests (`test-root.sh`) | 137 passed, 4 skipped; 14 passed | same (the 4 skipped never run — QA-22) |
| Frontend `tsc` + `vite build` | pass | pass |
| `make e2e` | not run before | 17 / 17 |
| `invoice_lifecycle.py` | not run before | 71 / 71 |
| `document_pipeline.py --quick` | not run before | 52 / 52 (run twice, after each fix batch) |
| `auth_flows.py` | not run before | 42 / 42 |
| Live probes (healthy stack) that returned a 500 | 11 | 0 (the two Redis-outage 500s remain — QA-16) |
| Live probes that corrupted or exposed data | 4 (NaN row, inventory −3, leaked reservation, 44 foreign contracts) | 0 |
| Failed API calls during UI crawl (excluding the 401 session bootstrap) | 2 kinds, on every requester page | 0 |

Order of suites in the service row: contract-risk / approval-inventory /
document-vendor / notification / auth. The +76 service tests are the new
regression tests (§4).

## 2. Issue register

Severity: **critical** — breaks a core feature for all users or corrupts
data; **high** — data corruption or exposure that one user can trigger;
**medium** — wrong behaviour with a workaround or a narrower impact;
**low** — misleading errors, hygiene, small UX/accessibility gaps.

| ID | Severity | Title | Affected | Status |
|---|---|---|---|---|
| QA-01 | Critical | A NaN amount is stored and then breaks the request list for everyone | approval-inventory: `schemas.py`, `approval_service.py`, DB | **Fixed** |
| QA-02 | High | Zero, negative or non-integer item quantity corrupts inventory | approval-inventory: `schemas.py` | **Fixed** |
| QA-03 | High | Stock stays reserved when a request fails to save | approval-inventory: `approval_service.py` | **Fixed** |
| QA-07 | High | Any signed-in user can read every contract and its PDFs (known P1) | contract-risk: `api/contracts.py`, `contract_service.py` | **Fixed** |
| QA-04 | Medium | Invalid amounts (negative, ∞, 1e300) give 500 instead of 422 | approval-inventory: `schemas.py` | **Fixed** |
| QA-05 | Medium | `limit=-1` → 500; `limit=10^7` reads the whole table | 10 list endpoints in 4 services | **Fixed** |
| QA-06 | Medium | `/auth/logout` doesn't revoke the refresh token | auth-service | Fixed Oct 19 |
| QA-08 | Medium | Requesters' Notifications page and bell fail with 403 | notification-agent: `api/notifications.py` | **Fixed** |
| QA-19 | Medium | A request is committed before its `approval.requested` event | approval-inventory: `approval_service.py` | Open |
| QA-09 | Low | Vendor page tells requesters/approvers "no payment changes" (actually a 403) | frontend: `VendorDetailPage.tsx` | **Fixed** |
| QA-10 | Low | Approve/reject with a malformed id → 500 | approval-inventory: `api/requests.py` | **Fixed** |
| QA-11 | Low | A short digital PDF is rejected as "blank or too faint" | document-vendor: `services/ocr.py` | **Fixed** |
| QA-12 | Low | Blank department accepted | approval-inventory: `schemas.py` | **Fixed** |
| QA-13 | Low | Currency not validated | approval-inventory: `schemas.py` | Open |
| QA-14 | Low | Documenso webhook non-JSON body → 500 | contract-risk: `api/webhooks.py` | **Fixed** |
| QA-15 | Low | Trailing-slash redirect drops the gateway port | services behind nginx | Open |
| QA-16 | Low | Redis down → generic 500 on request creation | approval-inventory | Open |
| QA-17 | Low | Error messages carry internals / echo input | shared auth; approval-inventory 422 handler | Open |
| QA-18 | Low | 11 form controls have no accessible name | frontend (7 files) | **Fixed** |
| QA-20 | Low | `inventory` has no CHECK constraints | DB | Open (recommendation) |
| QA-21 | Low | `react-router` 6.x moderate advisory | frontend dependency | Fixed Oct 19 (7.18) |
| QA-22 | Low | Chatbot root tests are silently skipped | `tests/test_chatbot_e2e.py` | Open (owner: Anooj) |

Already tracked in TODO.md and confirmed, not re-filed: access tokens stay
valid ≤60 min after logout-all or demotion (P1), dependency CVEs on the
upload path (P1), credential rotation (P0, SEC-1).

## 3. Findings in detail

### QA-01 — Critical — a NaN amount is stored and breaks the request list

- **Reproduce:** as `requester@`, `POST /api/requests/` with body
  `{"request_type":"license","department":"IT","amount":NaN}` (Python's
  JSON parser accepts the bare `NaN` token). Then, as anyone,
  `GET /api/requests/`.
- **Expected:** 422; nothing stored.
- **Actual:** the create returned 500, but the row **was stored**
  (`pending_approval`, tier `manager+finance`). From then on
  `GET /api/requests/` returned 500 for every user ("Out of range float
  values are not JSON compliant"): the requests page, dashboards and
  approval inbox all broke. One request from any requester did this.
- **Root cause:** `amount: float` had no bounds; Postgres `numeric` accepts
  NaN and `NaN >= 0` is true there, so `ck_purchase_requests_amount`
  didn't stop it. The 500 was raised by a *second* transaction (the outbox
  write, `json.dumps` → `NaN`, which JSONB rejects) after the row was
  already committed — see QA-19.
- **Fix:** `amount: float = Field(ge=0, lt=10_000_000_000, allow_inf_nan=False)`
  (the model column is `Numeric(12, 2)`), plus a DB constraint
  `ck_purchase_requests_amount_finite CHECK (amount <> 'NaN' AND amount < 'Infinity')`
  so no other writer can store one.
- **Migration:** appended to `services/approval-inventory-agent/migrations/0001_schema_extensions.sql`,
  idempotent (`IF NOT EXISTS` on `pg_constraint`), applied at service start.
  Existing data checked first: 0 non-finite rows of 242. Rollback:
  `ALTER TABLE purchase_requests DROP CONSTRAINT ck_purchase_requests_amount_finite;`.
- **Evidence:** live probe REQ-03 before/after; direct `INSERT … 'NaN'` now
  fails with the constraint; tests `TestAmountValidation` (13 cases).
- **Data:** the one NaN row was the audit's own probe; it was set to amount 0,
  status `cancelled` immediately to restore the list.

### QA-02 — High — bad item quantities corrupt inventory

- **Reproduce:** hardware request with `items: [{"sku": "<sku>", "quantity": -3}]`.
- **Actual:** 200; a SKU at available 5 / reserved 0 became **8 / −3**.
  `"two"` → 500; `0` → accepted.
- **Root cause:** `items` is a free-form `list[dict]`; `item_avail >= qty`
  is true for a negative `qty`, and `reserve_stock` then subtracts it.
- **Fix:** a validator on items that carry a `sku` (the only ones that
  reserve stock): quantity must be an `int` ≥ 1 (booleans and floats
  rejected; default 1). Line items without a SKU — e.g. drop-folder quotes
  with fractional hours — are not restricted.
- **Tests:** `TestDepartmentAndItems` (9 cases).

### QA-03 — High — reservation leaks when a request fails to save

- **Reproduce (before):** hardware request with a valid SKU and an amount the
  DB rejects (−5). Response 500; the SKU's reserved count went up by 1 and
  stayed there for a request that doesn't exist.
- **Root cause:** `reserve_stock` commits on its own, before the request row
  is inserted; nothing undid it on failure.
- **Fix:** `create_request` records each successful reservation and, if the
  insert / commit fails, rolls back and calls `release_reservation` for
  each before re-raising.
- **Test:** `test_failed_insert_releases_the_stock_it_reserved`. (The live
  trigger, an invalid amount, is now stopped at the API.)

### QA-07 — High — contracts readable by any signed-in user

- Already listed in TODO.md ("Security audit follow-ups").
- **Reproduce:** as `requester@`, `GET /api/contracts/`, then
  `GET /api/contracts/<id of another person's contract>/document`.
- **Actual:** the list had all 278 contracts (44 on other people's
  requests); the PDF downloaded.
- **Fix:** staff (`approver`, `finance`, `admin`, `service`) unchanged. A
  requester's list and renewals are joined to `purchase_requests` and
  filtered to their own email; detail, `/document`, `/signed-document`
  and `/signature-certificate` return 404 for anyone else's contract (same
  pattern as requests and documents). The requester's request page still
  shows its contract.
- **Live after:** requester list = 239 = exactly the contracts on their
  requests; all four endpoints 404 for a foreign contract; finance 200.
- **Tests:** `services/contract-risk-agent/tests/test_contract_access.py`.

### QA-04 — Medium — invalid amounts return 500

Negative → DB CHECK violation; ∞ and 1e300 → driver errors; all surfaced as
"Failed to create purchase request" 500. Fixed by the QA-01 field bounds;
now 422 with the reason.

### QA-05 — Medium — unbounded `limit`

`?limit=-1` reached SQL ("LIMIT must not be negative" → 500); `?limit=10000000`
read the whole table (here it hit the NaN row). All ten list endpoints now
take `Query(default, ge=1, le=1000)` — the largest any client sends is 200.
Endpoints: requests, invoice matches, order-summary history (approval-
inventory); contracts, vendor risk list (contract-risk); documents, review
queue, vendors, model-routing log (document-vendor); notification log.
Tests in three services.

### QA-06 — Medium — logout doesn't revoke the refresh token (fixed Oct 19: `jti` recorded in `auth_revoked_refresh_tokens`, migration 0014; replay → 401)

- **Reproduce:** log in (cookie + CSRF token), save the cookies, call
  `/auth/logout`, then call `/auth/refresh` with the saved cookies.
- **Actual:** 200 and a new access token. `/auth/logout` only clears the
  browser's cookies; the refresh token (HttpOnly, 7 days) stays valid.
  `/auth/logout-all` does revoke (bumps `token_version`) — verified.
- **Risk:** only a refresh token that was already stolen; the browser no
  longer holds it after logout.
- **Why not fixed here:** needs a server-side record of revoked refresh
  tokens (`jti`) — a new table and a design choice. Next step: add a
  `revoked_refresh_tokens (jti, expires_at)` table in an auth-service Alembic
  migration, write the `jti` on logout, check it in `/auth/refresh`, purge
  expired rows. Test: replay after logout → 401.

### QA-08 — Medium — requester notifications fail

The requester nav has "Notifications" and the top-bar bell polls the log on
every page, but `/notifications/log` was staff-only (403): the page showed an
error and the bell failed silently. The log holds 708 notifications
addressed to `requester@demo.example.com`. Fix: non-staff callers get only
rows whose recipient is their own email (from the JWT; a `?recipient=`
parameter can't widen it). Staff unchanged. Tests:
`test_notification_log_access.py`. Live: requester gets 200 with only own rows.

### QA-19 — Medium — request committed before its event (open)

`create_request` commits the row, then writes `approval.requested` to the
outbox and starts the workflow in later steps. If those fail, the request
is left `pending_approval` with no event and no approval workflow (that is
how QA-01's row was orphaned). The code comment says the event is written
"in the same transaction", which is true only for the backordered path.
Next step: stage `approval.requested` before the first commit for the main
path too (the backorder split happens later and publishes its own event);
test that a failing outbox write leaves no row. Not changed here because the
split/auto-approve ordering needs care and a broader test.

### Low-severity items

| ID | Detail | Fix or next step |
|---|---|---|
| QA-09 | Vendor detail called `/vendors/<id>/payment-changes` (finance/admin only) for every role and showed "No payment detail changes on record" on the 403. | Card and request now only for finance/admin. Verified in the UI crawl. |
| QA-10 | `POST /requests/not-a-uuid/approve` → 500 (a broad `except` hid the shared 400 handler). | Explicit UUID check → same 400 `bad_request` as other endpoints. Tests. |
| QA-11 | A digital PDF with < 40 characters of text and no images returned empty text → "We couldn't find any text… may be blank". | Short native text is kept at low quality, so the document goes to review. Blank pages still fail as before. Test + live (classified, needs review). |
| QA-12 | `department: "   "` stored. | Trimmed, must be non-empty. The wizard already requires it. |
| QA-13 | `currency: "NOTACURRENCY"` accepted. | Not changed: drop-folder requests pass the extracted currency through, and strict ISO validation could dead-letter them. Next step: normalise in the consumer first, then validate `^[A-Z]{3}$`. |
| QA-14 | Documenso webhook with a non-JSON body → 500. | 400 "request body is not valid JSON". Test. |
| QA-15 | `GET /api/auth/users/` → 307 to `http://localhost/api/auth/users` (port lost). The UI doesn't hit it; API clients do. | Next step: call paths without the trailing slash, or pass the original host (`proxy_set_header Host $http_host`) in nginx and retest. |
| QA-16 | Redis down → request creation returns a generic 500 (idempotency cache + stock lock need Redis). No partial data. | Next step: map Redis connection errors to 503 "try again". |
| QA-17 | An undecodable token's 401 includes the decoder's message; approval-inventory's own 422 handler echoes the submitted input (the shared handler deliberately doesn't). | Next step: generic "invalid token"; use the shared validation handler (check the frontend doesn't rely on the `VALIDATION_ERROR` code casing first). |
| QA-18 | Document review fields (vendor, type, total, number, date) and six search/filter controls had no accessible name. | `aria-label`s added; no visual change. |
| QA-20 | Nothing at the DB level stops `available_quantity` / `reserved_quantity` going negative. | Recommendation: `CHECK (available_quantity >= 0 AND reserved_quantity >= 0)` after confirming current data complies and no release path dips below zero. |
| QA-21 | `npm audit`: `react-router` ≤ 7.17 open redirect via backslash in `<Link>` / `useNavigate`; fix only in 7.x. | Not upgraded (major version). The app builds links from its own routes, not user input. Revisit with the dependency-upgrade P1. |
| QA-22 | `tests/test_chatbot_e2e.py`'s 4 async tests are skipped (no `pytest-asyncio`), so they never ran. | For the chatbot owner. |

## 4. Changes made

| Area | Files |
|---|---|
| Request validation | `services/approval-inventory-agent/app/schemas.py` |
| Reservation release on failed save | `services/approval-inventory-agent/app/services/approval_service.py` |
| Malformed id on approve/reject; bounded limit | `services/approval-inventory-agent/app/api/requests.py`, `invoices.py`, `orders.py` |
| Finite-amount constraint | `services/approval-inventory-agent/migrations/0001_schema_extensions.sql` |
| Contract scoping | `services/contract-risk-agent/app/api/contracts.py`, `app/services/contract_service.py` |
| Documenso non-JSON; bounded limit | `services/contract-risk-agent/app/api/webhooks.py`, `vendors.py` |
| Bounded limit | `services/document-vendor-agent/app/api/documents.py`, `vendors.py`, `admin.py` |
| Short-PDF text | `services/document-vendor-agent/app/services/ocr.py` |
| Notification scoping | `services/notification-agent/app/api/notifications.py` |
| Frontend | `pages/vendors/VendorDetailPage.tsx`; aria-labels in `DocumentDetailPage.tsx`, `VendorsListPage.tsx`, `NewRequestWizardPage.tsx`, `LicensesListPage.tsx`, `UsersPage.tsx`, `BusinessRulesPage.tsx`, `components/controls/ReliabilityPanel.tsx` |

API contract changes (all narrowing invalid input or access, none for valid
callers): invalid request bodies now 422 instead of 500/200; `limit` outside
1–1000 → 422; requesters get 404 for others' contracts and see only their
own in lists; requesters can now read their own notifications (was 403).

New tests (76): `test_qa_audit_regressions.py` (32), `test_contract_access.py`
(22), `test_list_limits.py` (13), `test_notification_log_access.py` (8),
`test_short_digital_pdf_keeps_its_text` (1). Each security/validation test
fails against the pre-fix code; the remaining ones guard valid input and
pass both before and after.

## 5. Test data left in the demo database

Probes used disposable data tagged `QA-PROBE`. Nothing was deleted; the
one record that broke the app (QA-01) was neutralised at once. Remaining:

- 14 purchase requests with `comments LIKE '%QA-PROBE%'`: 12 approved (each
  auto-generated a contract now `pending_signature`), 1 cancelled, 1
  rejected (closed through the app so its approval workflow ended).
- 5 uploaded documents (`passwd.pdf` ×2, `__QA-PROBE.pdf`, `qa_22probe.pdf`,
  `QA-PROBE-short.pdf`).
- Inventory SKU `QA-PROBE-SKU` (5 / 5 / 0).

They can be removed together with their contracts, history, audit and
outbox rows, or left as demo noise. Deleting them is the owner's call.

## 6. Release-readiness assessment

**READY WITH KNOWN ISSUES** for the local demo and submission:

- Every automated check that can run here passes: 823 service tests, 151 root
  tests, frontend build, and all four e2e suites (182 checks).
- The one critical and three high defects found are fixed, verified live and
  covered by tests that fail without the fix.
- No page crashes, failed API calls or horizontal overflow in the UI crawl
  across three screen sizes.

Known issues that remain (none blocks the demo):

- **Medium:** logout leaves the refresh token valid (QA-06); a request can be
  left without its event if the outbox write fails (QA-19); access tokens
  outlive logout-all by up to 60 minutes (existing P1).
- **Low:** QA-13, 15, 16, 17, 20, 21, 22.

**Not ready for a shared or public deployment** until SEC-1 (rotate the
GSTINCheck key, real secrets with `APP_ENV=production`), the dependency
upgrades on the upload path, and QA-06 are done. Not tested: load, Postgres /
Kafka / Temporal outages, screen-reader use. These are limits of this audit,
not evidence that those areas work.
