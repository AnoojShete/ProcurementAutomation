#!/usr/bin/env sh
set -e

echo "[notification-agent] waiting for postgres..."
python - <<'PYEOF'
import os, time, sys
import psycopg2
url = os.environ.get("APP_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@postgres:5432/postgres")
dsn = url.replace("postgresql+asyncpg://", "postgresql://")
for i in range(30):
    try:
        conn = psycopg2.connect(dsn)
        conn.close()
        print("postgres is up")
        sys.exit(0)
    except Exception as e:
        print(f"waiting for postgres ({i+1}/30): {e}")
        time.sleep(2)
sys.exit(1)
PYEOF

exec "$@"
