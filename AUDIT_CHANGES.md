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
