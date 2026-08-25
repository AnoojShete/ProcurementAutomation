# Multi-stage Dockerfile for the Contract & Risk Analysis Agent.
# Build context is the REPO ROOT (not this folder) so `shared/` can be
# copied in — this service imports shared.http.error_handlers.
# docker-compose.override.yml's entry for this service must set:
#   build: { context: ., dockerfile: services/contract-risk-agent/Dockerfile }

FROM python:3.11-slim AS builder
WORKDIR /build
COPY services/contract-risk-agent/requirements.txt .
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
COPY services/contract-risk-agent/config.yaml .
COPY services/contract-risk-agent/alembic.ini .
COPY services/contract-risk-agent/migrations/ ./migrations/
COPY services/contract-risk-agent/app/ ./app/
COPY services/contract-risk-agent/ml/ ./ml/
COPY services/contract-risk-agent/docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8003

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", "--log-level", "info"]
