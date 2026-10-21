#!/usr/bin/env bash
# Put the stack back into a clean, realistic demo state (docs/index.html#demo-5min).
#
#   ./scripts/reset-demo.sh          # asks before deleting anything
#   ./scripts/reset-demo.sh --yes    # no question (e.g. the night before)
#
# 1. backs up Postgres and MinIO to .run/backups/ (scripts/backup.sh; undo: scripts/restore.sh)
# 2. deletes only the data volumes (Postgres, MinIO, Kafka); model caches,
#    the sanctions list, ClamAV signatures, MLflow and Grafana are kept
# 3. starts the stack, seeds the demo accounts and data
# 4. runs the five demo scenarios (realistic history made by the real flows)
#    and adds the sanctions-listed vendor and an unsigned contract
#
# Takes ~5 minutes. Needs the e2e requirements on the host:
#   pip install -r tests/e2e/requirements.txt playwright && playwright install chromium
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"

if [ "${1:-}" != "--yes" ]; then
  echo "This deletes all requests, documents, vendors, contracts and sign-up accounts"
  echo "(a backup is taken first). Model caches and the sanctions list are kept."
  read -r -p "Reset the demo data? [y/N] " answer
  [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "Nothing changed."; exit 0; }
fi
"$PY" -c "import playwright, requests" 2>/dev/null || {
  echo "Missing host packages: pip install -r tests/e2e/requirements.txt playwright" >&2; exit 1; }

project="$(docker compose config --format json | "$PY" -c 'import sys, json; print(json.load(sys.stdin)["name"])')"
stamp="$(date +%Y%m%d-%H%M)"
mkdir -p .run/backups

echo "[1/4] backup → .run/backups/*-$stamp.*"
if docker compose ps --status running -q postgres | grep -q .; then
  ./scripts/backup.sh "$stamp"
fi
if [ -d inbox/processed ] || [ -d inbox/failed ]; then
  mkdir -p ".run/backups/inbox-$stamp"
  for d in processed failed; do [ -d "inbox/$d" ] && mv "inbox/$d" ".run/backups/inbox-$stamp/"; done
fi

echo "[2/4] delete data volumes (Postgres, MinIO, Kafka)"
docker compose down
for v in pgdata miniodata redpanda-data; do
  docker volume rm "${project}_$v" >/dev/null 2>&1 || true
done

echo "[3/4] start and seed"
./run.sh --no-build
./scripts/seed-demo-data.sh >/dev/null

echo "[4/4] demo history (the five scenarios), sanctions-listed vendor, unsigned contract"
"$PY" tests/e2e/demo_scenarios.py
"$PY" tests/e2e/showcase_screens.py sanctions contract

echo
echo "Demo data ready. Rehearse: $PY tests/e2e/demo_5min.py"
echo "Undo: ./scripts/restore.sh $stamp"
