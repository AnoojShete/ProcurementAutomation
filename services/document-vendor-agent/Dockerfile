# Multi-stage Dockerfile for the Document & Vendor Intelligence Agent.
# Build context is the REPO ROOT (not this folder) so `shared/` can be
# copied in — this service imports shared.http.error_handlers, same
# tradeoff as services/contract-risk-agent/Dockerfile.
# docker-compose.override.yml's entry for this service must set:
#   build: { context: ., dockerfile: services/document-vendor-agent/Dockerfile }

FROM python:3.11-slim AS builder
WORKDIR /build
COPY services/document-vendor-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# curl: healthcheck. tesseract-ocr: pytesseract shells out to the `tesseract`
# binary for OCR on scanned images — it is NOT a pip-installable dependency.
RUN apt-get update && apt-get install -y --no-install-recommends curl tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

COPY shared/ ./shared/
COPY services/document-vendor-agent/config.yaml .
COPY services/document-vendor-agent/migrations/ ./migrations/
COPY services/document-vendor-agent/app/ ./app/

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
