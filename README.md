# IT Procurement Intelligence Platform

Agentic AI-based IT procurement platform: document/vendor intake, approvals
and inventory, contracts and vendor risk, and notifications — one team, one
repo, one platform, wired together over Kafka.

## Quickstart

```
git clone <repo-url>
cd ProcurementAutomation
./install.sh
docker compose up -d
```

Each teammate owns one folder under `services/`. Add your service to
`docker-compose.override.yml` (append your block, don't edit anyone else's)
and it comes up alongside the rest with `docker compose up -d`.

| Service | Owner | Folder | Port |
|---|---|---|---|
| document-vendor-agent | Vaidehi | `services/document-vendor-agent/` | 8001 |
| approval-inventory-agent | Niraj | `services/approval-inventory-agent/` | 8002 |
| contract-risk-agent | Anjali | `services/contract-risk-agent/` | 8003 |
| notification-agent | Anooj | `services/notification-agent/` | 8004 |

Local UIs once the stack is up:
- Frontend: http://localhost:3001 (once built)
- API gateway: http://localhost:8080/api/...
- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090
- Temporal UI: http://localhost:8088
- MLflow: http://localhost:5050
- MinIO console: http://localhost:9000
- Mailpit: http://localhost:8025

## Shared contracts

Everything below is frozen once agreed — don't silently change a shape a
teammate is already coding against.

- **Event schema**: [`shared/schemas/events.md`](shared/schemas/events.md) —
  the Kafka envelope and, per-topic, the exact payload fields. Read this
  before writing any producer or consumer.
- **Kafka topics**: [`shared/kafka-topics.yaml`](shared/kafka-topics.yaml).
- **DB schema**: [`shared/db/init.sql`](shared/db/init.sql) — the shared
  base tables. Never edit this file directly; if your service needs new
  columns or tables, add your own Alembic migration inside your service
  folder (see `services/contract-risk-agent/migrations/` for an example —
  every statement is `IF NOT EXISTS` so it's safe to layer another
  service's migration on top of the same shared tables later).
- **REST response envelope**: every endpoint returns
  `{"data": {...}, "meta": {}}` on success or
  `{"error": {"code": "string", "message": "string"}}` on failure, with an
  appropriate HTTP status. `shared/http/error_handlers.py` is a drop-in
  FastAPI exception handler that enforces this — import
  `register_error_handlers` and call it on your `app` instead of letting
  `HTTPException` fall through to FastAPI's default `{"detail": ...}` shape.
- **Gateway routing**: `infra/nginx/nginx.conf` routes `/api/<prefix>/*` to
  each service by container name — see the table above.

## Repo etiquette

- Only write inside your own `services/<your-service>/` folder, plus the
  `data/` subfolder you own.
- `docker-compose.override.yml`, `shared/kafka-topics.yaml`, and this
  README are **append-only** for you — add your section, don't reorder or
  edit someone else's.
- Branch naming: `service/<your-name>-<short-desc>`. Open a PR into `main`.
- Before opening a PR: `docker compose down -v && ./install.sh && docker compose up -d`
  from a clean clone, with your override entry added, and confirm nothing
  else breaks.

---

## contract-risk-agent (Anjali)

Contract generation, e-signature routing, clause extraction, and vendor
risk scoring. Source: `services/contract-risk-agent/`.

### Endpoints (all under `/api/contracts/*` and `/api/vendors/*` via the gateway)

| Method | Path | Description |
|---|---|---|
| POST | `/contracts/generate` | Generate a contract from an approved purchase request + template |
| POST | `/contracts/{id}/send-for-signature` | Route a draft contract for e-signature |
| GET | `/contracts/{id}` | Contract status, renewal terms, full text |
| GET | `/contracts/renewals-due?within_days=N` | Contracts with a renewal window coming up |
| GET | `/vendors/{id}/risk` | Latest risk score + band + top contributing factors |
| POST | `/vendors/{id}/risk/recompute` | Manually re-score a vendor |
| POST | `/vendors/{id}/log-outcome` | Record an actual incident/no-incident outcome (feeds drift monitoring) |
| GET | `/vendors/risk-model/drift-check` | Manually trigger the population-stability drift check |
| POST | `/vendors/{id}/offboard` | Offboard a vendor: revoke access, flag active contracts for reconciliation, set data-retention |
| GET | `/health`, `/metrics` | Standard health/metrics endpoints |

### How it fits together

- **Contract generation** renders one of three Jinja2 templates
  (`app/templates/*.j2`), then runs the *same* clause-extraction code path
  used for any contract text (`app/services/clause_extraction.py`) to pull
  out renewal type / notice period / end date — so the extraction logic is
  exercised on real generated prose, not just trusted blindly.
- **Renewal reminders** are a per-contract Temporal workflow
  (`app/workflows/renewal_workflow.py`), started right after generation,
  that sleeps until 60/30/15 days before the contract's notice deadline and
  publishes `contract.renewal.due` at each milestone.
- **Vendor risk scoring** is a scikit-learn `RandomForestClassifier`
  (`ml/train_risk_model.py`) trained on
  `data/synthetic-vendors/vendor_risk_training_data.csv` (see that folder's
  README for provenance — Kaggle-seeded when available, documented
  synthetic fallback otherwise). Runs are logged to MLflow
  (http://localhost:5050). `POST /vendors/{id}/risk/recompute` scores a
  vendor and publishes `risk.score.updated`; a `High` band also fires an
  urgent `notification.send`.
- **Drift monitoring** (`app/services/drift_service.py`) computes a
  Population Stability Index between the score distribution at training
  time and the last N production scores, on a weekly Temporal schedule
  (`app/workflows/drift_workflow.py`) — a monitoring signal only, it never
  retrains automatically. Feed it ground truth via `POST /vendors/{id}/log-outcome`.
- **Vendor offboarding** revokes portal access, flags every active
  contract `reconciliation_status: pending_review` (never auto-closes —
  a human confirms final invoice/payment status), and sets a
  data-retention flag rather than deleting records.
- **Kafka**: publishes `contract.generated`, `contract.signed` (via the
  e-sign webhook added in the platform-wide hardening pass),
  `contract.renewal.due`, `risk.score.updated`, `vendor.offboarded`, and
  `notification.send`; consumes `vendor.matched` (scores a newly-matched
  vendor) and `approval.decided` (auto-generates a contract on approval).

### Running tests

```
cd services/contract-risk-agent
docker build -t contract-risk-agent .
docker run --rm -v "$(pwd):/app" -v "$(pwd)/../../shared:/app/shared" -w /app --entrypoint sh contract-risk-agent -c "python -m pytest -q tests"
```

Covers: clause extraction on 4 sample contract texts with known expected
renewal terms, the risk model producing a sane band ordering for an
obviously-low-risk vs obviously-high-risk feature vector, and a schema test
asserting every published event's keys match `shared/schemas/events.md`
exactly.

### Known infra fixes made while building this

A few gaps in the shared scaffold (Prompt 0) blocked this service from
running at all, so they're fixed at the shared-infra level rather than
worked around locally — anyone building the remaining services benefits
from these too:

- `.gitignore` excluded `docker-compose.override.yml` and `*.md` entirely,
  meaning no service wiring or documentation could ever be committed.
- Redpanda had no `--advertise-kafka-addr`, so it advertised `localhost`
  in its metadata response — every producer/consumer connected for the
  initial bootstrap but failed on the first actual publish/consume.
- `temporal` had no DB environment variables, so `auto-setup` defaulted to
  Cassandra and refused to start (`CASSANDRA_SEEDS env must be set`). It's
  now pointed at the shared Postgres instance.
- SQLAlchemy models across the codebase typed UUID primary/foreign keys as
  `String`, which Postgres rejects (`operator does not exist: uuid =
  character varying`) — this service's models use
  `sqlalchemy.dialects.postgresql.UUID`. Worth checking if other services'
  models do the same.
