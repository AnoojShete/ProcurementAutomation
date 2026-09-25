# Multi-stage Dockerfile for the Document & Vendor Intelligence Agent.
# Build context is the REPO ROOT (not this folder) so `shared/` can be
# copied in — this service imports shared.http.error_handlers, shared.auth.
#   build: { context: ., dockerfile: services/document-vendor-agent/Dockerfile }
#
# Notable build choices:
#   - libgl1, libglib2.0-0: OpenCV (Docling transitive dep) needs these
#     in a headless container.
#   - libgomp1: OpenMP runtime required by PaddleOCR's C++ inference backend.
#   - HF_HOME set to /app/.cache/huggingface — mount as a named Docker
#     volume so the ~1GB LayoutLMv3 model is downloaded once and cached.
#   - CPU-only torch pinned in requirements.txt — no GPU needed for this
#     project's scale; substantially smaller image than the CUDA variant.

FROM python:3.11-slim AS builder
WORKDIR /build
COPY services/document-vendor-agent/requirements.txt .
# Extra PyTorch CPU index is declared inside requirements.txt with
# --extra-index-url; pip respects it when reading from the file.
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
# HF_HOME points to a named Docker volume (see docker-compose.override.yml)
# so the LayoutLMv3 model is cached across container rebuilds.
ENV HF_HOME=/app/.cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      libgl1 \
      libglib2.0-0 \
      libgomp1 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

COPY shared/ ./shared/
COPY services/document-vendor-agent/config.yaml .
COPY services/document-vendor-agent/migrations/ ./migrations/
COPY services/document-vendor-agent/app/ ./app/

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
