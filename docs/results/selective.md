# Selective automation: results

Generated 2026-10-19 18:30 by `services/document-vendor-agent/scripts/eval_selective.py` (commit `a091d11`, generator 1.0, seed 7). Every number below is in `selective.json`. Plan and hypotheses: [../RESEARCH_PAPER_PLAN.md](../RESEARCH_PAPER_PLAN.md).

## Setup

- **Data**: 3000 synthetic invoices from 100 vendors (procurement-world generator), each against a purchase order in a generated ledger; 29.8 % carry an injected business error. Visual conditions: pdf 1652, scan_clean 764, scan_heavy 238, scan_mild 346.
- **Reading**: the production code (pdfplumber for text PDFs, PaddleOCR for images, the ML classifier, the field extractor), run in-process, not through Kafka and the database.
- **Enterprise evidence**: computed against the generated vendor master, PO ledger and invoice history with the production rules (vendor matching, the ledger's three-way match, duplicate detection, GSTIN check digit, bank details vs master).
- **Correct** = vendor, total, currency and invoice number read right and no business error. 59.9 % of documents are correct; fields are read right on 84.3 %.
- **Splits**: 20 × vendor-grouped 50/25/25 train/calibration/test (test vendors never seen in training or calibration). Gates: Learn-then-Test, δ = 0.1.

## RQ1 / RQ2: coverage at a fixed document-level error budget

Coverage = share of test invoices accepted without review. Risk = share of accepted invoices that are wrong (target ≤ α). Violation = share of splits where risk > α (target ≤ δ = 10 %). Value at risk = rupee total of wrongly accepted invoices per test set (L = lakh).

### α = 1.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.2 % ± 1.2 % | 6.8 % (max 8.6 %) | 100.0 % |  |  | ₹154.6 L |
| B2 | 58.9 % ± 1.4 % | 12.8 % (max 18.8 %) | 100.0 % |  |  | ₹400.7 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.741 | 0.268 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.724 | 0.269 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.938 | 0.137 | ₹0.0 L |
| P-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.947 | 0.124 | ₹0.0 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.954 | 0.123 | ₹0.0 L |
| P+dup-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.971 | 0.106 | ₹0.0 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +0.0 pp [+0.0, +0.0]
- P-B2 (logistic): -58.9 pp [-59.5, -58.2]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +0.0 pp [+0.0, +0.0]

### α = 2.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.2 % ± 1.2 % | 6.8 % (max 8.6 %) | 100.0 % |  |  | ₹154.6 L |
| B2 | 58.9 % ± 1.4 % | 12.8 % (max 18.8 %) | 100.0 % |  |  | ₹400.7 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.741 | 0.268 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.724 | 0.269 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.938 | 0.137 | ₹0.0 L |
| P-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.947 | 0.124 | ₹0.0 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 2.0 % ± 8.9 % | 0.1 % (max 3.0 %) | 5.0 % | 0.954 | 0.123 | ₹2.3 L |
| P+dup-hgb | 12.1 % ± 18.5 % | 0.3 % (max 2.3 %) | 5.0 % | 0.971 | 0.106 | ₹3.0 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +0.0 pp [+0.0, +0.0]
- P-B2 (logistic): -58.9 pp [-59.5, -58.2]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +2.0 pp [+0.0, +6.1]

### α = 5.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.2 % ± 1.2 % | 6.8 % (max 8.6 %) | 90.0 % |  |  | ₹154.6 L |
| B2 | 58.9 % ± 1.4 % | 12.8 % (max 18.8 %) | 100.0 % |  |  | ₹400.7 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.741 | 0.268 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.724 | 0.269 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.938 | 0.137 | ₹0.0 L |
| P-hgb | 1.7 % ± 7.4 % | 0.2 % (max 4.1 %) | 0.0 % | 0.947 | 0.124 | ₹3.5 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 7.9 % ± 18.8 % | 0.6 % (max 5.6 %) | 5.0 % | 0.954 | 0.123 | ₹9.7 L |
| P+dup-hgb | 35.4 % ± 19.5 % | 2.3 % (max 7.9 %) | 10.0 % | 0.971 | 0.106 | ₹53.7 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +1.7 pp [+0.0, +5.1]
- P-B2 (logistic): -58.9 pp [-59.5, -58.2]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +7.9 pp [+0.0, +16.3]

### α = 10.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.2 % ± 1.2 % | 6.8 % (max 8.6 %) | 0.0 % |  |  | ₹154.6 L |
| B2 | 58.9 % ± 1.4 % | 12.8 % (max 18.8 %) | 95.0 % |  |  | ₹400.7 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.741 | 0.268 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.724 | 0.269 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.938 | 0.137 | ₹0.0 L |
| P-hgb | 19.5 % ± 26.6 % | 2.7 % (max 10.1 %) | 5.0 % | 0.947 | 0.124 | ₹78.7 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 15.2 % ± 26.3 % | 1.8 % (max 9.4 %) | 0.0 % | 0.954 | 0.123 | ₹53.0 L |
| P+dup-hgb | 51.0 % ± 21.7 % | 6.1 % (max 13.4 %) | 20.0 % | 0.971 | 0.106 | ₹208.7 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +19.5 pp [+8.4, +31.6]
- P-B2 (logistic): -58.9 pp [-59.5, -58.2]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +15.2 pp [+3.2, +27.5]

B0 and B2 are fixed rules with no α: the same accept set is scored against every α.

## Ablation (P, logistic, α = 10.0 %)

| Without | Coverage | Risk | Violations | AUROC |
|---|---|---|---|---|
| vendor | 0.0 % | 0.0 % | 0.0 % | 0.937 |
| bank | 0.0 % | 0.0 % | 0.0 % | 0.897 |
| gstin | 2.6 % | 0.3 % | 0.0 % | 0.921 |
| po | 0.0 % | 0.0 % | 0.0 % | 0.831 |
| duplicate | 0.0 % | 0.0 % | 0.0 % | 0.919 |
| currency | 0.0 % | 0.0 % | 0.0 % | 0.938 |
| history | 6.0 % | 0.8 % | 0.0 % | 0.940 |

## RQ3: stale master data (α = 10.0 %)

A share of vendors have out-of-date bank details and no GSTIN on file, and the same share of POs is missing from the ledger.

| Stale share | P coverage | P risk | P violations | P AUROC | P+dup coverage | B1 coverage | P − B1 (95 % CI) |
|---|---|---|---|---|---|---|---|
| 0.0 % | 0.0 % | 0.0 % | 0.0 % | 0.938 | 15.2 % | 0.0 % | +0.0 pp [+0.0, +0.0] |
| 5.0 % | 0.0 % | 0.0 % | 0.0 % | 0.898 | 11.0 % | 0.0 % | +0.0 pp [+0.0, +0.0] |
| 10.0 % | 2.1 % | 1.6 % | 5.0 % | 0.880 | 5.0 % | 0.0 % | +2.1 pp [+0.0, +6.2] |
| 20.0 % | 0.0 % | 0.0 % | 0.0 % | 0.863 | 0.0 % | 0.0 % | +0.0 pp [+0.0, +0.0] |
| 40.0 % | 0.0 % | 0.0 % | 0.0 % | 0.838 | 0.4 % | 0.0 % | +0.0 pp [+0.0, +0.0] |

## Failure analysis (P+dup-hgb, α = 10.0 %, all splits)

| Injected error | Visual | Fields misread | Count |
|---|---|---|---|
| arithmetic | scan_clean | - | 99 |
| overbill_price | scan_clean | - | 62 |
| none | scan_mild | total | 54 |
| none | scan_clean | number | 43 |
| overbill_qty | scan_clean | - | 37 |
| duplicate | scan_clean | - | 36 |
| overbill_price | scan_mild | - | 35 |
| bank_change | scan_mild | - | 26 |
| duplicate | pdf | - | 24 |
| overbill_qty | pdf | - | 21 |
| gstin_mismatch | scan_clean | - | 18 |
| overbill_price | pdf | - | 16 |
| arithmetic | scan_clean | number | 14 |
| none | scan_mild | number | 12 |
| duplicate | scan_mild | - | 11 |

## Reading quality and cost

| Visual | Fields read right | Correct | Median read time |
|---|---|---|---|
| pdf | 100.0 % | 72.3 % | 0.01 s |
| scan_clean | 91.2 % | 63.0 % | 2.69 s |
| scan_heavy | 0.0 % | 0.0 % | 2.17 s |
| scan_mild | 51.7 % | 34.7 % | 2.47 s |

Enterprise evidence adds 1.0 ms per document (in memory).

## Limitations

- Synthetic documents and enterprise records: one generator, one family of layouts, injected errors at chosen rates. External validity on public invoices (RS-08) is not done.
- Reading runs in-process; the live pipeline's Docling path for scanned PDFs and the LayoutLMv3 cross-check are not part of the evidence.
- The reviewer is an oracle: history and ledger record the true values after review.
- Splits are by vendor; time drift and recalibration (RQ4, RS-10) are not studied.
