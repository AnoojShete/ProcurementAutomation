#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")" && pwd)

echo "Checking for Docker..."
if ! command -v docker >/dev/null 2>&1; then
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Docker not found. Install Docker Desktop for Mac:" >&2
    echo "  brew install --cask docker" >&2
    echo "  (or download from https://www.docker.com/products/docker-desktop/)" >&2
  elif grep -qi microsoft /proc/version 2>/dev/null || [ -n "${WSL_DISTRO_NAME:-}" ]; then
    echo "Docker not found inside WSL. Install Docker Desktop for Windows on the" >&2
    echo "Windows host (not inside WSL) and enable WSL integration for this distro:" >&2
    echo "  Settings > Resources > WSL Integration" >&2
    echo "  https://www.docker.com/products/docker-desktop/" >&2
  else
    echo "Docker not found. On Ubuntu install Docker with:" >&2
    echo "  sudo apt update && sudo apt install -y ca-certificates curl gnupg lsb-release" >&2
    echo "  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg" >&2
    echo "  echo \"deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable\" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null" >&2
    echo "  sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin" >&2
  fi
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin not available. On Ubuntu ensure 'docker compose' is installed (see README-VM.md)." >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "Creating .env from .env.example"
  cp .env.example .env
fi

# Starts Docker Desktop / the Docker daemon automatically where possible
# (macOS, WSL2, native Linux) instead of just failing here — see the
# script for exactly what each platform does.
source "$ROOT_DIR/scripts/ensure-docker.sh"

echo "Bringing up core services..."
# Scoped to core infra only (docker-compose.yml's own services) — an
# unscoped `docker compose up -d` also starts every app service now
# defined in docker-compose.override.yml, before shared/db/init.sql has
# even been applied below. run.sh brings the app services up itself,
# afterward, in the right order (see its comments for why).
#
# --remove-orphans: cleans up containers left over from renamed/removed
# services that otherwise hold stale Docker-network references and cause
# "network <id> not found" errors on the next `up`.
CORE_SERVICES="postgres redis redpanda minio prometheus grafana temporal temporal-ui mailpit clamav"

# If any containers are already running with stale network references
# (e.g. ClamAV kept alive between runs), tear them down first so they
# don't block the fresh `up` with "network not found" errors.
docker compose down --remove-orphans 2>/dev/null || true

docker compose up -d --remove-orphans $CORE_SERVICES

echo "Waiting for core services to report healthy (Postgres, Redpanda, MinIO, ClamAV). This may take a few minutes on first run..."
MAX=120
for i in $(seq 1 $MAX); do
  healthy_count=0
  pg_status="unknown"
  rd_status="unknown"
  min_status="unknown"
  clamav_status="unknown"

  pg_cont=$(docker compose ps -q postgres 2>/dev/null || true)
  if [ -n "$pg_cont" ]; then
    pg_status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $pg_cont 2>/dev/null || echo "unknown")
    if [ "$pg_status" = "healthy" ] || [ "$pg_status" = "running" ]; then
      healthy_count=$((healthy_count+1))
    fi
  fi

  rd_cont=$(docker compose ps -q redpanda 2>/dev/null || true)
  if [ -n "$rd_cont" ]; then
    rd_status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $rd_cont 2>/dev/null || echo "unknown")
    if [ "$rd_status" = "healthy" ] || [ "$rd_status" = "running" ]; then
      healthy_count=$((healthy_count+1))
    fi
  fi

  min_cont=$(docker compose ps -q minio 2>/dev/null || true)
  if [ -n "$min_cont" ]; then
    min_status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $min_cont 2>/dev/null || echo "unknown")
    if [ "$min_status" = "healthy" ] || [ "$min_status" = "running" ]; then
      healthy_count=$((healthy_count+1))
    fi
  fi

  clamav_cont=$(docker compose ps -q clamav 2>/dev/null || true)
  if [ -n "$clamav_cont" ]; then
    clamav_status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $clamav_cont 2>/dev/null || echo "unknown")
    if [ "$clamav_status" = "healthy" ] || [ "$clamav_status" = "running" ]; then
      healthy_count=$((healthy_count+1))
    fi
  fi

  if [ "$healthy_count" -ge 4 ]; then
    echo "Core services are up."
    break
  fi

  if [ "$i" -eq "$MAX" ]; then
    echo "ERROR: Core services failed to become healthy within $((MAX * 5)) seconds." >&2
    echo "  postgres: $pg_status" >&2
    echo "  redpanda: $rd_status" >&2
    echo "  minio: $min_status" >&2
    echo "  clamav: $clamav_status" >&2
    
    # Print the detailed healthcheck log for the failing service(s)
    for svc in postgres redpanda minio clamav; do
      cont=$(docker compose ps -q $svc 2>/dev/null || true)
      if [ -n "$cont" ]; then
        status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $cont 2>/dev/null || echo "unknown")
        if [ "$status" != "healthy" ] && [ "$status" != "running" ]; then
           echo "--- $svc Healthcheck Log ---" >&2
           docker inspect --format='{{json .State.Health}}' $cont 2>/dev/null | grep -o '"Output":"[^"]*"' | tail -n 1 >&2 || true
        fi
      fi
    done
    exit 1
  fi

  echo "Waiting for services to become healthy... ($i/$MAX)"
  sleep 5
done

echo "Running DB init SQL if available..."
if [ -f shared/db/init.sql ]; then
  pg_cont=$(docker compose ps -q postgres 2>/dev/null || true)
  if [ -n "$pg_cont" ]; then
    docker cp shared/db/init.sql $pg_cont:/tmp/init.sql || true
    docker compose exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -f /tmp/init.sql || true
    echo "Applied shared/db/init.sql (best-effort)."
  else
    echo "Postgres container not found; skipping DB init." >&2
  fi
fi

echo "Creating Kafka topics listed in shared/kafka-topics.yaml (best-effort)..."
if [ -f shared/kafka-topics.yaml ]; then
  # Attempt to create each topic using Redpanda's rpk tool inside the redpanda container
  if docker compose ps -q redpanda >/dev/null 2>&1; then
    echo "Creating topics via redpanda rpk (best-effort)"
    topics=$(grep -oE '^[[:space:]]*-\s*[^[:space:]]+' shared/kafka-topics.yaml | sed 's/^-//; s/^\s*//') || true
    for t in $topics; do
      echo "Creating topic: $t"
      docker compose exec -T redpanda rpk topic create "$t" --brokers redpanda:9092 || true
    done
  else
    echo "Redpanda container not found; skipping automatic topic creation."
  fi
fi

echo "Ensure MinIO bucket exists (use mc client if installed)"
if command -v mc >/dev/null 2>&1; then
  if ! mc alias list | grep -q minio; then
    mc alias set local http://localhost:9000 "${MINIO_ROOT_USER:-minioadmin}" "${MINIO_ROOT_PASSWORD:-minioadmin}" || true
  fi
  mc mb --ignore-existing local/it-procurement || true
else
  # Try using containerized mc on the compose network
  NETNAME="${NETWORK_NAME:-it-procurement-network}"
  echo "Attempting to create MinIO bucket using containerized mc on network $NETNAME"
  docker run --rm --network "$NETNAME" minio/mc:latest alias set local http://minio:9000 "${MINIO_ROOT_USER:-minioadmin}" "${MINIO_ROOT_PASSWORD:-minioadmin}" || true
  docker run --rm --network "$NETNAME" minio/mc:latest mb --ignore-existing local/it-procurement || true
fi

echo "Summary URLs:
Grafana: http://localhost:3000
Prometheus: http://localhost:9090
MinIO: http://localhost:9000
Mailpit: http://localhost:8025
Temporal UI: http://localhost:8088 (if available)
"

echo "Done."
