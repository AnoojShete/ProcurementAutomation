# Audit pass — what changed in this commit

A full audit (backend x5 services, frontend, infra/docker/k8s) was run against
the documented "ideal" system in `README.md`. The stack was actually built and
started from a clean `./run.sh`, `make e2e` and every service's pytest suite
were run, and every fix below was re-verified live against the running stack
(not just read/reasoned about) before being committed. See `TODO.md` (not
included in this commit) for what's tracked as remaining work.

## Security fixes

- **E-sign webhook secret was silently ignored.** `contract-risk-agent`'s
  `Settings` only reads env vars prefixed `APP_`, but `docker-compose.override.yml`
  set the unprefixed `ESIGN_WEBHOOK_SECRET` — so `settings.esign_webhook_secret`
  was *always* the hardcoded dev default, in every environment, regardless of
  configuration. Renamed to `APP_ESIGN_WEBHOOK_SECRET` in both the service and
  worker blocks. Verified live: a webhook signed with a bad secret now
  correctly gets `401`.
- **Payment-change dual control was bypassable.** `POST /vendors/{id}/verify-payment-change`
  trusted a client-supplied `verified_by` field instead of the caller's
  authenticated identity, so any authenticated user could "verify" a
  fraudulent bank-detail change themselves. Now derives `verified_by` from the
  JWT (`get_current_user`) and restricts the endpoint to `finance`/`admin`
  roles. Verified live: a `requester` token is now rejected with `403`.
- **Approval inbox / notification log had no role check (IDOR).** `GET /inbox/{approver_id}`
  and `GET /notifications/log` only required *any* authenticated user, so a
  `requester` could read another role's approval queue or the full
  cross-tenant notification audit trail. Both now require
  `approver`/`finance`/`admin`. Verified live: `requester` gets `403` on both;
  `approver`/`finance` still get `200`.
- **Webhook replay handling could 500 under concurrency.** The e-sign webhook's
  replay check was check-then-insert, not atomic — two concurrent deliveries
  of the same `provider_event_id` could both pass the check, and the second
  commit's `IntegrityError` wasn't caught, surfacing as a raw 500 instead of
  `{"status": "already_processed"}`. Now catches `IntegrityError` on commit
  and treats it as a replay. Verified live by firing 10 concurrent identical
  deliveries: exactly one `200 signed`, nine `200 already_processed`, zero
  500s.
- **`JWT_SECRET` silently falls back to a well-known default** with no
  visibility into it happening. Added a startup warning log when the fallback
  is in effect, so an unset secret in a real deployment is no longer silent.

## Correctness fixes

- **`POST /documents/{id}/review` crashed on any vendor-name correction.**
  `document_service.submit_review()` called `find_or_create_vendor(...)`,
  which was never imported — every call raised `NameError`, caught only by
  the generic 500 handler, and no test exercised this path. Added the missing
  import. Verified live: a vendor-name correction now returns `200` with the
  vendor linked, where it previously 500'd.
- **A bare `except Exception` in `POST /requests/` masked real failures as
  400s** and leaked internal error strings to the client instead of using the
  shared error-envelope handler. Removed it — unhandled errors now correctly
  fall through to `shared/http/error_handlers.py`'s generic 500 handler.
  Re-ran the service's test suite to confirm nothing depended on the old
  behavior.

## Infra fixes

- **MinIO console was unreachable.** `docker-compose.yml` started MinIO
  without `--console-address`, so it auto-selected a random console port
  while only `9000` (the S3 API port) was published — the documented
  `http://localhost:9000` console URL never actually served the console.
  Pinned `--console-address ":9001"`, published `9001`, and corrected the URL
  in `README.md`.
- **Postgres/MinIO credentials were hardcoded** in `docker-compose.yml`
  instead of sourced from `.env` like every other service's credentials.
  Switched both to `${VAR:-default}` form, consistent with the rest of the
  compose files.
- **No security headers on the gateway.** Added `X-Content-Type-Options`,
  `X-Frame-Options`, and `Referrer-Policy` to `infra/nginx/nginx.conf`.

## Verification performed

- `./run.sh` — clean build, all containers healthy.
- `make e2e` — 12/12 passing, both before and after rebuilding the five
  affected services with these fixes.
- `./scripts/test-service.sh all` — 132 passed, 2 skipped, across all 5
  services, both before and after these fixes.
- `frontend`: `npm run typecheck` (`tsc --noEmit`) — clean.
- Manual live verification via `curl`/Python against the running stack for
  every security/correctness fix above (signature rejection, role-gate
  rejections and legitimate-role acceptance, concurrent webhook replay,
  document-review crash fix), not just re-running the existing test suites.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

# Audit pass 2 — merge of `anooj2` into `anjali` (Sep 25)

`origin/anooj2` (23 commits since the pass above: 19 Niraj, 4 Anooj) was
merged into `anjali` and the same process repeated: full `./run.sh` from the
merged tree, every pytest suite, both e2e suites, and live checks through the
gateway for each fix. The full list, and a summary of what teammates changed, is
in README.md → [Recent changes (Sep 5 → Sep 25)](README.md#recent-changes-sep-5--sep-25).

## Security fixes

- Removed a duplicate `@router.post("/{id}/approve")` that had no role check.
- `requested_by` (create request) and `decided_by` (approve / reject /
  decline-reclaim) now come from the JWT; body values are ignored.
  Verified live: a requester posting `requested_by: "ceo@company.com"` is
  stored as `requester@demo.example.com`.
- `POST /vendors/{id}/confirm-no-gstin`: finance/admin only, attester from
  JWT (was: any user, body-supplied name). Verified live: requester → 403,
  spoofed `confirmed_by` ignored.
- `POST /licenses/{id}/mark-reviewed`: approver/finance/admin only, real
  reviewer recorded (was: any user; always logged `admin@example.com`).
  Verified live: requester → 403.
- `/inbox` role guard kept through the merge (the incoming branch had it as
  any-authenticated-user). Verified live: requester → 403.
- Hard-coded GSTINCheck API key removed from `docker-compose.override.yml`
  and `document-vendor-agent/app/config.py`. **The key is in git history —
  rotate it.**
- Internal business-rules secret compared with `hmac.compare_digest`.
- 500 responses in approval `requests.py` no longer echo exception text.

## Correctness fixes

- Document pipeline: every upload failed (`overall_confidence` dropped from
  the envelope in the Sep 25 commit). Restored and covered by a regression test.
- License anomaly model never ran in Docker (SSO log and model artifact
  paths pointed outside the image). Dataset now copied into the image and
  the model trained at build time.
- License with no history scored 0.0 "normal" instead of
  `insufficient_history` when the model wasn't loaded.
- Approval workflow dropped signals that arrived before it reached its
  wait; approvals sent right after request creation were silently lost.
- `system_settings` row never inserted, so the Live Verification toggle was
  a no-op; tables now also created by the service migration so existing
  DBs get them.

## Infra fixes

- document-vendor-agent didn't build on Apple Silicon (`torch==2.3.1+cpu`
  is x86-only); now platform-conditional.
- Temporal UI unreachable (image moved to port 8080 / `TEMPORAL_ADDRESS`).
- nginx routes `confirm-no-gstin` and `spend-summary` to document-vendor-agent.
- `seed-demo-data.sh` seeds licenses + inventory.
- MinIO console URL corrected to :9001 in README and `run.sh`.

## Verification performed

- `./run.sh` from the merged tree: all services healthy.
- Unit tests: 272 passed, 2 skipped (222 service + 50 root-level).
- `make e2e`: 16/16. `tests/e2e/test_flow.py`: passed.
- Frontend `npm run build` (includes `tsc --noEmit`): clean.
- Live gateway checks for each fix above, plus document upload → classified
  for invoice, quote and PO, and license scoring (2 anomalous / 2 watch /
  1 normal on seeded data).

---

# ClamAV: added back (Sep 25)

**Status: ADDED.** ClamAV malware scanning is part of the stack again.

Niraj removed ClamAV on Sep 24 because it took 2–3 minutes to start. The
requirement for bringing it back was that it's ready in under 20 seconds.
It measured **~5 seconds**, so it's back in.

- **Root cause of the slowness:** `clamav/clamav:stable_base` has no ARM64
  build, so compose forced `platform: linux/amd64` and it ran under x86
  emulation on Apple Silicon (50.4s to load signatures even with the DB on
  disk, longer on a fresh volume where `freshclam` also ran emulated). The
  health check then only polled every 15–30s.
- **Fix:** `clamav/clamav-debian:1.5` (official, native amd64 + arm64,
  signature DB built in) with a `start_interval: 1s` health check.
- **Measured:** fresh volume → healthy 4.7s; existing volume 4.6s; inside a
  full `./run.sh` 5.0s (container log timestamps); restart 4.6s; scan
  latency ~7 ms.
- **Restored code:** `clamav_client.py`, scan-before-store in
  `upload_service.py`, 422/503 handling in `documents.py`, `clamd`
  dependency, `tests/test_clamav.py`. The scan now runs via
  `asyncio.to_thread` so it can't block the event loop.
- **Wiring:** `docker-compose.yml` service + `clamav-data` volume;
  document-vendor-agent depends on `clamav: service_healthy`; `install.sh`
  and `run.sh` start and health-check it.
- **Upload size:** nginx had no `client_max_body_size`, so its 1 MB default
  rejected any real scanned PDF. nginx, the API (JSON 413) and clamd are
  now all 25 MB. Verified: 24 MB accepted and scanned in ~1s, 30 MB → 413.
- **Verified live:** EICAR → 422; clean PDF → 201; ClamAV stopped → 503
  (fails closed); `make e2e` 18/18 (now includes both checks); 275 unit
  tests pass.

Also in this commit: `run.sh` builds the frontend in a Linux container with
`frontend/` mounted, which overwrote the host's `node_modules` with Linux
binaries, so a later `npm run build` on macOS failed (missing
`@rollup/rollup-darwin-arm64`). The container now uses an anonymous
`/app/node_modules` volume. Verified: host build → container build → host
build all succeed.
