# Extraction accuracy

Generated 2026-10-16T10:31:46+00:00 by `services/document-vendor-agent/scripts/eval_extraction.py` on `data/synthetic-invoices` (ground truth in `manifest.json`). Image documents are also tested as rotated (4°), noisy and half-resolution copies.

## Overall

| | doc_type | vendor | document_number | document_date | total | currency | all fields |
|---|---|---|---|---|---|---|---|
| PDFs (15) | 100 % | 100 % | 100 % | 100 % | 100 % | 100 % | **100 %** |
| Images, no preprocessing (24) | 50 % | 33 % | 50 % | 42 % | 42 % | 67 % | **47 %** |
| Images, with preprocessing (24) | 50 % | 54 % | 50 % | 38 % | 38 % | 67 % | **49 %** |

## Images by variant (all fields)

| Variant | Without preprocessing | With preprocessing |
|---|---|---|
| original | 47 % | 53 % |
| rotated 4deg | 47 % | 53 % |
| noisy | 47 % | 44 % |
| half resolution | 47 % | 47 % |
