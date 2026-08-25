# Build context is the REPO ROOT (not this folder) — this service imports
# shared.auth and shared.http. docker-compose.override.yml's entry for
# this service must set: build: { context: ., dockerfile: services/auth-service/Dockerfile }

FROM python:3.11-slim AS builder
WORKDIR /build
COPY services/auth-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

COPY shared/ ./shared/
COPY services/auth-service/alembic.ini .
COPY services/auth-service/migrations/ ./migrations/
COPY services/auth-service/app/ ./app/
COPY services/auth-service/seed_demo_users.py .
COPY services/auth-service/docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8005

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005", "--log-level", "info"]
