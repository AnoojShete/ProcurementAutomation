# Report audit summary (17–18 Oct 2026)

Audit of the teammate's draft (`Agentic_AI_Procurement_LaTeX.pdf`) against the code on branch
`anjali`, the running stack, and `docs/results/`. Output: this folder and
`Agentic_AI_Procurement_Report.pdf` (71 pages).

## Source used

The newest draft existed only as the PDF. The LaTeX folder in the repo
(`Agentic_AI_Proc_Soln_Rpt/`, identical to the copy in Downloads) is an older revision: different
abstract, template appendices, PNG figures. So the template and front matter were taken from that
folder, and the text from the PDF. The original folder and PDF are left unchanged.

## Corrections of fact (draft → code / evidence)

| Draft said | Actually | Evidence |
|---|---|---|
| 134 unit tests, 132 passed; 12-step e2e | 823 service tests passed (17 Oct); shared suite 156 passed, 4 skipped; `make e2e` 17/17; four more e2e suites | re-run for this report, `evidence/test_runs.txt` |
| Classification is a weighted keyword classifier | TF-IDF + logistic regression (4 classes incl. *other*), keywords only below 0.6 confidence | `ml/train_classifier.py`, `docs/results/classifier.md` |
| Docling for every PDF, Tesseract for images, PaddleOCR rejected | pdfplumber for text PDFs, Docling for scanned PDFs, PaddleOCR for images in an isolated subprocess; Tesseract not used | `services/ocr.py` |
| LayoutLMv3 not implemented | Optional cross-check + low-quality image fallback | `layoutlm_crosscheck.py`, `docs/model-routing.md` |
| Clause extraction is rule-based | Legal-BERT (CUAD) primary, regex fallback; F1 0.85/0.80/0.91 vs 0.50/0.19/0.02 | `clause_router.py`, `docs/results/clauses.md` |
| Licence reclaim by a 30 % utilisation threshold | Isolation Forest + SHAP, thresholds 0.39/0.34, 7-day grace period | `docs/results/licence-anomaly.md`, migration 0012 |
| Sanctions screening, GSTIN/IFSC checks out of scope | Sanctions screening (OpenSanctions) and GSTIN check digit + IFSC lookup at onboarding are built | `sanctions.py`, `vendor_onboarding.py` |
| bcrypt | argon2id (bcrypt hashes only verified and re-hashed) | `auth-service/app/security.py` |
| Thresholds in configuration files | 47 business rules edited at run time (37 enforced) | `business_rules` table, `docs/business-rules.md` |
| Duplicate check: amount 1 %, 5 days | 2 %, 7 days, invoice number ≥ 85 % (live rules) | `business_rules` table |
| `contract.signed` marks the request fulfilled | Signed → `ordered`; "mark received" → `fulfilled` | `shared/lifecycle.py` |
| E-signature returns a simulated provider reference | Built-in in-app signing with SHA-256 seal and risk acknowledgement; HMAC webhook kept for tests | `contract_service.py`, `webhook_service.py` |
| Correlation-ID tracing is future work | Built (nginx ID, Loki/Grafana) | `docs/readmeforme.md` |
| No mention of the outbox, DLQ, approval authority / separation of duties, invoice ledger, e-mail and drop-folder intake, assistant | All built; added where relevant | code + docs |
| SLA timeout escalates | Escalates to next approver; a timeout at the last level **rejects** | `approval_workflow.py` |

Also removed: "budgets" from objectives (budget rules are seeded but not built), FinBERT as used
(not built), and the wireframe placeholder figure (no wireframes exist; real screenshots used).

## Added

- Agent definition (§2.2.8), so "agentic" is not over-claimed: only the assistant uses an LLM.
- Chapter 5 (was empty): 6 real screenshots, 3 verbatim code listings + the confidence formula,
  unit / e2e / black-box testing (black-box cases run live through the gateway), and an evaluation
  section with 4 tables and 3 charts built from `docs/results/`, with the synthetic-data caveats.
- Chapter 6 (was template text): conclusion, honest limitations, future scope.
- Appendix A timeline from the git history (Nov/Dec marked planned); Appendices B–D filled.
- New figures: purchase-request state machine; deployment block diagram distinct from Fig. 3.1.
- References: 6 added (Richardson outbox, Yurdakul PSI, scikit-learn, Argon2,
  OpenSanctions, Legal-BERT-CUAD checkpoint); all 19 cited, numbered by first citation.
  Yurdakul and the PaddleOCR 3.0 arXiv ID were checked online.

## Visuals

Every diagram was redrawn in TikZ in one style (one colour per agent, defined once in `main.tex`):
architecture, pipeline, event flow, use cases, lifecycle model, DFD 0/1, sequence, activity, state
machine, ER (columns checked against the live schema), block diagram, timeline. The blurry or
photographed raster diagrams in the draft are gone.

## Checks done

- PDF compiles; final log has no undefined references/citations; 3 overfull boxes, all < 2.5 pt.
- Every page rendered and inspected; every figure/table/listing label is referenced in the text.

## Still open — needs the team

1. Group / Team No. (Appendix C) and project competitions (Appendix D).
2. Appendix C self-scores were kept as the teammate set them; with the new evaluation evidence,
   "Data analysis and experimentation" (2) may deserve revisiting — team's call.
3. Cost figures (cloud hosting, e-mail) are the draft's indicative estimates, not quotations.
4. Screenshots and `docs/results/` numbers are from 16 Oct; e2e suites other than `make e2e` were
   not re-run (dated 16–17 Oct in Table 5.2).
5. The research-paper title in Appendix D is provisional (from `docs/RESEARCH_PAPER_PLAN.md`).
6. pdfLaTeX (Overleaf's default) and Tectonic both build it (24 Oct). Diagrams are pre-built PDFs in `figures/diagrams/` (TikZ source next to each; rebuild with `build.sh`) so the report compiles within Overleaf's time limit. Red TO-DO marks: Appendix C scores and team number, Appendix D competitions, the GST e2e result.
