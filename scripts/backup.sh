#!/usr/bin/env bash
# Back up the data that can't be rebuilt: every Postgres database (the app,
# Temporal and Temporal visibility) and the MinIO documents bucket.
#
#   ./scripts/backup.sh            # → .run/backups/{postgres,miniodata}-<stamp>.*
#   ./scripts/backup.sh <stamp>    # use this stamp (reset-demo.sh passes its own)
#
# Runs against the live stack; nothing is stopped. Restore with
# ./scripts/restore.sh <stamp>. Not backed up, because they rebuild
# themselves: Kafka topics (events are already applied to Postgres; the
# outbox re-sends anything unpublished), Redis (cache, idempotency keys),
# model caches, ClamAV signatures, the sanctions list, Grafana and Loki.
set -euo pipefail
cd "$(dirname "$0")/.."

stamp="${1:-$(date +%Y%m%d-%H%M)}"
out=.run/backups
mkdir -p "$out"
project="$(docker compose config --format json | python3 -c 'import sys, json; print(json.load(sys.stdin)["name"])')"
pg_user="$(docker compose exec -T postgres printenv POSTGRES_USER 2>/dev/null || echo postgres)"

if docker compose ps --status running -q postgres | grep -q .; then
  docker compose exec -T postgres pg_dumpall -U "$pg_user" | gzip > "$out/postgres-$stamp.sql.gz"
  # An empty or truncated dump must not look like a good backup.
  gunzip -c "$out/postgres-$stamp.sql.gz" | tail -n 3 | grep -q "PostgreSQL database cluster dump complete" \
    || { echo "Postgres dump is incomplete: $out/postgres-$stamp.sql.gz" >&2; exit 1; }
  echo "Postgres → $out/postgres-$stamp.sql.gz ($(du -h "$out/postgres-$stamp.sql.gz" | cut -f1))"
else
  echo "Postgres isn't running; start the stack first (./run.sh)." >&2
  exit 1
fi

if docker volume inspect "${project}_miniodata" >/dev/null 2>&1; then
  docker run --rm -v "${project}_miniodata:/data:ro" -v "$PWD/$out:/backup" alpine:3.20 \
    tar czf "/backup/miniodata-$stamp.tgz" -C /data .
  echo "MinIO    → $out/miniodata-$stamp.tgz ($(du -h "$out/miniodata-$stamp.tgz" | cut -f1))"
fi
