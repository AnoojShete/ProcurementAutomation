# Model routing and fallback (FR-08)

Where the platform chooses between a primary model and a fallback, when the
fallback fires, and how to show it on demand. Checked against the code on
16 Oct 2026.

Every routed decision is written to `model_routing_log` (route, model,
fallback and its reason, confidence, duration) and shown on **System
Health → Model Routing Log** (admin); counts are also exported as the
Prometheus metric `model_routing_total`.

## Routers

| Router | Service / file | Primary | Fallback | Fallback fires when | Logged as |
|---|---|---|---|---|---|
| **Text extraction** | document-vendor-agent · `app/services/extraction_router.py` | pdfplumber (PDF text layer) · Docling (scanned PDFs) · PaddleOCR (images) — in a killable subprocess with a time limit | LayoutLMv3 second reading of the image (`_layoutlm_image_fallback`); if that fails, the primary's text is kept | an **image**'s OCR quality is below `document.extraction_fallback_confidence_threshold` (0.5) — reason `low_confidence`; or forced (below) — reason `forced`. A file that can't be read at all fails with a message for the uploader instead | `docling_text` / `docling_paddleocr` / `layoutlmv3_fallback` |
| **Clause extraction** | contract-risk-agent · `app/services/clause_router.py` | Legal-BERT fine-tuned on CUAD (`alex-apostolo/legal-bert-base-cuad`, `clause_model.py`) finds the renewal, notice and expiry passages; parsers turn them into values (FR-13) | regex rules (`clause_extraction.extract_clauses`) | the model isn't downloaded (`model_unavailable`), raised (`exception`), found fewer than 40 % of the three clauses (`low_confidence`, rule `contract.clause_extraction_fallback_threshold`), or forced (`forced`) | `legal_bert_primary` / `regex_fallback` |
| **Document classification** | document-vendor-agent · `app/services/classification.py` | ML classifier (TF-IDF + logistic regression, `ml/artifacts/classifier.joblib`, trained at image build — FR-29) when ≥ 0.6 confident | keyword classifier | the model is less than 60 % sure, or no model was kept (training keeps it only if it beats the keywords) | not routed through the log |

Not routers, listed for completeness:
- **LayoutLMv3 cross-check** (document-vendor-agent pipeline): a second
  opinion on every document when the model is downloaded; disagreement
  forces review. It never replaces the primary result.
- **Assistant / chatbot**: one local Ollama model, no fallback. It belongs
  to another team member and isn't covered here.

Measured, not assumed: Legal-BERT beats the rules on CUAD's 102 test
contracts (F1 0.85 / 0.80 / 0.91 vs 0.50 / 0.19 / 0.02) and reads every
value of our own templates — `docs/results/clauses.md`. For contracts we
generate, the notice period and end date we wrote stay authoritative; a
disagreement by the extractor is written to the contract's audit log
(`clause_mismatches`), not stored.

## Showing the fallback on demand (development only)

The business rule **`dev.force_model_fallback`** (Business Rules page,
category Risk & Compliance) lists routers whose primary is treated as
failed: `["extraction"]`, `["clauses"]` or both. It is honoured only when
`APP_ENV=development`; in production it is ignored.

Demo:
1. Business Rules → *Force Model Fallback (demo)* → set `["extraction"]`.
2. Upload any document (Documents → Upload).
3. System Health → Model Routing Log: the newest row is
   `layoutlmv3_fallback · layoutlmv3 · forced`, with its duration.
4. Set the rule back to `[]`.

For clauses, set `["clauses"]` and generate a contract (approve a request,
or Contracts → Generate): the log shows `regex_fallback · regex · forced`.

## Tests

- `services/document-vendor-agent/tests/test_rules_wiring.py::test_dev_force_model_fallback`
  — forced → `layoutlmv3_fallback` with reason `forced`; ignored with
  `APP_ENV=production`.
- `services/contract-risk-agent/tests/test_rules_wiring.py::test_dev_force_model_fallback`
  — the same for clauses.
- `services/contract-risk-agent/tests/test_clause_router.py` — model
  passages become values; no model / a model error → the rules; generated
  contracts keep their written terms.
- `…::test_document_extraction_fallback_confidence_threshold` and
  `…::test_contract_clause_extraction_fallback_threshold` — the natural
  (low-confidence) fallback follows its rule.
- `services/auth-service/tests/test_business_rules.py::test_force_model_fallback_accepts_only_known_routers`.
