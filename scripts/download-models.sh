#!/usr/bin/env bash
# One-time download of the LayoutLMv3 invoice model (~500 MB) into the
# shared hf-cache volume. The pipeline loads it with local_files_only=True
# so an upload never waits on a download; until this has been run, the
# LayoutLMv3 cross-check is skipped ("skipped_model_unavailable").
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

echo "Downloading LayoutLMv3 (ngvozdenovic/invoice_extraction) into the hf-cache volume..."
docker compose run --rm --no-deps -T document-vendor-agent-worker python -c "
from transformers import LayoutLMv3Processor, LayoutLMv3ForTokenClassification
m = 'ngvozdenovic/invoice_extraction'
LayoutLMv3Processor.from_pretrained(m, apply_ocr=False)
LayoutLMv3ForTokenClassification.from_pretrained(m)
print('LayoutLMv3 cached.')
"
echo "Restarting the worker so it picks the model up..."
docker compose restart document-vendor-agent-worker >/dev/null
echo "Done."
