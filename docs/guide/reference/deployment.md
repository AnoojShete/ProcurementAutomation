# Deployment

The platform runs on one machine with Docker Compose (24 containers, plus a one-shot job that creates the Kafka topics).

## Requirements

- Docker with Compose v2, about 8 GB of memory for Docker (ClamAV alone holds ~1 GB).
- Internet for the first build, the breached-password check and optional model downloads.
- Optional: Ollama on the host for the assistant
  (`ollama pull llama3.2:3b && ollama pull nomic-embed-text`).

## Start

```bash
./run.sh                        # builds what changed, starts everything, waits for health
./scripts/seed-demo-data.sh     # demo data
./scripts/download-models.sh    # optional: LayoutLMv3 + Legal-BERT (~1 GB)
./scripts/download-sanctions.sh # optional: sanctions list (~80 MB)
```

| What | URL |
|---|---|
| App | <http://localhost:8080> |
| Mailpit (all development email) | <http://localhost:8025> |
| Grafana (admin / admin) | <http://127.0.0.1:3000> |
| Temporal UI | <http://localhost:8088> |
| MinIO console | <http://localhost:9001> |

Only port 8080 is reachable from other machines.

## After changing a service

```bash
docker compose up -d --build <service> <service>-worker   # workers run the service's image
docker compose up -d && docker compose restart nginx       # nginx caches upstream addresses
```

## Before a demo

```bash
./scripts/reset-demo.sh     # backs up, clears data volumes, rebuilds realistic demo data (~3 min)
```

## Backups

`./scripts/backup.sh` dumps Postgres and archives MinIO into `.run/backups/`;
`./scripts/restore.sh <stamp>` restores one (backing up the current data first).

## Production checklist

Set `APP_ENV=production` and real secrets, put HTTPS in front of the gateway,
set `EMAIL_MODE=smtp`, and replace placeholder role mailboxes with real
distribution lists. The full list is on the dashboard's Deployment tab
(`docs/index.html#deploy`).
