#!/usr/bin/env bash
# Run one service's pytest suite inside its own built image, with the
# service folder (and shared/, for services that import it) volume-mounted
# so tests run against the current source, not whatever was baked into the
# image at the last `docker compose build`.
#
# Usage:
#   scripts/test-service.sh <service-name>   # e.g. contract-risk-agent
#   scripts/test-service.sh all              # every service with a tests/ folder
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

PROJECT_NAME=$(basename "$ROOT_DIR" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')

ALL_SERVICES=(contract-risk-agent approval-inventory-agent document-vendor-agent notification-agent auth-service)

run_one() {
  local svc="$1"
  if [ ! -d "services/$svc/tests" ]; then
    echo "skip: services/$svc/tests does not exist"
    return 0
  fi
  local image="${PROJECT_NAME}-${svc}"
  echo "=== Testing $svc ($image) ==="
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "Image $image not found locally — building it first..."
    docker compose build "$svc"
  fi
  docker run --rm \
    -v "$ROOT_DIR/services/$svc:/app" \
    -v "$ROOT_DIR/shared:/app/shared" \
    -w /app \
    --entrypoint sh \
    "$image" \
    -c "python -m pytest -q tests"
}

target="${1:-all}"
if [ "$target" = "all" ]; then
  failed=()
  for svc in "${ALL_SERVICES[@]}"; do
    if ! run_one "$svc"; then
      failed+=("$svc")
    fi
  done
  echo
  if [ ${#failed[@]} -eq 0 ]; then
    echo "All service test suites passed."
  else
    echo "FAILED: ${failed[*]}"
    exit 1
  fi
else
  run_one "$target"
fi
