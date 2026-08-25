# Multi-stage Dockerfile for the Approval & Inventory Intelligence Agent
# Build context is the REPO ROOT (not this folder) — this service imports
# shared.http and shared.auth (added in the Prompt 5 hardening pass).
# docker-compose.override.yml's entry for this service must set:
#   build: { context: ., dockerfile: services/approval-inventory-agent/Dockerfile }

FROM python:3.11-slim AS builder
WORKDIR /build
COPY services/approval-inventory-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy application code
COPY shared/ ./shared/
COPY services/approval-inventory-agent/config.yaml .
COPY services/approval-inventory-agent/app/ ./app/
COPY services/approval-inventory-agent/migrations/ ./migrations/

EXPOSE 8002

# Run FastAPI with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--log-level", "info"]
