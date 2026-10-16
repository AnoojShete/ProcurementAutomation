# Extraction accuracy

Generated 2026-10-15T18:21:44+00:00 by `services/document-vendor-agent/scripts/eval_extraction.py` on `data/synthetic-invoices` (ground truth in `manifest.json`). Image documents are also tested as rotated (4°), noisy and half-resolution copies.

## Overall

| | doc_type | vendor | document_number | document_date | total | currency | all fields |
|---|---|---|---|---|---|---|---|
| PDFs (15) | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | **100 %** |
| Images, no preprocessing (24) | 100 % | 33 % | 50 % | 42 % | 42 % | 67 % | **56 %** |
| Images, with preprocessing (24) | 96 % | 38 % | 42 % | 29 % | 38 % | 67 % | **51 %** |

## Images by variant (all fields)

| Variant | Without preprocessing | With preprocessing |
|---|---|---|
| original | 56 % | 64 % |
| rotated 4deg | 56 % | 58 % |
| noisy | 56 % | 53 % |
| half resolution | 56 % | 31 % |
