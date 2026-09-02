#!/usr/bin/env bash
# Entrypoint: wait for postgres, run schema migration, then start FastAPI.
# Migration is idempotent (uses IF NOT EXISTS) so re-running is safe.
set -e

echo "[approval-inventory-agent] waiting for postgres..."
python - <<'PYEOF'
import os, time, sys
try:
    import psycopg2
except ImportError:
    print("psycopg2 not available, skipping sync wait — relying on asyncpg retry")
    sys.exit(0)

url = os.environ.get("APP_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/postgres")
dsn = url.replace("postgresql+asyncpg://", "postgresql://")
for i in range(60):
    try:
        conn = psycopg2.connect(dsn)
        conn.close()
        print("postgres is up")
        sys.exit(0)
    except Exception as e:
        print(f"waiting for postgres ({i+1}/60): {e}")
        time.sleep(2)
sys.exit(1)
PYEOF

echo "[approval-inventory-agent] running schema migration..."
# Run as __main__ so the asyncio.run(run_all()) guard fires correctly.
python app/migrations/migration_001_extend_schema.py

echo "[approval-inventory-agent] starting on port 8002..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8002 --log-level info
