# Proposed system and technology stack

## Proposed system

Five agents, each owning one part of procurement, cooperate through events:

| Agent | Responsibility |
|---|---|
| **Document & Vendor** | Takes documents in (upload, email, drop folder), scans for viruses, reads and classifies them, extracts and validates fields, matches vendors |
| **Approval & Inventory** | Purchase requests, approval workflows by spend tier, budgets, inventory, licences, RFQs, invoice matching |
| **Contract & Risk** | Generates contracts, built-in e-signature, renewals and obligations, vendor risk scorecard and clearance |
| **Notification** | Emails and the in-app feed, from templates editable in the Control Panel |
| **Auth** | Accounts, roles, and the business rules admins change live |

A sixth service, the **assistant** (chatbot, owned by Anooj), answers
questions about requests, contracts and vendors from the platform's own data.

Design principles:

- **One home page per item** (request, contract, document, vendor, licence);
  lists and the Control Panel link to it.
- **Events, not direct calls**: a change and its event commit together
  (transactional outbox); consumers retry and park failures in a dead-letter
  queue.
- **Humans where it matters**: low confidence, high value or high risk goes to
  a person; everything else flows.
- **Rules, not code**: thresholds, SLAs and tiers are business rules an admin
  edits.

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS ("Ledger" design system) |
| Gateway | nginx (only public port, :8080) |
| Services | Python 3.11, FastAPI, SQLAlchemy (async), Pydantic |
| Messaging | Kafka API on Redpanda, SASL/SCRAM login and ACLs per service |
| Workflows | Temporal (approvals, renewals) |
| Database | PostgreSQL 16 with pgvector (one shared database) |
| Files | MinIO (S3 API) |
| Cache / locks | Redis 7 |
| Virus scan | ClamAV |
| Email | Mailpit in development, any SMTP server in production |
| Document AI | pdfplumber, Docling, PaddleOCR, LayoutLMv3 cross-check, TF-IDF + logistic regression classifier |
| Contract AI | Legal-BERT fine-tuned on CUAD (clauses, obligations), regex fallback |
| Licence AI | IsolationForest with SHAP explanations |
| Vendor risk | Deterministic 100-point scorecard, sanctions screening (OpenSanctions) |
| Assistant | Ollama (llama3.2, nomic-embed-text), retrieval over pgvector |
| Observability | Prometheus, Grafana, Loki, Promtail, Temporal UI, MLflow |
| Packaging | Docker Compose (22 containers), `run.sh` |
