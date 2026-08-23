#!/usr/bin/env bash
# Entrypoint: run schema migration then start the FastAPI server.
# Migration is idempotent (uses IF NOT EXISTS) so re-running is safe.
set -e

echo "Running schema migration..."
python -m app.migrations

echo "Starting approval-inventory-agent on port 8002..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8002 --log-level info
