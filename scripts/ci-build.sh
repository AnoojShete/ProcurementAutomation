#!/usr/bin/env bash
# Builds every service image the way docker-compose.override.yml does:
# context = repo root (the Dockerfiles copy shared/ and data/), file =
# services/<name>/Dockerfile. Images aren't pushed, so each is removed
# after its build to stay inside the CI runner's disk space.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
repo="${GITHUB_REPOSITORY:-local}"
repo="${repo,,}"
echo "Looking for service Dockerfiles under services/"
for d in services/*; do
  if [ -d "$d" ] && [ -f "$d/Dockerfile" ]; then
    name=$(basename "$d")
    echo "Building Docker image for $name"
    docker build -f "$d/Dockerfile" -t "$repo/$name:ci" .
    docker image rm "$repo/$name:ci" >/dev/null
  fi
done
echo "CI build script finished."
