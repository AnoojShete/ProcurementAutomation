# Clause extraction: Legal-BERT vs rules (FR-13)

Generated 2026-10-16 by `ml/evaluate_clause_model.py`. Model: [alex-apostolo/legal-bert-base-cuad](https://huggingface.co/alex-apostolo/legal-bert-base-cuad) (Legal-BERT fine-tuned on CUAD's train split).

## CUAD test split — 102 real contracts, lawyer-annotated

A clause is *found* correctly when the passage returned (model) or the text matched (rules) overlaps a span the annotators highlighted.

| Clause | Contracts with it | Rules P / R / F1 | Model P / R / F1 |
|---|---|---|---|
| Renewal term | 26 | 0.90 / 0.35 / **0.50** | 0.95 / 0.77 / **0.85** |
| Notice period to terminate renewal | 16 | 0.20 / 0.19 / **0.19** | 0.86 / 0.75 / **0.80** |
| Expiration date | 78 | 0.08 / 0.01 / **0.02** | 0.96 / 0.87 / **0.91** |

Model time on CPU: median 17 s per contract (three questions; contracts median 25,922 characters).

## Our contract templates — 60 contracts

Exact values the app stores.

| Value | Rules | Model |
|---|---|---|
| Renewal term | 100% | 100% |
| Notice period to terminate renewal | 100% | 100% |
| Expiration date | 100% | 100% |

## Decision

Rule, fixed before running: the model is the primary when its F1 beats the rules on at least two of the three CUAD clauses **and** it gets every template value right.

- Model beats rules on: Renewal term, Notice period to terminate renewal, Expiration date
- Every template value right: yes
- **Primary: model**; the other is the fallback (`clause_router.py`).

## Limits

- CUAD is US commercial contracts; ours are short generated Indian procurement contracts.
- "Found" is scored by overlap with any highlighted span, not exact boundaries.
- Expiration dates in CUAD are mostly relative ("five years from the Effective Date"); the model finds the passage but a date is only stored when the passage states one.
- 102 contracts, and only 16 have a notice-to-terminate-renewal clause — small numbers.
