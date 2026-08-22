#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
echo "Looking for service Dockerfiles under services/"
for d in services/*; do
  if [ -d "$d" ] && [ -f "$d/Dockerfile" ]; then
    name=$(basename "$d")
    echo "Building Docker image for $name"
    docker build -t "${GITHUB_REPOSITORY:-local}/$name:ci" "$d"
  fi
done
echo "CI build script finished."
