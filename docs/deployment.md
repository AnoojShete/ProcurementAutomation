# Deployment, backups and recovery

The project runs as one Docker Compose stack on one machine. It has
**not** been deployed anywhere shared (a team decision). This page says
what a deployment needs, what was checked on Oct 19, 2026 and how to
back up and restore the data.

## 1. What was checked (Oct 19, 2026)

| Check | How | Result |
|---|---|---|
| Services refuse published secrets in production | each service image started with `APP_ENV=production` and no secrets | all 6 refused (`InsecureConfigError` naming the secret) |
| Services start with real secrets | the same, with every secret below set to a new value | all 6 services and their workers start |
| Business rules reach every service with a real secret | `RULES_ENGINE_INTERNAL_SECRET` was passed only to auth-service, so with a real value the others got 403 and silently used code defaults; now passed to every service and worker that reads rules (`tests/test_security_config.py`) | 47 rules fetched by each |
| Temporal keeps working with a real `POSTGRES_PASSWORD` | its password was hard-coded to `postgres`; now taken from `POSTGRES_PASSWORD` | config resolves |
| Backup is complete | `./scripts/backup.sh`, then the dump loaded into a throwaway `postgres:16` container and the MinIO copy unpacked into a scratch volume | 0 errors; requests, documents, vendors, contracts, users and Temporal executions identical to the live stack; every MinIO object present |
| Role checks on the server | through the gateway: requester on an admin endpoint, no token on each list | 403 / 401 |
| Logout ends the session | refresh with a copy of the cookie taken before logout | 401 |
| Dependencies | `npm audit`, `pip-audit` on every service image | see [§5](#5-known-dependency-advisories) |

Not checked: a run on a second machine or a cloud host, TLS, a real SMTP
server or real e-signature accounts.

## 2. Before any shared deployment

1. **Rotate the GSTINCheck API key.** The old key is in git history
   (commits `747ea13`, `0413162`) and the repository is public. Only its
   owner can revoke it at gstincheck.co.in. Put the new key in `.env` only.
2. **Set `APP_ENV=production`** in `.env`. This turns off demo accounts,
   showcase endpoints, simulated signing and `EMAIL_MODE=dev`, and makes
   the services refuse the published defaults.
3. **Set a new value for every secret** (`openssl rand -hex 32` for each):

   | Variable | Used by |
   |---|---|
   | `JWT_SECRET` | every service (signs and checks logins) |
   | `POSTGRES_PASSWORD` | Postgres, every service, Temporal |
   | `MINIO_ROOT_PASSWORD` | MinIO, document-vendor-agent |
   | `ESIGN_WEBHOOK_SECRET` | contract-risk-agent |
   | `RULES_ENGINE_INTERNAL_SECRET` | auth-service and the services reading rules |
   | `INTERNAL_SERVICE_TOKEN` | notification-agent → approval-inventory-agent |
   | `KAFKA_ADMIN_PASSWORD`, `KAFKA_PASSWORD_*` | Redpanda and each service's Kafka login |
   | `EMAIL_INTAKE_PASSWORD` | the intake mailbox, if email intake is on |

   Changing `POSTGRES_PASSWORD` or the Kafka passwords on an existing
   stack needs fresh volumes, because both are set when a volume is
   first created. Back up first (§4).
4. **Email**: `EMAIL_MODE=smtp` and the `SMTP_*` settings. `PUBLIC_BASE_URL`
   must be the HTTPS address people use, because emailed links carry
   one-time tokens.
5. **HTTPS**: put a TLS-terminating proxy (Caddy, or nginx with
   Let's Encrypt) in front of port 8080 and leave `AUTH_COOKIE_SECURE`
   unset (it is on outside development). Only the gateway listens on all
   interfaces; Temporal, Kafka, MinIO, MLflow, Grafana and the services
   are bound to `127.0.0.1` (tested by `tests/test_security_config.py`).
6. **Frontend**: build with `VITE_SHOW_DEMO_ACCOUNTS=false`
   (`cd frontend && VITE_SHOW_DEMO_ACCOUNTS=false npm run build`).
7. **Grafana**: add `GF_SECURITY_ADMIN_PASSWORD` to the `grafana`
   service's environment if anyone other than the operator can reach it
   (it is bound to `127.0.0.1:3000` and starts with admin/admin).
8. **Start**: `./run.sh`, then check `docker compose ps` (all healthy) and
   sign in as the first admin. Create accounts through sign-up and give
   roles on the Users page.
9. **Backups**: schedule `./scripts/backup.sh` (for example nightly with
   cron) and copy `.run/backups/` to another machine.

## 3. What holds the data

| Volume | Contents | Backed up? |
|---|---|---|
| `pgdata` | every table, accounts, business rules, audit log, Temporal's workflow state | yes, `pg_dumpall` |
| `miniodata` | uploaded documents and generated contract PDFs | yes, a tar of the volume |
| `redpanda-data` | Kafka topics | no: each event is already applied to Postgres; unsent events wait in the outbox table |
| (no volume) Redis | cache, idempotency keys, rate-limit counters | no: rebuilt on use |
| `hf-cache`, `docling-models`, `paddleocr-models`, `clamav-data` | models and virus signatures | no: `./scripts/download-models.sh` and ClamAV's updater fetch them again |
| `grafana-data`, `loki-data` | dashboards (provisioned from `infra/`) and logs | no |

## 4. Backup and restore

```bash
./scripts/backup.sh               # → .run/backups/postgres-<stamp>.sql.gz + miniodata-<stamp>.tgz
./scripts/restore.sh              # list the backups
./scripts/restore.sh <stamp>      # replace all data with that backup
```

- `backup.sh` runs against the live stack without stopping anything, and
  fails if the dump is incomplete. A backup is about 2 MB of SQL plus the
  size of the documents.
- `restore.sh` first backs up the current data as `<now>-before-restore`,
  so a restore can be undone with another restore. It then stops the
  stack, empties the Postgres, MinIO and Kafka volumes, loads the backup
  and starts everything with `./run.sh --no-build`.
- `./scripts/reset-demo.sh` uses `backup.sh` before it clears the demo
  data, and prints the `restore.sh` command that undoes it.

To move the platform to another machine: run `backup.sh`, copy the two
files into `.run/backups/` on the new machine, run `./install.sh` there,
then `./scripts/restore.sh <stamp>`.

## 5. Known dependency advisories

After the Oct 19 upgrades (FastAPI 0.148 / Starlette 1.9 everywhere;
Pillow 12.3, pdfplumber 0.11.10 / pdfminer.six 20260107, Docling 2.140,
accelerate 1.15 on the upload path; cryptography 50; aiosmtplib 5.1;
react-router 7.18; vite 6.4), these remain, each a deliberate choice:

| Package | Where | Why it stays |
|---|---|---|
| MLflow 2.14.3 (+ its pyarrow, protobuf) | approval-inventory and contract-risk (client); the `mlflow` container | 3.x is a major upgrade of the model registry; the server is bound to localhost and holds no business data |
| paddlepaddle 2.6.2, imgaug 0.4.0 | document-vendor-agent (image OCR) | the advisories are in Paddle's graph-drawing and download helpers and imgaug's multicore augmenter, which the OCR path doesn't call; the fix is PaddleOCR 3, a rewrite of the OCR integration; imgaug has no fixed release |
| pytest 8.2.2 | test runner in each image | test-only |
| braces, micromatch, chokidar (via Tailwind 3); postcss-selector-parser | frontend build tooling | no patched `braces` release; the fix is Tailwind 4, a styling rewrite; they only run at build time on our own files |

Re-run the audits with `npm audit` in `frontend/` and `pip-audit` on
`pip freeze` from each image (`docker run --rm --entrypoint pip <image> freeze`).
