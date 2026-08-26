# Multi-stage Dockerfile for the Approval & Inventory Intelligence Agent
# Stage 1: Install dependencies
# Stage 2: Minimal runtime image

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
COPY services/approval-inventory-agent/migrations/ ./migrations/
COPY services/approval-inventory-agent/app/ ./app/
COPY services/approval-inventory-agent/entrypoint.sh .
RUN chmod +x entrypoint.sh

EXPOSE 8002

# Entrypoint runs migration then launches uvicorn
CMD ["/bin/bash", "entrypoint.sh"]
