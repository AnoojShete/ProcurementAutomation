#!/usr/bin/env bash
# Put a backup from ./scripts/backup.sh back: replaces ALL current data.
#
#   ./scripts/restore.sh                 # lists the backups
#   ./scripts/restore.sh <stamp>         # asks, backs up the current data, restores
#   ./scripts/restore.sh <stamp> --yes   # no question
#
# 1. backs up the current data as <now>-before-restore (so this is undoable)
# 2. stops the stack and empties the Postgres, MinIO and Kafka volumes
# 3. starts Postgres alone and loads the dump; untars the MinIO copy
# 4. starts the whole stack (./run.sh --no-build)
# Kafka starts empty; the services recreate their topics at startup.
set -euo pipefail
cd "$(dirname "$0")/.."

out=.run/backups
stamp="${1:-}"
if [ -z "$stamp" ]; then
  echo "Backups in $out:"
  ls "$out" 2>/dev/null | sed -n 's/^postgres-\(.*\)\.sql\.gz$/  \1/p'
  echo "Restore one with: ./scripts/restore.sh <stamp>"
  exit 0
fi
dump="$out/postgres-$stamp.sql.gz"
files="$out/miniodata-$stamp.tgz"
[ -f "$dump" ] || { echo "No $dump" >&2; exit 1; }
gunzip -t "$dump"
[ ! -f "$files" ] || tar tzf "$files" >/dev/null

if [ "${2:-}" != "--yes" ]; then
  echo "This replaces all requests, documents, vendors, contracts, accounts and workflows"
  echo "with the backup from $stamp (the current data is backed up first)."
  read -r -p "Restore? [y/N] " answer
  [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "Nothing changed."; exit 0; }
fi

project="$(docker compose config --format json | python3 -c 'import sys, json; print(json.load(sys.stdin)["name"])')"

echo "[1/4] backup of the current data"
./scripts/backup.sh "$(date +%Y%m%d-%H%M)-before-restore"

echo "[2/4] stop the stack, empty the data volumes"
docker compose down
for v in pgdata miniodata redpanda-data; do
  docker volume rm "${project}_$v" >/dev/null 2>&1 || true
done

echo "[3/4] load $dump${files:+ and $files}"
docker compose up -d postgres
until docker compose exec -T postgres pg_isready -q 2>/dev/null; do sleep 1; done
pg_user="$(docker compose exec -T postgres printenv POSTGRES_USER)"
# The dump re-creates the roles and databases; the ones the image just made
# already exist, so "already exists" errors are expected and harmless.
gunzip -c "$dump" | docker compose exec -T postgres psql -q -U "$pg_user" -d postgres >/dev/null 2>"$out/restore-$stamp.log" || true
if grep -v -E "already exists|^$" "$out/restore-$stamp.log" | grep -q ERROR; then
  echo "Unexpected errors while loading (see $out/restore-$stamp.log):" >&2
  grep -v "already exists" "$out/restore-$stamp.log" | grep ERROR | head -5 >&2
fi
if [ -f "$files" ]; then
  docker compose create minio >/dev/null 2>&1  # creates the volume the way compose expects
  docker run --rm -v "${project}_miniodata:/data" -v "$PWD/$out:/backup:ro" alpine:3.20 \
    tar xzf "/backup/miniodata-$stamp.tgz" -C /data
fi

echo "[4/4] start the stack"
./run.sh --no-build
echo "Restored $stamp. Undo: ./scripts/restore.sh <the -before-restore stamp above>"
