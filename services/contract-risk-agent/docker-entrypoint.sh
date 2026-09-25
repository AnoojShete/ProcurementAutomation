#!/usr/bin/env sh
set -e

echo "[contract-risk-agent] waiting for postgres..."
python - <<'PYEOF'
import os, time, sys
import psycopg2
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

echo "[contract-risk-agent] running migrations..."
alembic upgrade head

if [ ! -f ml/artifacts/model.joblib ]; then
  echo "[contract-risk-agent] training risk model (first boot)..."
  python ml/train_risk_model.py || echo "[contract-risk-agent] model training skipped, will lazy-train on first request"
fi

exec "$@"
