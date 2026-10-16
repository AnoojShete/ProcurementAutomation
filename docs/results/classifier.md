# Document classifier — keyword vs ML

Generated 2026-10-16T10:26:18+00:00 by `services/document-vendor-agent/ml/train_classifier.py`. 1260 documents from `ml/classification_corpus.py` (generated invoices / POs / quotes in clean, OCR-noise and missing-title variants, plus delivery notes, statements, receipts, letters, credit notes, GRNs as *other*), split 861 / 252 / 252; synthetic, so these numbers compare the classifiers, they don't measure real intake.

**Decision: the ML model is used** (keep the model only if the shipped router beats keywords on validation macro-F1 and on document kinds held out of training; the pipeline uses ML when ≥ 0.6 confident, else keywords).

## Test set

| Classifier | Accuracy | Macro-F1 | Clean | OCR noise | No title | Other |
|---|---|---|---|---|---|---|
| Keywords | 0.929 | 0.912 | 1.0 | 0.958 | 0.847 | 0.889 |
| ML alone | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| **Shipped** (ML ≥ 0.6, else keywords) | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

## Document kinds held out of training (C, other-4, other-6; trained on 870, tested on 390)

The in-template test above is easy — train and test share templates. This one trains without one layout and two kinds of *other* paperwork and tests on exactly those.

| Classifier | Accuracy | Macro-F1 | Clean | OCR noise | No title | Other |
|---|---|---|---|---|---|---|
| Keywords | 0.854 | 0.844 | 1.0 | 0.894 | 0.602 | 1.0 |
| ML alone | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| **Shipped** | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

## Per class (test)

| Class | Keywords P / R | Shipped P / R |
|---|---|---|
| invoice | 0.947 / 0.986 | 1.0 / 1.0 |
| po | 1.0 / 0.986 | 1.0 / 1.0 |
| quote | 1.0 / 0.833 | 1.0 / 1.0 |
| other | 0.696 / 0.889 | 1.0 / 1.0 |
