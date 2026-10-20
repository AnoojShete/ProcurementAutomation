# Obligation extraction: Legal-BERT vs rules (feature expansion Phase 2)

Generated 2026-10-20 by `ml/evaluate_obligation_model.py`. Model: [alex-apostolo/legal-bert-base-cuad](https://huggingface.co/alex-apostolo/legal-bert-base-cuad), asked CUAD's own question for each category.

## CUAD test split — 102 lawyer-annotated contracts

Correct = the returned passage (model) or the rule's match overlaps an annotated span.

| Obligation | CUAD category | Contracts with it | Rules P / R / F1 | Model P / R / F1 | Primary |
|---|---|---|---|---|---|
| Licence limits (users, transfer, territory) | License Grant | 50 | 0.93 / 0.26 / **0.41** | 1.00 / 0.28 / **0.44** | model |
| Audit rights | Audit Rights | 38 | 0.77 / 0.26 / **0.39** | 0.86 / 0.32 / **0.46** | rules |
| Warranty duration | Warranty Duration | 10 | 1.00 / 0.30 / **0.46** | 1.00 / 0.20 / **0.33** | rules |
| Termination for convenience | Termination For Convenience | 29 | 0.26 / 0.24 / **0.25** | 0.86 / 0.66 / **0.74** | model |
| Minimum commitment | Minimum Commitment | 32 | 0.25 / 0.03 / **0.06** | 1.00 / 0.06 / **0.12** | rules |
| After termination (data return, transition) | Post-Termination Services | 29 | 0.11 / 0.03 / **0.05** | 1.00 / 0.03 / **0.07** | rules |
| Liability cap | Cap On Liability | 44 | 0.69 / 0.25 / **0.37** | 1.00 / 0.55 / **0.71** | rules |
| Insurance | Insurance | 32 | 0.80 / 0.75 / **0.77** | 1.00 / 0.50 / **0.67** | rules |

Model time per contract (8 questions, CPU): median 52.0 s.

## Our templates — values the app stores

| Obligation | Rules exact | Model exact |
|---|---|---|
| SLA uptime and service credits | 100% |  |
| Licence limits (users, transfer, territory) | 100% | 100% |
| Price increase cap | 100% |  |
| Audit rights | 100% | 0% |
| Warranty duration | 100% | 100% |
| Termination for convenience | 100% | 100% |
| Minimum commitment | 100% | 0% |
| After termination (data return, transition) | 100% | 0% |
| Data protection and breach notice | 100% |  |
| Liability cap | 100% | 0% |
| Insurance | 100% | 100% |

Model misses (first few): saas_subscription audit_rights: expected {'days': 30, 'frequency': 'annual'}, got None; saas_subscription minimum_commitment: expected {'seats': 6, 'months': 12}, got None; saas_subscription post_termination: expected {'days': 30}, got None; saas_subscription liability_cap: expected {'fees_months': 12}, got None; saas_subscription audit_rights: expected {'days': 30, 'frequency': 'annual'}, got None; saas_subscription minimum_commitment: expected {'seats': 20, 'months': 12}, got None; saas_subscription post_termination: expected {'days': 30}, got None; saas_subscription liability_cap: expected {'fees_months': 12}, got None

## FR-13 clause fields, templates with the new clauses

Rules: {'renewal_type': 1.0, 'notice_period_days': 1.0, 'contract_end_date': 1.0} · Model: {'renewal_type': 1.0, 'notice_period_days': 1.0, 'contract_end_date': 1.0}

## Decision

A type uses the model only if its CUAD F1 beats the rules and it reads every template value right.

| Obligation | Primary | Why |
|---|---|---|
| SLA uptime and service credits | rules | Not a CUAD category: rules only. |
| Licence limits (users, transfer, territory) | model | model F1 higher and templates exact |
| Price increase cap | rules | CUAD's test split has no Price Restrictions examples, so it can't be evaluated: rules only. |
| Audit rights | rules | model misses template values |
| Warranty duration | rules | model F1 not higher |
| Termination for convenience | model | model F1 higher and templates exact |
| Minimum commitment | rules | model misses template values |
| After termination (data return, transition) | rules | model misses template values |
| Data protection and breach notice | rules | CUAD has no data-protection category: rules only. |
| Liability cap | rules | model misses template values |
| Insurance | rules | model F1 not higher |

Rules for SLA uptime and data protection are checked on our templates only (no CUAD category); Price Restrictions has no examples in CUAD's test split. Every extracted obligation is confirmed by a person before reminders start, so a wrong extraction costs a correction, not a missed obligation.
