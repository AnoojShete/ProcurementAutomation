# Testing and results

## Automated tests (23 Oct 2026)

| Suite | Command | Result |
|---|---|---|
| Service tests (pytest, inside each image) | `./scripts/test-service.sh all` | **1,276 passed**: contract-risk 322, approval-inventory 275, document-vendor 373, notification 125, auth 115, chatbot 66 |
| Root tests (shared code, config: Kafka ACLs, nginx, lifecycle, docs) | `./scripts/test-root.sh` | 165 + 14 passed, 4 skipped |
| Whole lifecycle through the gateway | `python tests/e2e/invoice_lifecycle.py` | 71 / 71 |
| Frontend types | `cd frontend && npm run typecheck` | clean |

Other end-to-end suites: `auth_flows.py`, `budget_flow.py`,
`obligation_flow.py`, `sourcing_flow.py`, `risk_flow.py`, `gst_flow.py`,
`document_pipeline.py`, `chatbot_eval.py`, `demo_scenarios.py`. Install their
dependencies once with `pip install -r tests/e2e/requirements.txt`, and wait a
minute between suites (gateway rate limits).

## How fixes are checked

A fix comes with a test, and the test is shown to fail when the fix is
reverted. For example, the final-checklist work added:

| Behaviour | Test |
|---|---|
| A blank scan dropped in `input/` ends in `failed/` with the pipeline's reason | `test_drop_folder.py::TestSettle` |
| An edited template is rendered in a sandbox; a broken edit falls back to the built-in | `test_template_store.py` |
| An SLA escalation asks the next level, not the level that missed it | `test_expansion_notifications.py` |
| A manager's approval of a two-level request asks finance next and generates no contract yet | `test_expansion_notifications.py`, `test_contract_documents.py::TestContractOnlyAfterFinalApproval` |
| The signer's email has a signing link | `test_templates.py` |

## Model results

| Model | Result | Report |
|---|---|---|
| Document classifier | Macro-F1 1.00 on held-out document kinds (keywords 0.84) | `docs/results/classifier.md` |
| Field extraction | PDFs 100 %; images ~49 % fully right | `docs/results/extraction.md` |
| Clause extraction (Legal-BERT, CUAD) | F1 0.85 / 0.80 / 0.91 | `docs/results/clauses.md` |
| Licence anomalies | ROC-AUC 0.954 | `docs/results/licence-anomaly.md` |
| Assistant | 20 / 20 expected answers | `docs/results/chatbot-eval.md` |
| Selective automation (research) | Coverage at a guaranteed error rate | `docs/results/selective.md` |

All data is synthetic; see `data/README.md`.
