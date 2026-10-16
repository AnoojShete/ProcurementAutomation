#!/usr/bin/env bash
# Root tests (shared/ code, config checks, cross-service tests) inside the
# service images — no host Python needed. tests/test_email_action.py imports
# approval-inventory-agent, so it runs in that image; the rest in auth-service's.
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
P=${COMPOSE_PROJECT_NAME:-procurementautomation}
docker run --rm -e APP_ENV=development -v "$ROOT_DIR:/w" -w /w --entrypoint sh "$P-auth-service" \
  -c "pip -q install pyyaml >/dev/null 2>&1; python -m pytest -q -p no:cacheprovider tests --ignore=tests/e2e --ignore=tests/test_email_action.py"
docker run --rm -e APP_ENV=development -v "$ROOT_DIR:/w" -w /w --entrypoint sh "$P-approval-inventory-agent" \
  -c "python -m pytest -q -p no:cacheprovider tests/test_email_action.py"
