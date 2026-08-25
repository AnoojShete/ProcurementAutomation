# Multi-stage Dockerfile for the Notification Agent.
# Build context is the REPO ROOT (not this folder) so `shared/` can be
# copied in — this service imports shared.http.error_handlers, matching
# services/contract-risk-agent/Dockerfile's approach.
# docker-compose.override.yml's entry for this service must set:
#   build: { context: ., dockerfile: services/notification-agent/Dockerfile }

FROM python:3.11-slim AS builder
WORKDIR /build
COPY services/notification-agent/requirements.txt .
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
COPY services/notification-agent/config.yaml .
COPY services/notification-agent/migrations/ ./migrations/
COPY services/notification-agent/app/ ./app/
COPY services/notification-agent/docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8004

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004", "--log-level", "info"]
