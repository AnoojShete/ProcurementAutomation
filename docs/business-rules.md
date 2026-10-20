# Business rules

Every rule on the Business Rules page (`/app/business-rules`, admin): what it changes, where the code reads it, and the test that proves changing it changes behaviour. Generated from the live rules table on 16 Oct 2026 (47 rules; 52 after the Phase 1 budget rules of 20 Oct; 55 after the Phase 2 obligation rules) and kept in step by `tests/test_business_rules_registry.py`, which fails if a rule is missing here, if code reads a rule that isn't seeded, or if an enforced rule has no behaviour test.

Rules are read through `shared/rules_engine.get_rule` (cached 5 min, refreshed on `business_rule.updated`); each read has a fallback used when auth-service is unreachable. Tests: `services/<service>/tests/test_rules_wiring.py::test_<rule key with _>` — each sets the rule to two values and checks the behaviour differs.

**Enforced: 47** · **Not enforced: 8** (listed at the end — editing them has no effect until the feature exists).

| Rule | Default | What it changes | Read in | Test |
|---|---|---|---|---|
| `approval.email_action_allowed_high_risk_vendor` | `false` | Allow email approval when the vendor's risk band is High | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_email_action_allowed_high_risk_vendor` |
| `approval.email_action_allowed_over_budget` | `false` | Allow email approval of requests that exceed the budget | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_email_action_allowed_over_budget` |
| `approval.email_action_enabled` | `true` | Allow approvers to approve or reject from a single-use email link | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_email_action_enabled` |
| `approval.email_action_max_amount` | `50000` | Requests above this amount must be decided in the app, not from email | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_email_action_max_amount` |
| `approval.email_token_ttl_hours` | `48` | How long an approval link in an email stays valid (never past the SLA deadline) | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_email_token_ttl_hours` |
| `approval.high_risk_vendor_requires_finance` | `false` | Purchases from a High-risk vendor get a finance approval step | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_approval_high_risk_vendor_requires_finance` |
| `approval.reminder_sla_percents` | `[50, 80]` | Remind the approver when this much of the approval SLA has passed | approval-inventory-agent: workflows/activities.py | `approval-inventory-agent` · `test_approval_reminder_sla_percents` |
| `approval.sla_escalation_hours` | `48` | Hours before an unapproved request escalates | approval-inventory-agent: approval_service.py, approval-inventory-agent: workflows/activities.py | `approval-inventory-agent` · `test_approval_sla_escalation_hours` |
| `approval.spend_tiers` | `[{"tier_name": "auto", "max_amount": …` | Approval tiers with amount limits and required roles | approval-inventory-agent: approval_service.py | `approval-inventory-agent` · `test_approval_spend_tiers` |
| `budget.block_when_over` | `false` | Refuse an over-budget request (422 over_budget) instead of adding a finance step | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_block_when_over` |
| `budget.fiscal_period_type` | `"quarterly"` | Budgets are per quarter or per fiscal year; decides which budget a request draws on | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_fiscal_period_type` |
| `budget.fiscal_year_start_month` | `4` | Month the fiscal year starts (April); sets the quarter a request falls in | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_fiscal_year_start_month` |
| `budget.no_budget_policy` | `"allow"` | Request with no budget for its department, category and period: allow, add a finance step, or refuse | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_no_budget_policy` |
| `budget.over_budget_requires_finance_approval` | `true` | A request that would exceed its budget gets a finance approval step | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_over_budget_requires_finance_approval` |
| `budget.warning_threshold_pct` | `0.8` | A request that takes its budget past this share is marked *warning* and publishes budget.threshold_crossed | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_warning_threshold_pct` |
| `contract.auto_send_scope` | `"all"` | Which approved requests get their contract sent for signature automatically: "all" or "drop_folder" (only quotes dropped in the inbox folder) | contract-risk-agent: contract_service.py | `contract-risk-agent` · `test_contract_auto_send_scope` |
| `contract.clause_extraction_fallback_threshold` | `0.4` | Confidence threshold to fallback during contract clause extraction | contract-risk-agent: clause_router.py | `contract-risk-agent` · `test_contract_clause_extraction_fallback_threshold` |
| `contract.obligation_model_min_confidence` | `0.5` | Legal-BERT passages scoring below this are not proposed as obligations (only for types where the model beat the rules on CUAD) | contract-risk-agent: obligation_service.py | `contract-risk-agent` · `test_contract_obligation_model_min_confidence` |
| `contract.obligation_reminder_days` | `[30, 7]` | Days before a confirmed obligation's due date when its owner is reminded (contract.obligation.due) | contract-risk-agent: obligation_service.py | `contract-risk-agent` · `test_contract_obligation_reminder_days` |
| `contract.signature_reminder_days` | `3` | Remind the signer when a contract has waited this many days for signature | contract-risk-agent: reminder_sweep.py | `contract-risk-agent` · `test_contract_signature_reminder_days` |
| `contract.sla_credit_auto_expect` | `true` | A service credit computed from recorded downtime is expected on the next invoice at once; off: finance accepts each one first | contract-risk-agent: obligation_service.py | `contract-risk-agent` · `test_contract_sla_credit_auto_expect` |
| `dev.force_model_fallback` | `[]` | Development only: routers whose primary model is treated as failed — "extraction", "clauses" (FR-08 demo switch; ignored unless APP_ENV=development) | document-vendor-agent: services/extraction_router.py, contract-risk-agent: services/clause_router.py | `document-vendor-agent` · `contract-risk-agent` · `test_dev_force_model_fallback` |
| `document.confidence_review_threshold` | `0.8` | Extraction confidence score threshold below which human review is triggered | document-vendor-agent: confidence.py | `document-vendor-agent` · `test_document_confidence_review_threshold` |
| `document.duplicate_invoice_amount_tolerance_pct` | `0.02` | Tolerance percentage for duplicate invoice detection | document-vendor-agent: duplicate_detection.py | `document-vendor-agent` · `test_document_duplicate_invoice_amount_tolerance_pct` |
| `document.duplicate_invoice_date_window_days` | `7` | Date window in days for duplicate invoice detection | document-vendor-agent: duplicate_detection.py | `document-vendor-agent` · `test_document_duplicate_invoice_date_window_days` |
| `document.extraction_fallback_confidence_threshold` | `0.5` | Confidence threshold to trigger layout/OCR fallback models | document-vendor-agent: extraction_router.py | `document-vendor-agent` · `test_document_extraction_fallback_confidence_threshold` |
| `document.image_preprocessing` | `true` | Straighten and enlarge photographed / scanned documents before reading them | document-vendor-agent: extraction_router.py | `document-vendor-agent` · `test_document_image_preprocessing` |
| `document.review_reminder_hours` | `24` | Remind reviewers when a document has waited this long in the review queue | document-vendor-agent: reminder_sweep.py | `document-vendor-agent` · `test_document_review_reminder_hours` |
| `inventory.reorder_point_pct` | `20` | Reorder when the stock left after backorders falls to this share of the item's total | approval-inventory-agent: reorder.py | `approval-inventory-agent` · `test_inventory_reorder_point_pct` |
| `inventory.reorder_quantity_pct` | `25` | How much to order on top of what is owed, as a share of the item's total | approval-inventory-agent: reorder.py | `approval-inventory-agent` · `test_inventory_reorder_quantity_pct` |
| `invoice.overbill_tolerance_pct` | `0.01` | An invoice may exceed the order's remaining balance by this fraction before it is held | approval-inventory-agent: invoice_ledger.py | `approval-inventory-agent` · `test_invoice_overbill_tolerance_pct` |
| `invoice.unit_price_tolerance_pct` | `0.01` | An invoiced unit price may exceed the ordered price by this fraction before it is held | approval-inventory-agent: invoice_ledger.py | `approval-inventory-agent` · `test_invoice_unit_price_tolerance_pct` |
| `license.anomaly_anomalous_threshold` | `0.75` | Threshold score for flagging a license as anomalous for reclamation | approval-inventory-agent: config.py | `approval-inventory-agent` · `test_license_anomaly_anomalous_threshold` |
| `license.anomaly_watch_threshold` | `0.5` | Threshold score for placing a license on watch status | approval-inventory-agent: config.py | `approval-inventory-agent` · `test_license_anomaly_watch_threshold` |
| `license.reclaim_cooldown_days` | `45` | Days to wait before attempting reclamation again after decline | approval-inventory-agent: approval_service.py | `approval-inventory-agent` · `test_license_reclaim_cooldown_days` |
| `monitor.event_log_retention_days` | `14` | How long the Control Panel keeps Kafka events (summaries only) | document-vendor-agent: event_monitor.py | `document-vendor-agent` · `test_monitor_event_log_retention_days` |
| `risk.contract_renewal_milestones_days` | `[60, 30, 15]` | Days before renewal to trigger notification alerts | contract-risk-agent: api/contracts.py, contract-risk-agent: workflows/activities.py | `contract-risk-agent` · `test_risk_contract_renewal_milestones_days` |
| `risk.psi_moderate_threshold` | `0.1` | Population Stability Index threshold for moderate risk drift | contract-risk-agent: drift_service.py | `contract-risk-agent` · `test_risk_psi_moderate_threshold` |
| `risk.psi_significant_threshold` | `0.2` | Population Stability Index threshold for significant risk drift | contract-risk-agent: drift_service.py | `contract-risk-agent` · `test_risk_psi_significant_threshold` |
| `risk.sanctions_match_threshold_pct` | `90.0` | Match score (0–100) at which a vendor name counts as a potential sanctions match (hard override until finance clears it; FR-14) | contract-risk-agent: services/sanctions.py | `contract-risk-agent` · `test_risk_sanctions_match_threshold_pct` |
| `vendor.bank_verification_reminder_hours` | `24` | Remind finance when a bank-detail change has waited this long for the second person | document-vendor-agent: reminder_sweep.py | `document-vendor-agent` · `test_vendor_bank_verification_reminder_hours` |
| `vendor.duplicate_invoice_number_fuzzy_threshold` | `85` | Invoice numbers at least this similar (0-100) from one vendor count as possible duplicates | document-vendor-agent: duplicate_detection.py | `document-vendor-agent` · `test_vendor_duplicate_invoice_number_fuzzy_threshold` |
| `vendor.expected_delivery_days` | `14` | An order received within this many days of signing counts as on time in vendor risk | contract-risk-agent: risk_signals.py | `contract-risk-agent` · `test_vendor_expected_delivery_days` |
| `vendor.lookalike_min_similarity` | `70` | A new vendor this similar (0-100) to an existing one is flagged as a possible impostor | document-vendor-agent: pipeline.py | `document-vendor-agent` · `test_vendor_lookalike_min_similarity` |
| `vendor.petty_tier_max_amount` | `5000` | Maximum threshold for petty spend tier | document-vendor-agent: vendor_tier_service.py | `document-vendor-agent` · `test_vendor_petty_tier_max_amount` |
| `vendor.standard_tier_max_amount` | `50000` | Maximum threshold for standard spend tier | document-vendor-agent: vendor_tier_service.py | `document-vendor-agent` · `test_vendor_standard_tier_max_amount` |
| `vendor.structuring_detection_window_days` | `90` | Lookback window in days to detect invoice structuring | document-vendor-agent: vendor_tier_service.py | `document-vendor-agent` · `test_vendor_structuring_detection_window_days` |

## Not enforced

| Rule | Default | Why it has no effect today |
|---|---|---|
| `document.invoice_po_match_tolerance_pct` | `0.05` | Superseded by invoice.overbill_tolerance_pct and invoice.unit_price_tolerance_pct (what matching actually uses, 1 %). Its 5 % default would loosen a fraud control — candidate for removal (needs a decision). |
| `license.false_positive_decline_count` | `2` | No false-positive suppression of licence anomalies exists yet. |
| `license.false_positive_window_months` | `6` | No false-positive suppression of licence anomalies exists yet. |
| `license.grace_period_days` | `7` | The 7-day reclaim grace period is a Temporal workflow timer; making it a rule needs a versioned workflow change. |
| `license.minimum_history_days` | `30` | The anomaly model reports insufficient history when there are no logins, not by a day count. |
| `risk.adverse_media_article_count_threshold` | `2` | Adverse-media screening isn't built. |
| `risk.adverse_media_lookback_days` | `90` | Adverse-media screening isn't built. |
| `risk.adverse_media_negative_confidence` | `0.7` | Adverse-media screening isn't built. |

## Changes made on 16 Oct (FR-09)

- Duplicate detection read `vendor.duplicate_invoice_days_window` and `vendor.duplicate_invoice_amount_tolerance_pct`, which were never seeded, so the page's values (7 days, 2 %) never applied and the code used 5 days / 1 %. It now reads `document.duplicate_invoice_date_window_days` and `document.duplicate_invoice_amount_tolerance_pct`.
- Nine rules the code already read were added to the table with the code's own fallbacks (auth migration 0010), so admins can now see and change them: the five `approval.email_*` rules, `invoice.overbill_tolerance_pct`, `invoice.unit_price_tolerance_pct`, `vendor.duplicate_invoice_number_fuzzy_threshold`, `vendor.lookalike_min_similarity`.
- Licence anomaly status (`normal / watch / anomalous`) now comes from one helper, `app/config.anomaly_status_for`, used by both the licence page and the summary.
