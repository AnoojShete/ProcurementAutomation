# Selective automation: results

Generated 2026-10-19 17:41 by `services/document-vendor-agent/scripts/eval_selective.py` (commit `60ee38e`, generator 1.0, seed 7). Every number below is in `selective.json`. Plan and hypotheses: [../RESEARCH_PAPER_PLAN.md](../RESEARCH_PAPER_PLAN.md).

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
| B0 | 41.4 % ± 1.2 % | 6.8 % (max 8.6 %) | 100.0 % |  |  | ₹154.6 L |
| B2 | 59.4 % ± 1.4 % | 12.9 % (max 18.9 %) | 100.0 % |  |  | ₹404.4 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.741 | 0.268 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.724 | 0.269 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.941 | 0.135 | ₹0.0 L |
| P-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.947 | 0.125 | ₹0.0 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.957 | 0.121 | ₹0.0 L |
| P+dup-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.972 | 0.106 | ₹0.0 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +0.0 pp [+0.0, +0.0]
- P-B2 (logistic): -59.4 pp [-60.0, -58.8]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +0.0 pp [+0.0, +0.0]

### α = 2.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.4 % ± 1.2 % | 6.8 % (max 8.6 %) | 100.0 % |  |  | ₹154.6 L |
| B2 | 59.4 % ± 1.4 % | 12.9 % (max 18.9 %) | 100.0 % |  |  | ₹404.4 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.741 | 0.268 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.724 | 0.269 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.941 | 0.135 | ₹0.0 L |
| P-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.947 | 0.125 | ₹0.0 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 2.3 % ± 10.0 % | 0.2 % (max 3.5 %) | 5.0 % | 0.957 | 0.121 | ₹2.4 L |
| P+dup-hgb | 16.6 % ± 18.6 % | 0.5 % (max 2.5 %) | 10.0 % | 0.972 | 0.106 | ₹4.3 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +0.0 pp [+0.0, +0.0]
- P-B2 (logistic): -59.4 pp [-60.0, -58.8]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +2.3 pp [+0.0, +6.9]

### α = 5.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.4 % ± 1.2 % | 6.8 % (max 8.6 %) | 90.0 % |  |  | ₹154.6 L |
| B2 | 59.4 % ± 1.4 % | 12.9 % (max 18.9 %) | 100.0 % |  |  | ₹404.4 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.741 | 0.268 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.724 | 0.269 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.941 | 0.135 | ₹0.0 L |
| P-hgb | 1.8 % ± 6.0 % | 0.4 % (max 4.0 %) | 0.0 % | 0.947 | 0.125 | ₹3.2 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 8.0 % ± 19.0 % | 0.6 % (max 5.4 %) | 5.0 % | 0.957 | 0.121 | ₹9.5 L |
| P+dup-hgb | 42.2 % ± 15.0 % | 2.6 % (max 6.1 %) | 20.0 % | 0.972 | 0.106 | ₹62.3 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +1.8 pp [+0.0, +4.8]
- P-B2 (logistic): -59.4 pp [-60.0, -58.8]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +8.0 pp [+0.0, +16.6]

### α = 10.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.4 % ± 1.2 % | 6.8 % (max 8.6 %) | 0.0 % |  |  | ₹154.6 L |
| B2 | 59.4 % ± 1.4 % | 12.9 % (max 18.9 %) | 95.0 % |  |  | ₹404.4 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.741 | 0.268 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.724 | 0.269 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.941 | 0.135 | ₹0.0 L |
| P-hgb | 20.1 % ± 27.2 % | 3.2 % (max 10.6 %) | 10.0 % | 0.947 | 0.125 | ₹86.7 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 9.4 % ± 22.5 % | 1.2 % (max 8.9 %) | 0.0 % | 0.957 | 0.121 | ₹33.9 L |
| P+dup-hgb | 51.1 % ± 21.8 % | 5.9 % (max 12.1 %) | 10.0 % | 0.972 | 0.106 | ₹187.8 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +20.1 pp [+8.7, +32.4]
- P-B2 (logistic): -59.4 pp [-60.0, -58.8]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +9.4 pp [+0.0, +19.0]

B0 and B2 are fixed rules with no α: the same accept set is scored against every α.

## Ablation (P, logistic, α = 10.0 %)

| Without | Coverage | Risk | Violations | AUROC |
|---|---|---|---|---|
| vendor | 0.0 % | 0.0 % | 0.0 % | 0.940 |
| bank | 0.0 % | 0.0 % | 0.0 % | 0.900 |
| gstin | 0.2 % | 1.2 % | 5.0 % | 0.924 |
| po | 0.0 % | 0.0 % | 0.0 % | 0.833 |
| duplicate | 0.0 % | 0.0 % | 0.0 % | 0.919 |
| currency | 0.0 % | 0.0 % | 0.0 % | 0.941 |
| history | 6.2 % | 0.8 % | 0.0 % | 0.942 |

## RQ3: stale master data (α = 10.0 %)

A share of vendors have out-of-date bank details and no GSTIN on file, and the same share of POs is missing from the ledger.

| Stale share | P coverage | P risk | P violations | P AUROC | P+dup coverage | B1 coverage | P − B1 (95 % CI) |
|---|---|---|---|---|---|---|---|
| 0.0 % | 0.0 % | 0.0 % | 0.0 % | 0.941 | 9.4 % | 0.0 % | +0.0 pp [+0.0, +0.0] |
| 5.0 % | 0.0 % | 0.0 % | 0.0 % | 0.901 | 13.8 % | 0.0 % | +0.0 pp [+0.0, +0.0] |
| 10.0 % | 2.1 % | 2.0 % | 5.0 % | 0.883 | 6.9 % | 0.0 % | +2.1 pp [+0.0, +6.2] |
| 20.0 % | 0.0 % | 0.0 % | 0.0 % | 0.866 | 0.0 % | 0.0 % | +0.0 pp [+0.0, +0.0] |
| 40.0 % | 0.0 % | 0.0 % | 0.0 % | 0.841 | 0.0 % | 0.0 % | +0.0 pp [+0.0, +0.0] |

## Failure analysis (P+dup-hgb, α = 10.0 %, all splits)

| Injected error | Visual | Fields misread | Count |
|---|---|---|---|
| arithmetic | scan_clean | - | 95 |
| overbill_price | scan_clean | - | 62 |
| none | scan_mild | total | 53 |
| none | scan_clean | number | 44 |
| overbill_qty | scan_clean | - | 32 |
| overbill_price | scan_mild | - | 29 |
| duplicate | scan_clean | - | 25 |
| bank_change | scan_mild | - | 23 |
| overbill_qty | pdf | - | 21 |
| overbill_price | pdf | - | 15 |
| gstin_mismatch | scan_clean | - | 15 |
| arithmetic | scan_clean | number | 14 |
| none | scan_mild | currency | 13 |
| arithmetic | scan_mild | - | 11 |
| none | scan_mild | number | 11 |

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
