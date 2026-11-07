# Selective automation: results

Generated 2026-11-06 12:47 by `services/document-vendor-agent/scripts/eval_selective.py` (commit `1306b21`, generator 1.0, seed 7). Every number below is in `selective.json`. Plan and hypotheses: [../RESEARCH_PAPER_PLAN.md](../RESEARCH_PAPER_PLAN.md).

## Setup

- **Data**: 3000 synthetic invoices from 100 vendors (procurement-world generator), each against a purchase order in a generated ledger; 29.8 % carry an injected business error. Visual conditions: pdf 1652, scan_clean 764, scan_heavy 238, scan_mild 346.
- **Reading**: the production code (pdfplumber for text PDFs, PaddleOCR for images, the ML classifier, the field extractor), run in-process, not through Kafka and the database.
- **Enterprise evidence**: computed against the generated vendor master, PO ledger and invoice history with the production rules (vendor matching, the ledger's three-way match, duplicate detection, GSTIN check digit, bank details vs master).
- **Correct** = vendor, total, currency and invoice number read right and no business error. 59.8 % of documents are correct; fields are read right on 84.1 %.
- **Splits**: 20 × vendor-grouped 50/25/25 train/calibration/test (test vendors never seen in training or calibration). Gates: Learn-then-Test, δ = 0.1.

## RQ1 / RQ2: coverage at a fixed document-level error budget

Coverage = share of test invoices accepted without review. Risk = share of accepted invoices that are wrong (target ≤ α). Violation = share of splits where risk > α (target ≤ δ = 10 %). Value at risk = rupee total of wrongly accepted invoices per test set (L = lakh).

### α = 1.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.2 % ± 1.2 % | 7.2 % (max 9.0 %) | 100.0 % |  |  | ₹158.3 L |
| B2 | 58.8 % ± 1.4 % | 13.2 % (max 18.0 %) | 100.0 % |  |  | ₹392.6 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.745 | 0.266 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.735 | 0.268 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.940 | 0.135 | ₹0.0 L |
| P-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.945 | 0.127 | ₹0.0 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.958 | 0.119 | ₹0.0 L |
| P+dup-hgb | 1.7 % ± 7.5 % | 0.0 % (max 0.9 %) | 0.0 % | 0.971 | 0.107 | ₹0.0 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +0.0 pp [+0.0, +0.0]
- P-B2 (logistic): -58.8 pp [-59.4, -58.2]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +0.0 pp [+0.0, +0.0]

### α = 2.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.2 % ± 1.2 % | 7.2 % (max 9.0 %) | 100.0 % |  |  | ₹158.3 L |
| B2 | 58.8 % ± 1.4 % | 13.2 % (max 18.0 %) | 100.0 % |  |  | ₹392.6 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.745 | 0.266 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.735 | 0.268 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.940 | 0.135 | ₹0.0 L |
| P-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.945 | 0.127 | ₹0.0 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 4.2 % ± 12.5 % | 0.2 % (max 2.6 %) | 10.0 % | 0.958 | 0.119 | ₹4.0 L |
| P+dup-hgb | 20.7 % ± 19.6 % | 0.7 % (max 3.6 %) | 15.0 % | 0.971 | 0.107 | ₹5.5 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +0.0 pp [+0.0, +0.0]
- P-B2 (logistic): -58.8 pp [-59.4, -58.2]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +4.2 pp [+0.0, +10.3]

### α = 5.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.2 % ± 1.2 % | 7.2 % (max 9.0 %) | 90.0 % |  |  | ₹158.3 L |
| B2 | 58.8 % ± 1.4 % | 13.2 % (max 18.0 %) | 100.0 % |  |  | ₹392.6 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.745 | 0.266 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.735 | 0.268 | ₹0.0 L |
| P-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.940 | 0.135 | ₹0.0 L |
| P-hgb | 2.6 % ± 6.6 % | 0.6 % (max 6.7 %) | 5.0 % | 0.945 | 0.127 | ₹6.7 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 8.1 % ± 19.4 % | 0.8 % (max 6.4 %) | 5.0 % | 0.958 | 0.119 | ₹16.0 L |
| P+dup-hgb | 39.9 % ± 16.8 % | 2.9 % (max 8.1 %) | 15.0 % | 0.971 | 0.107 | ₹52.4 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +0.0 pp [+0.0, +0.0]
- P-B1 (hgb): +2.6 pp [+0.0, +5.9]
- P-B2 (logistic): -58.8 pp [-59.4, -58.2]
- P-FC (logistic): +0.0 pp [+0.0, +0.0]
- P+dup - P (logistic, exploratory): +8.1 pp [+0.0, +16.5]

### α = 10.0 %

| System | Coverage (mean ± sd) | Risk (mean) | Violations | AUROC | AURC | Value at risk |
|---|---|---|---|---|---|---|
| B0 | 41.2 % ± 1.2 % | 7.2 % (max 9.0 %) | 0.0 % |  |  | ₹158.3 L |
| B2 | 58.8 % ± 1.4 % | 13.2 % (max 18.0 %) | 100.0 % |  |  | ₹392.6 L |
| B1-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.745 | 0.266 | ₹0.0 L |
| B1-hgb | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % | 0.735 | 0.268 | ₹0.0 L |
| P-logistic | 5.9 % ± 17.6 % | 0.8 % (max 8.0 %) | 0.0 % | 0.940 | 0.135 | ₹17.8 L |
| P-hgb | 16.6 % ± 25.9 % | 2.4 % (max 13.7 %) | 5.0 % | 0.945 | 0.127 | ₹92.8 L |
| FC-logistic | 0.0 % ± 0.0 % | 0.0 % (max 0.0 %) | 0.0 % |  |  | ₹0.0 L |
| P+dup-logistic | 15.0 % ± 26.1 % | 1.8 % (max 10.6 %) | 5.0 % | 0.958 | 0.119 | ₹50.4 L |
| P+dup-hgb | 57.3 % ± 13.4 % | 7.0 % (max 14.3 %) | 20.0 % | 0.971 | 0.107 | ₹244.4 L |

Paired differences in coverage over the splits (95 % bootstrap CI):

- P-B1 (logistic): +5.9 pp [+0.0, +14.8]
- P-B1 (hgb): +16.6 pp [+5.9, +28.6]
- P-B2 (logistic): -52.9 pp [-58.9, -44.2]
- P-FC (logistic): +5.9 pp [+0.0, +14.8]
- P+dup - P (logistic, exploratory): +9.2 pp [+0.5, +18.3]

B0 and B2 are fixed rules with no α: the same accept set is scored against every α.

## Ablation (P, logistic, α = 10.0 %)

| Without | Coverage | Risk | Violations | AUROC |
|---|---|---|---|---|
| vendor | 6.0 % | 0.8 % | 0.0 % | 0.939 |
| bank | 2.4 % | 0.8 % | 0.0 % | 0.898 |
| gstin | 2.8 % | 0.3 % | 0.0 % | 0.923 |
| po | 0.0 % | 0.0 % | 0.0 % | 0.833 |
| duplicate | 0.0 % | 0.0 % | 0.0 % | 0.921 |
| currency | 5.9 % | 0.8 % | 0.0 % | 0.939 |
| history | 6.0 % | 0.8 % | 0.0 % | 0.942 |

## RQ3: stale master data (α = 10.0 %)

A share of vendors have out-of-date bank details and no GSTIN on file, and the same share of POs is missing from the ledger.

| Stale share | P coverage | P risk | P violations | P AUROC | P+dup coverage | B1 coverage | P − B1 (95 % CI) |
|---|---|---|---|---|---|---|---|
| 0.0 % | 5.9 % | 0.8 % | 0.0 % | 0.940 | 15.0 % | 0.0 % | +5.9 pp [+0.0, +14.8] |
| 5.0 % | 2.4 % | 0.4 % | 0.0 % | 0.899 | 13.9 % | 0.0 % | +2.4 pp [+0.0, +7.2] |
| 10.0 % | 2.3 % | 1.2 % | 5.0 % | 0.881 | 7.4 % | 0.0 % | +2.3 pp [+0.0, +6.6] |
| 20.0 % | 0.0 % | 0.0 % | 0.0 % | 0.864 | 0.0 % | 0.0 % | +0.0 pp [+0.0, +0.0] |
| 40.0 % | 0.7 % | 0.5 % | 5.0 % | 0.838 | 0.5 % | 0.0 % | +0.7 pp [+0.0, +2.1] |

## Failure analysis (P+dup-hgb, α = 10.0 %, all splits)

| Injected error | Visual | Fields misread | Count |
|---|---|---|---|
| arithmetic | scan_clean | - | 112 |
| none | scan_mild | total | 76 |
| overbill_price | scan_clean | - | 74 |
| none | scan_clean | number | 63 |
| overbill_qty | scan_clean | - | 41 |
| duplicate | scan_clean | - | 38 |
| overbill_price | scan_mild | - | 28 |
| overbill_qty | pdf | - | 26 |
| duplicate | pdf | - | 25 |
| gstin_mismatch | scan_clean | - | 18 |
| overbill_price | pdf | - | 18 |
| bank_change | scan_mild | - | 17 |
| duplicate | scan_mild | - | 16 |
| arithmetic | scan_clean | number | 15 |
| arithmetic | scan_mild | - | 13 |

## Reading quality and cost

| Visual | Fields read right | Correct | Median read time |
|---|---|---|---|
| pdf | 100.0 % | 72.3 % | 0.01 s |
| scan_clean | 91.2 % | 63.0 % | 2.62 s |
| scan_heavy | 0.0 % | 0.0 % | 2.11 s |
| scan_mild | 50.0 % | 34.1 % | 2.40 s |

Enterprise evidence adds 1.0 ms per document (in memory).

## Limitations

- Synthetic documents and enterprise records: one generator, one family of layouts, injected errors at chosen rates. External validity on public invoices (RS-08) is not done.
- Reading runs in-process; the live pipeline's Docling path for scanned PDFs and the LayoutLMv3 cross-check are not part of the evidence.
- The reviewer is an oracle: history and ledger record the true values after review.
- Splits are by vendor; time drift and recalibration (RQ4, RS-10) are not studied.
