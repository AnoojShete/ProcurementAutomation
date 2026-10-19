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
ENV PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5
COPY services/document-vendor-agent/requirements.txt .
# Extra PyTorch CPU index is declared inside requirements.txt with
# --extra-index-url; pip respects it when reading from the file.
# BuildKit cache mount: a requirements change re-downloads only what changed.
RUN --mount=type=cache,target=/root/.cache/pip pip install --default-timeout=120 --retries=5 -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
# HF_HOME points to a named Docker volume (see docker-compose.override.yml)
# so the LayoutLMv3 model is cached across container rebuilds.
ENV HF_HOME=/app/.cache/huggingface
# torchvision and paddle ship their own zlib builds; whichever loads first
# can be used by the others and fail with "inconsistent stream state" or a
# segfault in inflateReset2 (PaddleOCR then returns no text). Preloading the
# system zlib makes every library use the one copy.
ENV LD_PRELOAD=libz.so.1

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

# FR-29: train the document classifier at build time. It is saved — and so
# used — only if it beats the keyword classifier on held-out documents.
COPY services/document-vendor-agent/ml/ ./ml/
COPY services/document-vendor-agent/scripts/synthetic_invoice_lib.py services/document-vendor-agent/scripts/export_evidence.py ./scripts/
COPY data/synthetic-classification/ ./data/synthetic-classification/
RUN python ml/train_classifier.py

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
