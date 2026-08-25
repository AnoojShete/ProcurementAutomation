#!/usr/bin/env bash
# One script that brings up the ENTIRE platform from a clean clone:
# core infra -> build every service image -> ClamAV (slow first boot) ->
# every app service + its worker -> gateway/frontend -> optional demo data.
#
# Individual pieces can be run/tested on their own via scripts/ — see
# scripts/test-service.sh (per-service pytest) and scripts/seed-demo-data.sh
# (seed one vendor + approved purchase request for a quick demo).
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT_DIR"

echo "=================================================================="
echo "  IT Procurement Intelligence Platform — full stack bring-up"
echo "=================================================================="
echo

echo "--- [1/6] Core infra (postgres, redis, kafka, minio, temporal, ---"
echo "---       prometheus, grafana, nginx, mailpit) via install.sh  ---"
./install.sh

echo
echo "--- [2/6] Building every service image ---"
docker compose build

echo
echo "--- [3/6] Starting ClamAV (malware scanning) — first boot pulls ---"
echo "---       virus definitions, can take a couple of minutes      ---"
docker compose up -d clamav
echo -n "Waiting for ClamAV to report healthy"
for i in $(seq 1 60); do
  status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' \
    "$(docker compose ps -q clamav)" 2>/dev/null || echo "starting")
  if [ "$status" = "healthy" ]; then
    echo " healthy."
    break
  fi
  echo -n "."
  sleep 5
done

echo
echo "--- [4/6] Starting every app service + its worker ---"
docker compose up -d \
  auth-service \
  document-vendor-agent document-vendor-agent-worker \
  approval-inventory-agent approval-inventory-agent-worker \
  contract-risk-agent contract-risk-agent-worker \
  notification-agent \
  mlflow

echo
echo "--- [5/6] Recreating the gateway (nginx) ---"
echo "---       nginx resolves every upstream hostname at boot, so it ---"
echo "---       needs a restart now that every service above exists  ---"
docker compose up -d nginx --force-recreate

echo
echo "--- [6/6] Waiting for every service's healthcheck ---"
SERVICES="postgres redis redpanda minio temporal clamav auth-service document-vendor-agent approval-inventory-agent contract-risk-agent notification-agent"
for i in $(seq 1 30); do
  unhealthy=""
  for svc in $SERVICES; do
    cid=$(docker compose ps -q "$svc" 2>/dev/null || true)
    [ -z "$cid" ] && continue
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo "unknown")
    if [ "$status" != "healthy" ] && [ "$status" != "running" ]; then
      unhealthy="$unhealthy $svc($status)"
    fi
  done
  if [ -z "$unhealthy" ]; then
    echo "All services healthy."
    break
  fi
  echo "Still waiting on:$unhealthy ($i/30)"
  sleep 5
done

echo
echo "=================================================================="
echo "  Stack is up. Seed a demo vendor + approved purchase request:"
echo "    ./scripts/seed-demo-data.sh"
echo
echo "  URLs:"
echo "    Frontend             http://localhost:8080/"
echo "    API gateway           http://localhost:8080/api/..."
echo "    Grafana               http://localhost:3000"
echo "    Prometheus            http://localhost:9090"
echo "    Temporal UI            http://localhost:8088"
echo "    MLflow                http://localhost:5050"
echo "    MinIO console          http://localhost:9000"
echo "    Mailpit                http://localhost:8025"
echo
echo "  Demo logins (see README's Security & Auth section):"
echo "    requester@demo.example.com / DemoPass123!"
echo "    approver@demo.example.com  / DemoPass123!"
echo "    finance@demo.example.com   / DemoPass123!"
echo "    admin@demo.example.com     / DemoPass123!"
echo
echo "  Run one service's tests:  ./scripts/test-service.sh <name>"
echo "  Run every service's tests: ./scripts/test-service.sh all"
echo "  Run the end-to-end test:   make e2e"
echo "=================================================================="
