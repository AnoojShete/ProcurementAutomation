FROM python:3.11-slim AS builder
WORKDIR /build
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5
COPY services/chatbot-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

COPY shared/ ./shared/
COPY services/chatbot-agent/migrations/ ./migrations/
COPY services/chatbot-agent/app/ ./app/
COPY services/chatbot-agent/docker-entrypoint.sh .

RUN chmod +x docker-entrypoint.sh
EXPOSE 8006

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006", "--log-level", "info"]