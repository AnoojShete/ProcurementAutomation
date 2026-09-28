# CLAUDE.md

Context for an agent working in this repo. README.md is the full
reference; TODO.md is the open work; CHANGELOG.md is what changed and why.

## What this is

A student team project (Anjali, Vaidehi, Niraj, Anooj): five FastAPI
services + workers talking over Kafka (Redpanda), one shared Postgres,
Temporal for long-running workflows, MinIO for files, ClamAV for upload
scanning, nginx gateway on :8080 serving the React/Vite frontend. Keep
explanations and designs simple enough for students to present.

| Service | Port | Owner | Migrations |
|---|---|---|---|
| document-vendor-agent (+ worker) | 8001 | Vaidehi | raw SQL `migrations/000N_*.sql`, applied at startup by `app/database.py` (`MIGRATIONS` tuple) |
| approval-inventory-agent (+ worker) | 8002 | Niraj | raw SQL `migrations/0001_schema_extensions.sql` (one growing file), applied at startup |
| contract-risk-agent (+ worker) | 8003 | Anjali | Alembic, `alembic_version_contract_risk_agent`, run by `docker-entrypoint.sh` |
| notification-agent | 8004 | Anooj | raw SQL `migrations/0001_notification_tables.sql` |
| auth-service | 8005 | Anooj | Alembic, `alembic_version_auth_service`, run by `docker-entrypoint.sh` |

Base tables: `shared/db/init.sql`, applied once by `install.sh`. Never edit
it for new work — add a migration in the owning service. Raw-SQL
migrations are split with `shared/db/sql_runner.split_sql` (handles `;`
inside quotes / `$$` blocks); keep them idempotent (`IF NOT EXISTS`,
`DO $$ … IF NOT EXISTS (SELECT 1 FROM pg_constraint …)`). Check existing
data before adding a constraint, and ask the user before anything
destructive.

Team boundaries the user set: **don't build the email automation or the
chatbot — Anooj owns those.** notification-agent still sends to Mailpit on
purpose (its recipients are placeholder role addresses).

## Commands

```bash
./run.sh                                  # whole stack (install.sh → build → services → nginx → health)
./scripts/seed-demo-data.sh               # demo vendor, request, licenses, inventory
./scripts/test-service.sh <svc>|all       # service pytest suite inside its image (mounts source)
# root tests (shared/ code, config checks):
docker run --rm -e APP_ENV=development -v "$PWD:/w" -w /w --entrypoint sh \
  procurementautomation-auth-service -c "pip -q install pyyaml; python -m pytest -q tests --ignore=tests/e2e"
make e2e                                  # bash e2e through the gateway
python tests/e2e/auth_flows.py            # accounts + Mailpit (needs EMAIL_MODE=dev)
python tests/e2e/invoice_lifecycle.py     # one invoice through all five agents
python tests/e2e/document_pipeline.py [--quick]
cd frontend && npm run typecheck          # tsc; `npm run build` = typecheck + vite build
docker compose up -d --build <svc> && docker compose restart nginx   # after changing a service
```

e2e scripts need `pip install -r tests/e2e/requirements.txt` on the host.
There's no configured Python linter; `ruff check --select F` is a useful
ad-hoc pass (undefined names).

## Frontend conventions

- **One home page per item** (request, contract, license, vendor,
  document); its actions live there, and lists / dashboards / the inbox
  link to it. Don't add a second place with its own copy of an action.
- **Each agent's actions are one component** under
  `frontend/src/components/<agent>/` (`approvals/ApprovalActions`,
  `contracts/ContractActions`, `vendors/PaymentChangeVerify`) that calls
  only that agent's API module; reuse it wherever the item appears.
- Show a page's loading skeleton only on the first load
  (`if (loading && !data)`), or a reload after an action unmounts the
  panel and loses its confirmation.
- The top bar's back arrow covers every page; don't add per-page "Back to…"
  buttons.
- Deep links: `/app/requests/:id?step=approval|contract|signature|…`,
  `/app/contracts/:id?action=sign|send`.

## Gotchas

- **`docker compose up -d --build <svc>` can remove other services**: it
  re-runs the one-shot `redpanda-init`, and containers depending on it may
  be removed rather than restarted. Run `docker compose up -d` (and restart
  nginx) afterwards and check `docker compose ps`.
- **Restart nginx after recreating any service** — it resolves upstream IPs
  once at boot, so a recreated container gets 502s until nginx restarts.
- **Gateway rate limits** (per IP): login/register/verify/reset/change
  30/min burst 20, forgot-password/resend 6/min. Running e2e suites back to
  back trips them — wait a minute between suites. `auth_flows.py` waits out
  `rate_limited` 429s itself.
- **`APP_ENV` defaults to production**: published default secrets are
  refused, no demo accounts, no showcase endpoints, `EMAIL_MODE=dev`
  refused. The compose stack sets `APP_ENV=development`.
- **Identity always comes from the JWT**, never from a request body field
  (`requested_by`, `decided_by`, `uploaded_by`, `verified_by`…). Tests
  exist for this; don't reintroduce body identity.
- **Errors**: raise `HTTPException`; the shared handler
  (`shared/http/error_handlers.py`) renders `{"error": {"code", "message"}}`.
  `detail={"code": ..., "message": ...}` sets a specific code. Unhandled
  exceptions are logged there with a traceback and returned as a generic
  500. The JSON log formatter drops `extra=` fields — put details in the
  message.
- **Kafka**: a new topic needs `shared/kafka-topics.yaml`,
  `infra/redpanda/acls.conf` and `shared/schemas/events.md`;
  `tests/test_kafka_acls.py` fails otherwise. Publish through the outbox
  (`staged(producer, session)` from `shared/eventing`) so the event commits
  with the change; wrap consumers with `shared/eventing.deliver` (retry +
  `event_dlq`).
- **Purchase-request status** changes are validated by `shared/lifecycle.py`
  on the model; the DB also has a CHECK constraint listing every status.
- **Temporal (temporalio 1.6)**: no `workflow.sleep` (use `asyncio.sleep`
  in workflows); optional signal/activity fields must be `Optional[...]`,
  not `str = None` (payload conversion fails silently).
- **Alembic**: every service shares one DB, so each Alembic service has its
  own `version_table`.
- **Cross-service DB coupling**: services share tables. A foreign key from
  one service's table to rows another service creates inside an
  uncommitted transaction will fail (see the open P0 on
  `fk_invoice_matches_vendor` in TODO.md).
- **Emails**: `shared/mailer.py`, `EMAIL_MODE=dev|smtp`. Compose passes
  unset vars as `""`, which the mailer treats as "use the default". Links
  carry tokens after `#` so they never reach server logs.
- **Tests that need Postgres**: `services/auth-service/tests/test_account_flows.py`
  uses a throwaway `auth_test` database; `test-service.sh` wires it up when
  the stack is running, otherwise those tests skip.
- zsh is the user's shell: unquoted `$VAR` doesn't word-split, and globs
  with no match are errors.
- LayoutLMv3 is loaded from the local cache only; run
  `./scripts/download-models.sh` once or the cross-check is skipped.

## Working style the user expects

- Verify fixes live, and prove a test catches a regression (revert the
  fix, see it fail).
- Don't weaken checks to make something pass; don't rotate or delete real
  credentials (say which need rotating); stop and ask on architectural
  decisions and destructive migrations; don't deploy anywhere.
- Report outcomes plainly, including what failed.
