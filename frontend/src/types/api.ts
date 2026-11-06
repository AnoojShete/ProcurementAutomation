// Mirrors the Pydantic response models read directly from each service's
// app/schemas.py — see the plan doc for the file-by-file source. Keep these
// in sync with the backend; never add a field the backend doesn't return.

export type Role = "requester" | "approver" | "finance" | "admin";

export type ThemePreference = "light" | "dark" | "system";

export interface CurrentUser {
  id: string;
  email: string;
  role: Role;
  display_name: string | null;
  theme: ThemePreference;
}

/** One row of the people directory (GET /auth/people). */
export interface Person {
  id: string;
  email: string;
  role: Role;
  display_name: string | null;
}

/** An account as the admin Users page sees it. */
export interface AccountUser extends CurrentUser {
  is_active: boolean;
  email_verified_at: string | null;
  created_at: string | null;
  last_login_at: string | null;
}

// --- auth-service ---
export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_minutes: number;
}
export interface AccessTokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_minutes: number;
}

// --- approval-inventory-agent ---
export type RequestType = "hardware" | "license" | "saas" | "reclaim";
export type SpendTier = "auto" | "manager" | "manager+finance" | "catalog";
export type RequestStatus =
  | "pending_approval"
  | "approved"
  | "ordered"
  | "rejected"
  | "fulfilled"
  | string;

export interface ApprovalHistoryEntry {
  id: string;
  decision: string;
  decided_by: string;
  decision_level: string | null;
  escalated: boolean;
  comments: string | null;
  decided_at: string | null;
}

export interface PurchaseRequest {
  id: string;
  document_id: string | null;
  request_type: RequestType | null;
  requested_by: string | null;
  department: string | null;
  vendor_id: string | null;
  amount: number | null;
  currency: string | null;
  spend_tier: SpendTier | null;
  status: RequestStatus | null;
  approval_chain: string[] | null;
  current_approver_index: number;
  selected_approver?: string | null;
  sla_deadline: string | null;
  items: Record<string, unknown>[] | null;
  is_backordered: boolean;
  comments?: string | null;
  source?: string | null;
  source_ref?: string | null;
  requested_by_user_id?: string | null;
  bulk_eligible?: boolean | null;
  bulk_ineligible_reasons?: string[] | null;
  next_action?: any;
  created_at: string | null;
  updated_at: string | null;
  approval_history: ApprovalHistoryEntry[] | null;
  /** Budget check made when the request was created (Phase 1). */
  budget_id?: string | null;
  budget_status?: BudgetStatus | null;
  budget_check?: BudgetCheck | null;
  /** Phase 3: advisory sourcing notes (RFQ recommended, over contract seats). */
  sourcing_flags?: { code: string; message: string }[] | null;
  rfq_id?: string | null;
}

export type BudgetCategory = "hardware" | "software" | "saas" | "services";
export type BudgetStatus = "within" | "warning" | "over" | "no_budget";
export type BudgetRoutingReason = "over_budget" | "no_budget" | "high_risk_vendor" | "unrated_vendor" | "catalog_preapproved";

export interface BudgetCheck {
  status?: BudgetStatus;
  fiscal_year?: string;
  period?: string;
  category?: BudgetCategory;
  department?: string;
  budget_id?: string | null;
  budget_amount?: number | null;
  used_before?: number;
  request_amount?: number;
  left_after?: number | null;
  warning_crossed?: boolean;
  routing?: BudgetRoutingReason[];
}

/** A budget with its usage, computed from the requests that draw on it. */
export interface Budget {
  id: string;
  fiscal_year: string;
  period: string;
  department: string;
  category: BudgetCategory;
  amount_inr: number;
  owner_email: string | null;
  consumed: number;
  committed: number;
  pending: number;
  used: number;
  left: number;
  used_pct: number | null;
  status: Exclude<BudgetStatus, "no_budget">;
}

export interface BudgetRequestRow {
  id: string;
  request_type: string | null;
  status: string;
  amount: number;
  invoiced: number;
  requested_by: string;
  created_at: string | null;
  budget_status_at_creation: BudgetStatus | null;
  counts_as: "consumed/committed" | "pending" | "released";
}

export interface BudgetDetail extends Budget {
  requests: BudgetRequestRow[];
}

export interface BudgetPeriod {
  fiscal_year: string;
  period: string;
  period_type: "quarterly" | "annual";
  categories: BudgetCategory[];
}

export interface RequestBudgetLine {
  applies: boolean;
  status_at_creation: BudgetStatus | null;
  check: BudgetCheck | null;
  budget: Budget | null;
}

export interface BudgetInput {
  department: string;
  category: BudgetCategory;
  amount_inr: number;
  fiscal_year?: string;
  period?: string;
  owner_email?: string | null;
}

export interface CreatePurchaseRequestBody {
  request_type: RequestType;
  requested_by: string;
  department: string;
  vendor_id?: string | null;
  document_id?: string | null;
  amount: number;
  currency?: string;
  items?: Record<string, unknown>[] | null;
  comments?: string | null;
  source?: string | null;
  source_ref?: string | null;
  idempotency_key?: string | null;
  selected_approver?: string | null;
}

export interface InboxItem {
  request_id: string;
  request_type: string;
  requested_by: string;
  department: string;
  amount: number;
  currency: string;
  spend_tier: string;
  sla_deadline: string | null;
  created_at: string | null;
  /** Set for reclaim/license requests: the license they concern. */
  license_id?: string | null;
}

export interface InventoryItem {
  id: string;
  sku: string;
  name: string;
  category: string | null;
  total_quantity: number;
  available_quantity: number;
  reserved_quantity: number;
  unit_cost: number | null;
  currency: string | null;
  location: string | null;
  vendor_id?: string | null;
  reorder?: ReorderStatus | null;
}

/** BR-5: computed by approval-inventory-agent (services/reorder.py). */
export interface ReorderStatus {
  reorder_point: number;
  reorder_quantity: number;
  point_source: "item" | "rule";
  quantity_source: "item" | "rule";
  backordered_units: number;
  needs_reorder: boolean;
  suggested_quantity: number;
  explanation: string;
}

export type AnomalyStatus = "normal" | "watch" | "anomalous" | "insufficient_history";

export interface AnomalyFactor {
  feature: string;
  contribution: number;
  direction?: "increasing_risk" | "decreasing_risk";
}

export interface LicenseItem {
  id: string;
  vendor_id: string | null;
  vendor_name?: string | null;
  app_name: string;
  total_seats: number;
  assigned_seats?: number;
  active_seats_30d: number;
  active_seats_60d: number;
  active_seats_90d: number;
  utilisation_score: number;
  anomaly_score: number | null;
  anomaly_status: AnomalyStatus;
  top_factors?: AnomalyFactor[];
  reclaim_cooldown_until: string | null;
  last_scored_at: string | null;
  days_since_last_login: number;
  cost_per_seat: number | null;
  currency?: string;
  period_start?: string | null;
  period_end: string | null;
  status: string;
}

export interface UsageHistoryEntry {
  date: string;
  active_seats: number;
}

export interface LicenseAnomalySummary {
  total_licenses: number;
  anomalous: number;
  watch: number;
  normal: number;
  insufficient_history: number;
  last_scoring_run: string | null;
  potential_annual_savings: number;
}

export interface ReclaimHistoryEntry {
  id?: string;
  event_type: "reclaim_opened" | "declined" | "reinstated" | "reclaimed" | "reviewed" | string;
  event_at: string;
  by_user: string | null;
  cooldown_set_until: string | null;
  notes?: string | null;
}

export interface InventorySnapshot {
  hardware: InventoryItem[];
  licenses: LicenseItem[];
}

// --- document-vendor-agent ---
export type DocumentType = "po" | "invoice" | "quote" | "other";
export type DocumentStatus = "pending" | "processing" | "classified" | "failed" | string;

export interface DocumentRecord {
  id: string;
  status: DocumentStatus;
  document_type: DocumentType | null;
  vendor_id: string | null;
  vendor_name_raw: string | null;
  extracted_fields: Record<string, unknown>;
  confidence_scores: Record<string, number>;
  overall_confidence: number | null;
  needs_review: boolean;
  is_likely_duplicate: boolean;
  duplicate_of_document_id: string | null;
  file_type: string | null;
  original_filename: string | null;
  uploaded_by: string | null;
  uploaded_at: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  error_message: string | null;
  /** Amount in INR and the exchange rate used, fixed when the document was
   * processed. Null until then. */
  fx?: DocumentFx | null;
  /** GST check of an invoice (Phase 4); null for other documents. */
  tax_check?: TaxCheck | null;
  /** upload | folder | email; the sender's address for email. */
  source?: string | null;
  source_sender?: string | null;
}

export interface DocumentFx {
  currency: string;
  total: number | null;
  total_inr: number;
  rate: number | null;
  rate_date: string | null;
  source: string | null;
}

export type BatchUploadResult =
  | { filename: string; document_id: string; status: string; error?: undefined }
  | { filename: string; error: string; document_id?: undefined };

export interface OrderAttentionItem {
  request_id: string;
  kind: "approval_overdue" | "signature_stalled" | "delivery_overdue" | "status_mismatch" | "backordered";
  severity: "high" | "medium" | "low";
  message: string;
}

export interface OrderSummary {
  id: string;
  generated_at: string;
  window_start: string;
  trigger: string;
  counts: {
    pending_approval: number;
    approval_overdue: number;
    awaiting_signature: number;
    awaiting_delivery: number;
    delivery_overdue: number;
    backordered: number;
  };
  changes: { new_requests: number; approved: number; invoices_received: number; rejected: number };
  open_order_value: number | null;
  attention: OrderAttentionItem[];
  summary_text: string;
}

export interface ReviewCorrectionBody {
  reviewed_by: string;
  vendor_name: string;
  extracted_fields: Record<string, unknown>;
  document_type: DocumentType;
}

export interface VendorPaymentChange {
  id: string;
  vendor_id: string;
  submitted_by: string;
  submitted_at: string | null;
  source: string;
  status: string;
  verified_by: string | null;
  verified_at: string | null;
  verification_channel: string | null;
  document_id?: string | null;
  previous_account_last4?: string | null;
  new_account_last4?: string | null;
  new_routing_code?: string | null;
  new_beneficiary_name?: string | null;
  vendor_name?: string;
}

// --- contract-risk-agent: vendors/risk ---
export type RiskBand = "Low" | "Medium" | "High" | string;

export interface VendorSummary {
  id: string;
  name: string;
  status: string;
  inherent_tier?: string | null;
  swift_bic?: string | null;
  bank_name?: string | null;
  website?: string | null;
  portal_access_revoked: boolean;
  risk_band: RiskBand | null;
  risk_score: number | null;
  // "assessed" | "provisional" | "not_rated": a provisional band is shown as such, never green
  rating_status?: string | null;
  created_at: string | null;
}

export interface RiskFactor {
  feature: string;
  contribution: number;
  /** A hard override (e.g. GSTIN cancelled): the vendor is High whatever the model says. */
  override?: boolean;
  reason?: string | null;
}

// Older scores name the check ("sanctions"); scorecard scores name the rule ("R-SAN-01").
export interface RiskOverrideCheck {
  check?: "gstin" | "sanctions" | "ifsc" | string;
  rule_id?: string;
  status: "triggered" | "clear" | "not_checked";
  reason?: string | null;
}

export interface VendorRisk {
  vendor_id: string;
  risk_band: RiskBand;
  // null until the rating is "assessed" (unrated / provisional vendors have no score)
  risk_score: number | null;
  top_factors?: RiskFactor[];
  model_version?: string | null;
  scored_at: string | null;
  total_points?: number;
  points_band?: string;
  final_band?: string;
  worst_case_points?: number;
  worst_case_band?: string;
  unassessed_potential_points?: number;
  is_provisional?: boolean;
  provisional?: {
    is_provisional: boolean;
    reasons: (string | { code?: string; signal?: string; message?: string })[];
  };
  provisional_reasons?: (string | { code?: string; signal?: string; message?: string })[];
  data_needed?: DataNeededItem[];
  override_rule_ids?: string[];
  headline?: string;
  ruleset_version?: number;
  trigger_type?: string;
  score_id?: string;
  explanation?: Record<string, unknown>;
  snapshot_sha256?: string;
  /** How many of the model's signals were on file (null for older scores). */
  signals_used?: number | null;
  signals_total?: number | null;
  overrides?: RiskOverrideCheck[];
  rating_status?: string;
}

export interface ScorecardRuleResult {
  rule_id: string;
  signal_key: string;
  signal_label?: string;
  label?: string;
  group_key: string;
  group?: string;
  status: "assessed" | "not_assessed" | "not_applicable" | "review_pending" | string;
  points: number;
  potential_points: number;
  max_points?: number;
  override_band: string | null;
  observed_fields: Record<string, any>;
  facts: Array<{ label: string; value: string }>;
  reason_text: string;
  rationale: string;
  remediable: boolean;
  ages_out_on: string | null;
}

/** A detail missing from the vendor record that a risk check is waiting on. */
export interface DataNeededItem {
  field: string;
  signal: string;
  message: string;
  points: number;
}

export interface ScorecardExplanation {
  score_id: string;
  rating_status?: string;
  vendor_id: string;
  ruleset_version: number;
  assessed_at: string;
  total_points: number;
  points_band: string;
  final_band: string;
  worst_case_points: number;
  worst_case_band: string;
  unassessed_potential_points: number;
  is_provisional: boolean;
  provisional_reasons: (string | { code?: string; signal?: string; message?: string })[];
  override_rule_ids: string[];
  headline: string;
  data_needed?: DataNeededItem[];
  /** One step per group: {group_label, narrative, points, max_points} (older scores: plain strings). */
  thought_process: (string | { step?: number; group_key?: string; group_label?: string; narrative?: string; points?: number; max_points?: number })[];
  score_breakdown: ScorecardRuleResult[];
  signals?: ScorecardRuleResult[];
  unassessed_signals: Array<{
    signal_key: string;
    signal_label?: string;
    potential_points: number;
    provider?: string;
    reason_not_assessed?: string;
  }>;
  override_details: Array<{
    rule_id: string;
    signal_key: string;
    override_band: string;
    rationale: string;
  }>;
  snapshot_sha256: string;
}

export interface RemediationStep {
  rule_id: string;
  signal_key: string;
  points: number;
  who: "vendor" | "buyer";
  step: string;
  evidence: string;
  submit_via: string;
  shareable_with_vendor: boolean;
}

export interface RemediationPlan {
  summary?: string;
  total_points: number;
  recoverable_points: number;
  projected_points: number;
  projected_band: string;
  actions: RemediationStep[];
}

export interface WhatIfResult {
  original_points: number;
  original_band: string;
  simulated_points: number;
  simulated_band: string;
  simulated_rules: string[];
  score_difference: number;
}

export interface RiskHistoryEntry {
  id: string;
  assessed_at: string;
  total_points: number;
  points_band: string;
  final_band: string;
  is_provisional: boolean;
  trigger_type: string;
  ruleset_version: number;
  headline: string;
}

export interface VendorDispute {
  id: string;
  score_id: string;
  rule_result_id: string;
  raised_by: string;
  raised_at: string;
  reason: string;
  evidence_id: string | null;
  status: "open" | "upheld" | "rejected";
  reviewed_by: string | null;
  reviewed_at: string | null;
  resolution_note: string | null;
}

export interface VendorEvidence {
  id: string;
  evidence_type: string;
  title: string;
  status: "accepted" | "pending_review" | string;
  valid_from: string | null;
  valid_until: string | null;
  scope_covers_service?: boolean;
  verified_at: string | null;
  verified_by: string | null;
  created_at: string;
}

/** What finance records in a vendor's evidence register (metadata carries
 * a credit rating's agency/grade or audited statement figures). */
export interface VendorEvidenceCreate {
  evidence_type: string;
  title: string;
  valid_from?: string;
  valid_until?: string;
  notes?: string;
  metadata?: Record<string, unknown>;
}

export interface RulesetResponse {
  id: string;
  version: number;
  status: "draft" | "active" | "retired";
  definition: any;
  definition_hash: string;
  created_by: string;
  created_at: string;
  activated_by: string | null;
  activated_at: string | null;
  change_justification: string | null;
  dry_run_report: any;
}

export interface DryRunReport {
  sample_size: number;
  duration_ms: number;
  avg_duration_ms: number;
  migration_matrix: Record<string, number>;
  score_diff_distribution: Record<string, number>;
  top_movers: Array<{
    vendor_id: string;
    active_points: number;
    draft_points: number;
    diff: number;
    active_band: string;
    draft_band: string;
  }>;
  overrides_active: Record<string, number>;
  overrides_draft: Record<string, number>;
}

export interface MonitoringReport {
  report_generated_at: string;
  lookback_days: number;
  active_ruleset_version: number;
  total_assessments: number;
  rating_distribution: {
    low: number;
    low_pct: number;
    medium: number;
    medium_pct: number;
    high: number;
    high_pct: number;
    provisional: number;
    provisional_pct: number;
  };
  rule_frequencies: Array<{
    rule_id: string;
    signal_key: string;
    description: string;
    times_fired: number;
    fire_pct: number;
    is_dead: boolean;
    is_overly_sensitive: boolean;
  }>;
  override_frequencies: Record<string, number>;
  missing_signal_rates: Array<{
    signal_key: string;
    not_assessed_count: number;
    missing_rate_pct: number;
    exceeds_threshold: boolean;
  }>;
  dispute_stats: {
    raised_count: number;
    upheld_count: number;
    rejected_count: number;
    open_count: number;
    top_disputed_signals: Record<string, number>;
  };
  calibration_candidates: Array<{
    vendor_id: string;
    incident_date: string;
    actual_incident_occurred: boolean;
    score_at_incident: number;
    band_at_incident: string;
    notes?: string;
  }>;
}

export interface DriftCheckResult {
  [key: string]: unknown;
}

export interface OffboardResult {
  contracts_flagged: string[];
  [key: string]: unknown;
}

// --- contract-risk-agent: contracts ---
export type ContractStatus = "draft" | "pending_signature" | "signed" | string;
export type ContractTemplate = "hardware_purchase" | "saas_subscription" | "professional_services";

export interface SignatureCertificate {
  certificate_id: string;
  contract_id: string;
  template_used?: string | null;
  signer_name: string;
  signer_email: string;
  signer_designation?: string | null;
  signed_at: string;
  signature_seal: string;
  legal_framework: string;
  consent_acknowledged: boolean;
  ip_address?: string | null;
  user_agent?: string | null;
  signature_image?: string | null;
  signing_method?: string | null;
}

export interface Contract {
  id: string;
  purchase_request_id: string | null;
  vendor_id: string | null;
  template_used: string | null;
  version: number | null;
  status: ContractStatus;
  renewal_type: string | null;
  notice_period_days: number | null;
  contract_end_date: string | null;
  generated_at: string | null;
  signed_at: string | null;
  signed_by: string | null;
  esign_provider_ref: string | null;
  /** Sent for signature by the platform after approval, nobody clicked "Send". */
  sent_automatically?: boolean;
  approval_channel?: string | null;
  signature_method?: string | null;
  bulk_batch_id?: string | null;
  mandate_id?: string | null;
  /** Last day to give notice (end date − notice period); reminders count back from it. */
  notice_deadline?: string | null;
  renewal_reminders?: { alert_level: number; date: string; passed: boolean }[];
  next_renewal_reminder?: string | null;
  reconciliation_status: string | null;
  contract_text: string | null;
  signature_certificate?: SignatureCertificate | null;
  /** BR-6: the vendor's risk as the signer should see it (GET /contracts/:id only). */
  vendor_risk?: SigningRisk;
  /** How a contract sent now is signed: both parties in Documenso's frame, or the built-in e-sign. */
  signing_provider?: "documenso" | "builtin";
  /** Documenso: the company's signatory, then the vendor (GET /contracts/:id only). */
  signers?: ContractSigner[];
  /** Staff, draft contracts: the vendor's contact email, the default vendor signatory. */
  vendor_contact_email?: string | null;
}

export interface ContractSigner {
  party: "company" | "vendor";
  name: string;
  email: string;
  status: "waiting" | "ready" | "signed" | "rejected";
  signed_at: string | null;
  rejection_reason: string | null;
  link_expires_at: string | null;
}

/** Opens Documenso's signing frame for one signer. */
export interface SigningSession {
  host: string;
  token: string;
  name: string;
  party: "company" | "vendor";
  legal_basis: string;
}

/** The vendor's signing page, from the emailed link. */
export interface VendorSigningSession {
  state: "ready" | "signed" | "closed" | "expired";
  contract_id: string;
  title: string;
  vendor_name: string;
  company_name: string;
  signer_name: string;
  signer_email: string;
  company_signer: string | null;
  company_signed_at: string | null;
  signed_at: string | null;
  legal_basis: string;
  host?: string;
  token?: string;
}

export interface SigningRisk {
  risk_band: string | null;
  rating_status?: string | null;
  risk_score: number | null;
  reasons: { feature: string; contribution: number }[];
  overrides: { check: string; status: string; reason: string | null }[];
  scored_at: string | null;
  acknowledgement_required: boolean;
  acknowledgement_reason: string | null;
  /** A sanctions match or prohibited country: nobody can sign. */
  signing_blocked?: boolean;
  blocked_reason?: string | null;
}

// --- notification-agent ---
export interface NotificationLogEntry {
  id: string;
  recipient: string;
  channel: string;
  event_type: string;
  template_name: string | null;
  subject: string | null;
  priority: string | null;
  related_entity_id: string | null;
  status: string;
  error: string | null;
  sent_at: string | null;
  created_at: string | null;
}

/** A notification in your own feed, with your read state. */
export interface FeedEntry extends NotificationLogEntry {
  read: boolean;
}

// --- health ---
export interface HealthResponse {
  status: "ok" | "degraded" | string;
  service: string;
  dependencies: Record<string, "up" | "down">;
}

// --- business-rules ---
export interface BusinessRule {
  id: string;
  rule_key: string;
  category: "approval" | "budget" | "vendor_verification" | "license_usage" | "risk_compliance" | string;
  display_name: string;
  description: string;
  value_type: "currency" | "integer" | "float" | "days" | "hours" | "percentage" | "boolean" | "json" | string;
  current_value: any;
  default_value: any;
  min_value: number | null;
  max_value: number | null;
  updated_by: string | null;
  updated_at: string | null;
}

export interface BusinessRuleHistory {
  id: string;
  rule_key: string;
  old_value: any;
  new_value: any;
  changed_by: string;
  changed_at: string | null;
  justification: string;
}

export interface SpendTierItem {
  tier_name: string;
  min_amount: number;
  max_amount: number | null;
  required_approvers: string[];
  sla_hours: number;
}

export interface ApiEnvelope<T> {
  data: T;
  meta?: Record<string, unknown>;
}

export interface ApiErrorEnvelope {
  error: { code: string; message: string };
}


// --- event backbone (shared/eventing) ---
export interface OutboxServiceStats {
  pending: number;
  oldest_pending: string | null;
  sent_last_hour: number;
  last_error: string | null;
}
export interface EventingStatus {
  outbox: Record<string, OutboxServiceStats>;
  dlq: Record<string, Record<string, number>>;
  showcase_mode: boolean;
}
export interface DlqEntry {
  id: string;
  consumer: string;
  topic: string;
  event_id: string | null;
  event: { event_type?: string; payload?: Record<string, unknown>; source_service?: string };
  error: string;
  attempts: number;
  failed_at: string;
  status: "open" | "replayed" | "discarded";
  resolved_at: string | null;
  resolved_by: string | null;
  resolution: string | null;
}
export interface ReconcileResult {
  request_id: string;
  contract_id: string;
  outcome: string;
}

// --- approval authority ---
export interface AuthorityCheck {
  allowed: boolean;
  code: string;
  reason: string;
  level?: string | null;
  via_delegation?: string | null;
  limit?: number | null;
}
export interface SelectableApprover {
  email: string;
  name: string | null;
}
export interface ApproverAssignment {
  id: string;
  level: string;
  user_email: string;
  max_amount: number | null;
  active: boolean;
  created_by: string | null;
  created_at: string | null;
}
export interface ApprovalDelegation {
  id: string;
  level: string;
  delegator_email: string;
  delegate_email: string;
  valid_from: string;
  valid_until: string;
  reason: string | null;
  created_by: string | null;
  active: boolean;
  revoked_at: string | null;
}

// --- sourcing (Phase 3) ---
export type CatalogCategory = "hardware" | "software" | "saas";
export interface CatalogItem {
  id: string;
  sku: string;
  name: string;
  category: CatalogCategory;
  request_type: RequestType;
  vendor_id: string | null;
  vendor_name: string | null;
  contract_id: string | null;
  unit_price: number;
  currency: string;
  spec: Record<string, string>;
  inventory_sku: string | null;
  license_id: string | null;
  lead_time_days: number | null;
  warranty_months: number | null;
  active: boolean;
  valid_until: string | null;
  available: boolean;
  seat_addon: boolean;
}
export interface CatalogItemInput {
  sku: string;
  name: string;
  category: CatalogCategory;
  vendor_id: string;
  unit_price: number;
  spec?: Record<string, string>;
  inventory_sku?: string | null;
  license_id?: string | null;
  lead_time_days?: number | null;
  warranty_months?: number | null;
  valid_until?: string | null;
}
export type RfqStatus = "open" | "closed" | "awarded" | "cancelled";
export type RfqCriterion = "price" | "lead_time" | "warranty" | "support" | "vendor_risk" | "delivery_record";
export interface RfqSummary {
  id: string;
  reference: string;
  title: string;
  department: string;
  request_type: RequestType;
  items: { name: string; quantity: number; spec?: string | null }[];
  criteria: Partial<Record<RfqCriterion, number>>;
  sealed: boolean;
  round: number;
  deadline: string;
  status: RfqStatus;
  created_by: string;
  awarded_vendor_id: string | null;
  awarded_response_id: string | null;
  awarded_request_id: string | null;
  created_at: string | null;
  invited?: number;
  responded?: number;
}
export interface RfqResponse {
  id?: string;
  vendor_id: string;
  vendor_name: string | null;
  round: number;
  submitted_at: string | null;
  total_inr?: number;
  lead_time_days?: number | null;
  warranty_months?: number | null;
  support_rating?: number | null;
  support_terms?: string | null;
  source?: "manual" | "quote";
  quote_id?: string | null;
}
export interface RankedResponse extends RfqResponse {
  id: string;
  total_inr: number;
  scores: Record<RfqCriterion, number>;
  total_score: number;
  rank: number;
}
export interface RfqDetail extends RfqSummary {
  sealed_now: boolean;
  invitations: { vendor_id: string; vendor_name: string | null; round: number; invited_at: string | null; responded_at: string | null }[];
  responses: RfqResponse[];
  comparison: {
    round: number;
    weights: Partial<Record<RfqCriterion, number>>;
    vendor_info: Record<string, { risk_band: string | null; on_time_rate: number | null }>;
    ranked: RankedResponse[];
  } | null;
}
export interface RfqInput {
  title: string;
  department: string;
  request_type: "hardware" | "license" | "saas";
  items: { name: string; quantity: number; spec?: string }[];
  vendor_ids: string[];
  deadline: string;
  sealed: boolean;
  criteria?: Partial<Record<RfqCriterion, number>>;
}
export interface RfqResponseInput {
  vendor_id: string;
  total_inr: number;
  lead_time_days?: number | null;
  warranty_months?: number | null;
  support_rating?: number | null;
  support_terms?: string | null;
}
export interface GoodsReceipt {
  id: string;
  lines: { line_no: number; quantity: number; asset_tags: string[] }[];
  received_by: string;
  received_at: string | null;
  notes: string | null;
}
export interface RequestReceipts {
  receipts: GoodsReceipt[];
  lines: { line_no: number; description: string; ordered: number; received: number }[];
}
export interface VendorScorecard {
  vendor_id: string;
  on_time_rate: number | null;
  deliveries: number;
  deliveries_on_time: number;
  expected_delivery_days: number;
  invoice_accuracy: number | null;
  invoices: number;
  rfq_response_rate: number | null;
  rfq_invitations: number;
  sla_breaches: number;
  risk_band: string | null;
  computed_at: string;
}

// --- contract obligations (Phase 2) ---
export type ObligationType =
  | "sla_uptime" | "license_limit" | "price_cap" | "audit_rights" | "warranty" | "termination_convenience"
  | "minimum_commitment" | "post_termination" | "data_protection" | "liability_cap" | "insurance";
export type ObligationStatus = "to_confirm" | "open" | "met" | "breached" | "waived";
export interface ContractObligation {
  id: string;
  contract_id: string;
  type: ObligationType;
  label: string;
  clause_text: string | null;
  value: Record<string, number | string | boolean>;
  status: ObligationStatus;
  due_date: string | null;
  recurrence: "none" | "monthly" | "annual";
  owner_email: string | null;
  license_id: string | null;
  extracted_by: "legal-bert-cuad" | "regex" | "manual";
  confidence: number | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  events: { kind: string; details: Record<string, unknown>; performed_by: string | null; created_at: string | null }[];
}
export interface SlaCredit {
  id: string;
  obligation_id: string;
  period: string;
  measured_uptime_pct: number;
  credit_pct: number;
  credit_amount: number;
  currency: string;
  status: "proposed" | "expected" | "applied" | "waived";
  recorded_by: string;
  resolved_by: string | null;
  resolved_at: string | null;
  note: string | null;
  created_at: string | null;
}
export interface ContractObligations {
  obligations: ContractObligation[];
  credits: SlaCredit[];
  extracted_at: string | null;
  reading: boolean;
}
export interface ObligationConfirm {
  value?: Record<string, number | string | boolean>;
  owner_email?: string;
  license_id?: string;
  due_date?: string;
}

// --- invoice ledger ---
export type InvoiceMatchStatus = "matched" | "partial" | "variance" | "ambiguous" | "no_match";
export interface InvoiceMatchResult {
  status: InvoiceMatchStatus;
  request_id: string | null;
  amount: number;
  allocations: { line_no: number | null; description: string; quantity: number | null; amount: number }[];
  issues: string[];
  remaining_before: number | null;
  remaining_after: number | null;
  candidates: { request_id: string; status: string; remaining: number; issues: string[] }[];
  notes?: string[];
}
export interface InvoiceMatchRow {
  document_id: string;
  vendor_id: string | null;
  vendor_name: string | null;
  purchase_request_id: string | null;
  invoice_number: string | null;
  status: InvoiceMatchStatus;
  amount: number | null;
  payment_hold: boolean;
  hold_reason: string | null;
  issues: string[];
  created_at: string;
}
export interface RequestLedger {
  request_id: string;
  status: string;
  amount: number;
  invoiced_amount: number;
  remaining_amount: number;
  lines: { line_no: number; description: string; quantity: number; unit_price: number; invoiced_quantity: number }[];
  invoices: {
    document_id: string;
    invoice_number: string | null;
    status: InvoiceMatchStatus;
    amount: number | null;
    payment_hold: boolean;
    hold_reason: string | null;
    created_at: string;
    /** Phase 4: GST and TDS kept with the booked invoice. */
    taxable_value?: number | null;
    gst_amount?: number | null;
    tds_section?: string | null;
    tds_rate_pct?: number | null;
    tds_amount?: number | null;
    net_payable?: number | null;
    tds_notes?: string[];
    paid_at?: string | null;
  }[];
}

// --- learning from corrections ---
export interface VendorLearning {
  vendor_id: string;
  vendor_name: string;
  reviews: number;
  clean: number;
  threshold: number;
  mode: "default" | "relaxed" | "strict";
  hints: { field: string; label: string; support: number; active: boolean }[];
}
export interface LearningStats {
  base_threshold: number;
  min_support: number;
  min_reviews_for_calibration: number;
  vendors: VendorLearning[];
  corrections_by_field: { field: string; count: number }[];
  daily: { day: string; documents: number; needs_review: number; learned: number }[];
}
export interface LookalikeScenario {
  document_id: string;
  impersonated_vendor: string;
  impersonated_vendor_id: string;
  lookalike_name: string;
  invoice_number: string;
  bank_account_last4: string;
}

// --- GST and TDS (feature expansion Phase 4) ---
export type TaxStatus = "ok" | "flagged" | "incomplete" | "reverse_charge" | "import_goods";

export interface TaxCheck {
  status: TaxStatus;
  supply_type: "intra_state" | "inter_state" | "import" | "unknown";
  supplier_gstin: string | null;
  buyer_gstin: string | null;
  place_of_supply: string | null;
  taxable_value: number | null;
  cgst: number | null;
  sgst: number | null;
  igst: number | null;
  gst_total: number | null;
  hsn_codes: { code: string; line_total: number | null }[];
  irn: string | null;
  expected_rate_pct: number | null;
  effective_rate_pct: number | null;
  reverse_charge: boolean;
  gst_payable_inr: number | null;
  itc_eligible: boolean;
  checks: { check: string; ok: boolean; detail: string }[];
  issues: string[];
  notes: string[];
  einvoice: { present: boolean; verified?: boolean | null; mismatches?: string[]; error?: string | null };
}

export interface GstRate {
  code: string;
  description: string;
  category: "hardware" | "software" | "saas" | "services";
  rate_pct: number;
  updated_by: string | null;
  updated_at: string | null;
}

export interface GstInvoice {
  document_id: string;
  invoice_number: string | null;
  invoice_date: string | null;
  vendor_id: string | null;
  vendor_name: string | null;
  currency: string | null;
  total: number | null;
  total_inr: number | null;
  status: TaxStatus | null;
  supply_type: string | null;
  supplier_gstin: string | null;
  taxable_value: number | null;
  gst_total: number | null;
  reverse_charge: boolean;
  gst_payable_inr: number | null;
  itc_eligible: boolean;
  einvoice_verified: boolean | null;
  issues: string[];
}

export interface Gstr2bSummary {
  matched: number;
  value_mismatch: number;
  missing_in_2b: number;
  not_in_books: number;
  entries_in_2b: number;
  itc_at_risk_inr: number;
}

export interface GstSummary {
  month: string;
  period: string;
  invoices: number;
  by_status: Record<TaxStatus, number>;
  input_tax: { cgst: number; sgst: number; igst: number };
  itc_eligible_inr: number;
  reverse_charge_payable_inr: number;
  buyer_gstin: string | null;
  last_2b: (Gstr2bSummary & { id: string; uploaded_at: string }) | null;
}

export interface Gstr2bRow {
  result: "matched" | "value_mismatch" | "missing_in_2b" | "not_in_books";
  supplier_gstin: string | null;
  supplier: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  taxable_value_2b?: number;
  tax_2b?: number;
  taxable_value_books?: number | null;
  tax_books?: number | null;
  document_id: string | null;
  detail: string;
}

export interface Gstr2bUpload {
  id: string;
  period: string;
  buyer_gstin: string | null;
  filename?: string | null;
  uploaded_by?: string;
  uploaded_at?: string;
  summary: Gstr2bSummary;
  rows?: Gstr2bRow[];
}

export interface TdsSection {
  section: string;
  description: string;
  rate_pct: number;
  rate_no_pan_pct: number;
  threshold_single_inr: number | null;
  threshold_annual_inr: number | null;
  above_threshold_only: boolean;
  active: boolean;
  updated_by: string | null;
  updated_at: string | null;
}

export interface VendorTaxProfile {
  vendor_id: string;
  vendor_name: string;
  gstin: string | null;
  country: string | null;
  pan: string | null;
  pan_from_gstin: string | null;
  tds_section: string | null;
  ldc_rate_pct: number | null;
  ldc_valid_until: string | null;
  msme_udyam_number: string | null;
  msme_category: "micro" | "small" | "medium" | null;
  msme_tracked: boolean;
  annual_turnover_inr: number | null;
}

export type VendorTaxInput = Omit<VendorTaxProfile, "vendor_id" | "vendor_name" | "gstin" | "country" | "pan_from_gstin" | "msme_tracked">;

export interface TdsRegisterEntry {
  document_id: string;
  invoice_number: string | null;
  invoice_date: string;
  quarter: string;
  vendor_id: string | null;
  vendor_name: string | null;
  pan: string | null;
  request_id: string | null;
  amount: number | null;
  taxable_value: number | null;
  tds_section: string;
  tds_rate_pct: number | null;
  tds_base: number | null;
  tds_amount: number | null;
  net_payable: number | null;
  notes: string[];
  paid_at: string | null;
}

export interface TdsRegister {
  fy: string;
  invoices: TdsRegisterEntry[];
  totals: { quarter: string; section: string; invoices: number; base: number; tds: number }[];
  tds_total: number;
}

export interface MsmeDeadline {
  document_id: string;
  invoice_number: string | null;
  vendor_id: string;
  vendor_name: string;
  msme_category: "micro" | "small";
  udyam_number: string | null;
  request_id: string | null;
  amount: number | null;
  net_payable: number | null;
  paid_at: string | null;
  paid_by: string | null;
  acceptance_date: string;
  due_date: string;
  days_left: number;
  status: "ok" | "due_soon" | "overdue" | "paid";
}
