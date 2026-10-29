# Business rules

Every rule on the Business Rules page (`/app/business-rules`, admin): what it changes, where the code reads it, and the test that proves changing it changes behaviour. Generated from the live rules table on 16 Oct 2026 (47 rules; 52 after the Phase 1 budget rules of 20 Oct; 55 after the Phase 2 obligation rules; 59 after the Phase 3 sourcing rules; 63 after merging the deterministic risk scorecard; 70 after the Phase 4 GST and TDS rules; 71 after FR-04; 88 after the bulk-approval and signing-mandate rules of 24 Oct) and kept in step by `tests/test_business_rules_registry.py`, which fails if a rule is missing here, if code reads a rule that isn't seeded, or if an enforced rule has no behaviour test.

Rules are read through `shared/rules_engine.get_rule` (cached 5 min, refreshed on `business_rule.updated`); each read has a fallback used when auth-service is unreachable. Tests: `services/<service>/tests/test_rules_wiring.py::test_<rule key with _>` — each sets the rule to two values and checks the behaviour differs.

**Enforced: 78** · **Not enforced: 10** (listed at the end — editing them has no effect until the feature exists).

| Rule | Default | What it changes | Read in | Test |
|---|---|---|---|---|
| `approval.bulk_actions_per_hour` | `20` | Most bulk-approval batches one person may run in an hour (429 after that) | approval-inventory-agent: bulk_service.py | `approval-inventory-agent` · `test_approval_bulk_actions_per_hour` |
| `approval.bulk_approve_enabled` | `true` | Allow approving several eligible requests at once from the inbox | approval-inventory-agent: bulk_service.py | `approval-inventory-agent` · `test_approval_bulk_approve_enabled` |
| `approval.bulk_approve_max_amount` | `25000` | Requests above this amount (INR) must be approved one by one; must not exceed `approval.email_action_max_amount` | approval-inventory-agent: bulk_service.py | `approval-inventory-agent` · `test_approval_bulk_approve_max_amount` |
| `approval.bulk_approve_max_batch_total` | `250000` | Most a single batch may approve in total (INR); requests past it are skipped; must be at least `approval.bulk_approve_max_amount` | approval-inventory-agent: bulk_service.py | `approval-inventory-agent` · `test_approval_bulk_approve_max_batch_total` |
| `approval.bulk_approve_max_items` | `25` | Most requests in one batch (1–100) | approval-inventory-agent: bulk_service.py | `approval-inventory-agent` · `test_approval_bulk_approve_max_items` |
| `approval.bulk_digest_enabled` | `true` | Send the daily batch-approval digest email: each approver's requests eligible for bulk approval, with one batch link | approval-inventory-agent: bulk_digest.py | `approval-inventory-agent` · `test_approval_bulk_digest_enabled` |
| `approval.bulk_digest_min_items` | `2` | Fewest eligible requests an approver must have to get the digest that day | approval-inventory-agent: bulk_digest.py | `approval-inventory-agent` · `test_approval_bulk_digest_min_items` |
| `approval.bulk_digest_time_ist` | `"09:00"` | Time of day (IST, HH:MM) the digest goes out; a malformed value means 09:00 | approval-inventory-agent: bulk_digest.py | `approval-inventory-agent` · `test_approval_bulk_digest_time_ist` |
| `approval.bulk_email_enabled` | `true` | Batch approval by email as a whole: when off, no digest is sent, no batch link is minted, and existing batch links show "turned off" | approval-inventory-agent: email_action_token_service.py, bulk_digest.py, email_action.py | `approval-inventory-agent` · `test_approval_bulk_email_enabled` |
| `approval.bulk_email_token_ttl_hours` | `48` | How long a batch-approval email link stays valid | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_bulk_email_token_ttl_hours` |
| `approval.bulk_excluded_request_types` | `[]` | Request types that can never be approved in bulk | approval-inventory-agent: bulk_service.py | `approval-inventory-agent` · `test_approval_bulk_excluded_request_types` |
| `approval.email_action_allowed_high_risk_vendor` | `false` | Allow email approval when the vendor's risk band is High | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_email_action_allowed_high_risk_vendor` |
| `approval.email_action_allowed_over_budget` | `false` | Allow email approval of requests that exceed the budget | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_email_action_allowed_over_budget` |
| `approval.email_action_enabled` | `true` | Allow approvers to approve or reject from a single-use email link | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_email_action_enabled` |
| `approval.email_action_max_amount` | `50000` | Requests above this amount must be decided in the app, not from email | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_email_action_max_amount` |
| `approval.email_token_ttl_hours` | `48` | How long an approval link in an email stays valid (never past the SLA deadline) | approval-inventory-agent: email_action_token_service.py | `approval-inventory-agent` · `test_approval_email_token_ttl_hours` |
| `approval.high_risk_vendor_requires_finance` | `false` | Purchases from a High-risk vendor get a finance approval step | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_approval_high_risk_vendor_requires_finance` |
| `approval.reminder_sla_percents` | `[50, 80]` | Remind the approver when this much of the approval SLA has passed | approval-inventory-agent: workflows/activities.py | `approval-inventory-agent` · `test_approval_reminder_sla_percents` |
| `approval.sla_escalation_hours` | `48` | Hours before an unapproved request escalates | approval-inventory-agent: approval_service.py, approval-inventory-agent: workflows/activities.py | `approval-inventory-agent` · `test_approval_sla_escalation_hours` |
| `approval.spend_tiers` | `[{"tier_name": "auto", "max_amount": …` | Approval tiers with amount limits and required roles | approval-inventory-agent: approval_service.py | `approval-inventory-agent` · `test_approval_spend_tiers` |
| `approval.unrated_vendor_requires_finance` | `false` | Purchases from a vendor whose risk checks are incomplete (Unrated) get a finance step (merge review G2) | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_approval_unrated_vendor_requires_finance` |
| `budget.block_when_over` | `false` | Refuse an over-budget request (422 over_budget) instead of adding a finance step | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_block_when_over` |
| `budget.fiscal_period_type` | `"quarterly"` | Budgets are per quarter or per fiscal year; decides which budget a request draws on | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_fiscal_period_type` |
| `budget.fiscal_year_start_month` | `4` | Month the fiscal year starts (April); sets the quarter a request falls in | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_fiscal_year_start_month` |
| `budget.no_budget_policy` | `"allow"` | Request with no budget for its department, category and period: allow, add a finance step, or refuse | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_no_budget_policy` |
| `budget.over_budget_requires_finance_approval` | `true` | A request that would exceed its budget gets a finance approval step | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_over_budget_requires_finance_approval` |
| `budget.warning_threshold_pct` | `0.8` | A request that takes its budget past this share is marked *warning* and publishes budget.threshold_crossed | approval-inventory-agent: budget_service.py | `approval-inventory-agent` · `test_budget_warning_threshold_pct` |
| `catalog.preapproved_max_inr` | `0` | Catalog-only requests up to this amount skip the manager step (0 = off); finance steps from budget or vendor-risk rules stay | approval-inventory-agent: catalog_service.py | `approval-inventory-agent` · `test_catalog_preapproved_max_inr` |
| `contract.auto_send_scope` | `"all"` | Which approved requests get their contract sent for signature automatically: "all" or "drop_folder" (only quotes dropped in the inbox folder) | contract-risk-agent: contract_service.py | `contract-risk-agent` · `test_contract_auto_send_scope` |
| `contract.auto_sign_allow_email_channel` | `true` | Contracts approved from an email link may also be signed under a mandate | contract-risk-agent: kafka/consumer.py | `contract-risk-agent` · `test_contract_auto_sign_allow_email_channel` |
| `contract.auto_sign_enabled` | `false` | Sign a contract automatically when finance gives the final approval in bulk or from email and holds an active signing mandate | contract-risk-agent: kafka/consumer.py, approval-inventory-agent: bulk_service.py, email_action.py | `contract-risk-agent` · `test_contract_auto_sign_enabled` |
| `contract.auto_sign_max_amount` | `25000` | Largest contract (INR) signed under a mandate; a mandate can't be issued above it; must not exceed `approval.bulk_approve_max_amount` | contract-risk-agent: kafka/consumer.py, api/mandates.py | `contract-risk-agent` · `test_contract_auto_sign_max_amount` |
| `contract.auto_sign_roles` | `["finance"]` | Roles that may hold a signing mandate | contract-risk-agent: api/mandates.py | `contract-risk-agent` · `test_contract_auto_sign_roles` |
| `contract.clause_extraction_fallback_threshold` | `0.4` | Confidence threshold to fallback during contract clause extraction | contract-risk-agent: clause_router.py | `contract-risk-agent` · `test_contract_clause_extraction_fallback_threshold` |
| `contract.mandate_max_days` | `90` | Longest validity of a signing mandate | contract-risk-agent: api/mandates.py | `contract-risk-agent` · `test_contract_mandate_max_days` |
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
| `document.upload_max_files_per_batch` | `500` | Most files one multi-file or folder upload may contain, and most batch files one user can register per hour (batch files skip the 60-a-minute upload limit) | document-vendor-agent: api/batches.py | `document-vendor-agent` · `test_document_upload_max_files_per_batch` |
| `gst.buyer_gstin` | `"29AAACA1234B1ZE"` | Our GSTIN: invoices must be addressed to it, and it decides within-state (CGST + SGST) versus between-state (IGST) supplies | document-vendor-agent: pipeline.py (tax_agent), api/gst.py | `document-vendor-agent` · `test_gst_buyer_gstin` |
| `gst.einvoice_required_turnover_inr` | `50000000` | A vendor with a recorded turnover above this must send e-invoices with a signed QR; an invoice without one goes to review | document-vendor-agent: pipeline.py (tax_agent) | `document-vendor-agent` · `test_gst_einvoice_required_turnover_inr` |
| `gst.require_breakdown` | `false` | An Indian invoice with no CGST/SGST/IGST amounts goes to review (off: only noted as incomplete) | document-vendor-agent: pipeline.py (tax_agent) | `document-vendor-agent` · `test_gst_require_breakdown` |
| `gst.tax_tolerance_inr` | `1` | How far GST amounts and totals may be off, in rupees, before the tax check fails (also the 2B amount tolerance) | document-vendor-agent: pipeline.py (tax_agent), api/gst.py | `document-vendor-agent` · `test_gst_tax_tolerance_inr` |
| `inventory.reorder_point_pct` | `20` | Reorder when the stock left after backorders falls to this share of the item's total | approval-inventory-agent: reorder.py | `approval-inventory-agent` · `test_inventory_reorder_point_pct` |
| `inventory.reorder_quantity_pct` | `25` | How much to order on top of what is owed, as a share of the item's total | approval-inventory-agent: reorder.py | `approval-inventory-agent` · `test_inventory_reorder_quantity_pct` |
| `invoice.match_against_received` | `true` | Once a request has goods receipts, an invoice line for more than has been received is a variance (three-way match) | approval-inventory-agent: invoice_ledger.py | `approval-inventory-agent` · `test_invoice_match_against_received` |
| `invoice.overbill_tolerance_pct` | `0.01` | An invoice may exceed the order's remaining balance by this fraction before it is held | approval-inventory-agent: invoice_ledger.py | `approval-inventory-agent` · `test_invoice_overbill_tolerance_pct` |
| `invoice.unit_price_tolerance_pct` | `0.01` | An invoiced unit price may exceed the ordered price by this fraction before it is held | approval-inventory-agent: invoice_ledger.py | `approval-inventory-agent` · `test_invoice_unit_price_tolerance_pct` |
| `license.anomaly_anomalous_threshold` | `0.75` | Threshold score for flagging a license as anomalous for reclamation | approval-inventory-agent: config.py | `approval-inventory-agent` · `test_license_anomaly_anomalous_threshold` |
| `license.anomaly_watch_threshold` | `0.5` | Threshold score for placing a license on watch status | approval-inventory-agent: config.py | `approval-inventory-agent` · `test_license_anomaly_watch_threshold` |
| `license.reclaim_cooldown_days` | `45` | Days to wait before attempting reclamation again after decline | approval-inventory-agent: approval_service.py | `approval-inventory-agent` · `test_license_reclaim_cooldown_days` |
| `monitor.event_log_retention_days` | `14` | How long the Control Panel keeps Kafka events (summaries only) | document-vendor-agent: event_monitor.py | `document-vendor-agent` · `test_monitor_event_log_retention_days` |
| `msme.payment_days` | `45` | Days from acceptance within which a micro or small enterprise's invoice must be paid (s. 43B(h)) | approval-inventory-agent: tds_service.py | `approval-inventory-agent` · `test_msme_payment_days` |
| `msme.warning_days` | `7` | An unpaid MSME invoice shows as due soon this many days before its deadline | approval-inventory-agent: tds_service.py | `approval-inventory-agent` · `test_msme_warning_days` |
| `reorder.create_request_roles` | `["requester", "approver", "finance", "admin"]` | Roles that may turn a reorder suggestion into a purchase request | approval-inventory-agent: api/requests.py | `approval-inventory-agent` · `test_reorder_create_request_roles` |
| `risk.alert_recipients` | `"procurement-risk-team@company.com"` | Who is e-mailed when a vendor turns High risk or a new hard override fires (empty = nobody) | contract-risk-agent: risk_service.py | `contract-risk-agent` · `test_risk_alert_recipients` |
| `risk.breach_catalogue_max_age_days` | `30` | A breach catalogue older than this no longer counts; breach history becomes not assessed | contract-risk-agent: collectors/cyber_collectors.py | `contract-risk-agent` · `test_risk_breach_catalogue_max_age_days` |
| `risk.breach_name_match_pct` | `85` | A breach whose name is at least this similar to the vendor's is a candidate a reviewer must confirm | contract-risk-agent: collectors/cyber_collectors.py | `contract-risk-agent` · `test_risk_breach_name_match_pct` |
| `risk.contract_renewal_milestones_days` | `[60, 30, 15]` | Days before renewal to trigger notification alerts | contract-risk-agent: api/contracts.py, contract-risk-agent: workflows/activities.py | `contract-risk-agent` · `test_risk_contract_renewal_milestones_days` |
| `risk.financial_max_debt_to_equity` | `1.0` | Audited statements pass the leverage check when total borrowings ÷ total equity is at most this (financial statement score, below) | contract-risk-agent: collectors/company_collectors.py | `contract-risk-agent` · `test_risk_financial_max_debt_to_equity` |
| `risk.financial_min_current_ratio` | `1.2` | Audited statements pass the liquidity check when current assets ÷ current liabilities is at least this (financial statement score, below) | contract-risk-agent: collectors/company_collectors.py | `contract-risk-agent` · `test_risk_financial_min_current_ratio` |
| `risk.min_relationship_days` | `90` | Days on file (without a delivered order) before a vendor's incident history counts as assessed | contract-risk-agent: collectors/performance_collectors.py | `contract-risk-agent` · `test_risk_min_relationship_days` |
| `risk.petty_threshold` | `50000` | A provisional low-tier vendor is still cleared for a purchase or contract up to this amount (no hard override) | contract-risk-agent: api/vendors.py (clearance) | `contract-risk-agent` · `test_risk_petty_threshold` |
| `risk.raw_retention_months` | `24` | How long raw responses from the risk signal collectors are kept | contract-risk-agent: collectors/base.py | `contract-risk-agent` · `test_risk_raw_retention_months` |
| `risk.required_certifications_by_tier` | `{"critical": ["ISO 27001 or SOC 2…"], …` | Certifications a vendor of each tier must hold | contract-risk-agent: collectors/cyber_collectors.py | `contract-risk-agent` · `test_risk_required_certifications_by_tier` |
| `risk.sanctions_match_threshold_pct` | `90.0` | Match score (0–100) at which a vendor name counts as a potential sanctions match (hard override until finance clears it; FR-14) | contract-risk-agent: services/sanctions.py | `contract-risk-agent` · `test_risk_sanctions_match_threshold_pct` |
| `sourcing.default_criteria` | `{"price": 0.45, "lead_time": 0.15, …}` | Weights for comparing RFQ quotes (price, lead time, warranty, support, vendor risk, delivery record; add up to 1); each new RFQ starts with them | approval-inventory-agent: sourcing_service.py | `approval-inventory-agent` · `test_sourcing_default_criteria` |
| `sourcing.rfq_required_above_inr` | `200000` | A request above this with no RFQ or catalog price gets an advisory *sourcing* note on its page (0 = off) | approval-inventory-agent: sourcing_service.py | `approval-inventory-agent` · `test_sourcing_rfq_required_above_inr` |
| `tds.category_sections` | `{"hardware": "194Q", …` | TDS section per purchase category when the vendor's tax profile names none | approval-inventory-agent: tds_service.py | `approval-inventory-agent` · `test_tds_category_sections` |
| `vendor.bank_verification_reminder_hours` | `24` | Remind finance when a bank-detail change has waited this long for the second person | document-vendor-agent: reminder_sweep.py | `document-vendor-agent` · `test_vendor_bank_verification_reminder_hours` |
| `vendor.duplicate_invoice_number_fuzzy_threshold` | `85` | Invoice numbers at least this similar (0-100) from one vendor count as possible duplicates | document-vendor-agent: duplicate_detection.py | `document-vendor-agent` · `test_vendor_duplicate_invoice_number_fuzzy_threshold` |
| `vendor.expected_delivery_days` | `14` | An order received within this many days of signing counts as on time in vendor risk | contract-risk-agent: risk_signals.py | `contract-risk-agent` · `test_vendor_expected_delivery_days` |
| `vendor.lookalike_min_similarity` | `70` | A new vendor this similar (0-100) to an existing one is flagged as a possible impostor | document-vendor-agent: pipeline.py | `document-vendor-agent` · `test_vendor_lookalike_min_similarity` |
| `vendor.petty_tier_max_amount` | `5000` | Maximum threshold for petty spend tier | document-vendor-agent: vendor_tier_service.py | `document-vendor-agent` · `test_vendor_petty_tier_max_amount` |
| `vendor.standard_tier_max_amount` | `50000` | Maximum threshold for standard spend tier | document-vendor-agent: vendor_tier_service.py | `document-vendor-agent` · `test_vendor_standard_tier_max_amount` |
| `vendor.structuring_detection_window_days` | `90` | Lookback window in days to detect invoice structuring | document-vendor-agent: vendor_tier_service.py | `document-vendor-agent` · `test_vendor_structuring_detection_window_days` |

## Financial statement score (set 29 Oct 2026)

A vendor with no current credit rating (Hathway's was withdrawn in 2022) is
scored from its latest audited statements. Finance enters five figures from
them in the vendor's Evidence Register (type "Audited financial statements"),
in any one unit, plus the period end, the auditor's opinion and whether the
auditor reports a going-concern doubt. The score is the share of five checks
passed:

| Check | Passes when |
|---|---|
| Positive net worth | total equity > 0 |
| Profitable year | profit after tax > 0 |
| Liquidity | current assets ÷ current liabilities ≥ `risk.financial_min_current_ratio` (1.2) |
| Leverage | total borrowings ÷ total equity ≤ `risk.financial_max_debt_to_equity` (1.0) |
| Clean audit | the auditor's opinion is unmodified |

A going-concern doubt scores 0 whatever the figures say. The scorecard then
applies its existing outcomes: 0.8 or more (4–5 checks) R-FIN-04, 0 points;
0.4–0.6 (2–3 checks) R-FIN-05, 2 points; below 0.4 R-FIN-06, 4 points. A
missing figure leaves financial "not assessed" (R-FIN-07); it no longer
counts as a pass. Statements older than 365 days from their period end don't
count. A credit rating, when there is one, is used instead. These limits are
ours for the project; a company adopting it would have its finance team set them.

## Not enforced

| Rule | Default | Why it has no effect today |
|---|---|---|
| `risk.psi_moderate_threshold` | `0.1` | Retired 21 Oct 2026 with the PSI drift check of the archived ML risk model (`ml/archive/`); the weekly monitoring report replaced it |
| `risk.psi_significant_threshold` | `0.2` | Retired 21 Oct 2026 with the PSI drift check of the archived ML risk model (`ml/archive/`); the weekly monitoring report replaced it |
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
