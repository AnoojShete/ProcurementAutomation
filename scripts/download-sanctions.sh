#!/usr/bin/env bash
# Downloads the OpenSanctions consolidated sanctions list (~80 MB, no API key)
# into contract-risk-agent's sanctions-data volume and builds the index used
# for vendor screening (FR-14). Data licence: CC BY-NC 4.0 (non-commercial).
# After this, contract-risk-agent refreshes it once a day.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T contract-risk-agent python -m app.services.sanctions refresh
