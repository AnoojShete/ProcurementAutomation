#!/usr/bin/env bash
# One-time download of the models into the shared hf-cache volume:
#   - LayoutLMv3 invoice model (~500 MB) — document-vendor-agent's
#     cross-check, skipped ("skipped_model_unavailable") until downloaded;
#   - Legal-BERT fine-tuned on CUAD (~440 MB) — contract-risk-agent's clause
#     extraction (FR-13), which uses the regex rules until downloaded.
# Both are loaded with local_files_only=True, so nothing waits on a download.
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

echo "Downloading LayoutLMv3 and Legal-BERT (CUAD) into the hf-cache volume..."
docker compose run --rm --no-deps -T -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 document-vendor-agent-worker python -c "
from transformers import LayoutLMv3Processor, LayoutLMv3ForTokenClassification
m = 'ngvozdenovic/invoice_extraction'
LayoutLMv3Processor.from_pretrained(m, apply_ocr=False)
LayoutLMv3ForTokenClassification.from_pretrained(m)
print('LayoutLMv3 cached.')
from transformers import AutoTokenizer, AutoModelForQuestionAnswering
m = 'alex-apostolo/legal-bert-base-cuad'
AutoTokenizer.from_pretrained(m)
AutoModelForQuestionAnswering.from_pretrained(m)
print('Legal-BERT (CUAD) cached.')
"
echo "Restarting the services so they pick the models up..."
docker compose restart document-vendor-agent-worker contract-risk-agent >/dev/null
echo "Done."
