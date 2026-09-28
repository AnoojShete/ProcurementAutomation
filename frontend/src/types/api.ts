// Mirrors the Pydantic response models read directly from each service's
// app/schemas.py — see the plan doc for the file-by-file source. Keep these
// in sync with the backend; never add a field the backend doesn't return.

export type Role = "requester" | "approver" | "finance" | "admin";

export interface CurrentUser {
  id: string;
  email: string;
  role: Role;
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
export type SpendTier = "auto" | "manager" | "manager+finance";
export type RequestStatus =
  | "pending_approval"
  | "approved"
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
  sla_deadline: string | null;
  items: Record<string, unknown>[] | null;
  is_backordered: boolean;
  created_at: string | null;
  updated_at: string | null;
  approval_history: ApprovalHistoryEntry[] | null;
}

export interface CreatePurchaseRequestBody {
  request_type: RequestType;
  requested_by: string;
  department: string;
  vendor_id?: string | null;
  amount: number;
  currency?: string;
  items?: Record<string, unknown>[] | null;
  comments?: string | null;
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
export type DocumentType = "po" | "invoice" | "quote";
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
  portal_access_revoked: boolean;
  risk_band: RiskBand | null;
  risk_score: number | null;
  created_at: string | null;
}

export interface RiskFactor {
  feature: string;
  contribution: number;
}

export interface VendorRisk {
  vendor_id: string;
  risk_band: RiskBand;
  risk_score: number;
  top_factors: RiskFactor[];
  model_version: string | null;
  scored_at: string | null;
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
  signed_at: string;
  signature_seal: string;
  legal_framework: string;
  consent_acknowledged: boolean;
  ip_address?: string | null;
  user_agent?: string | null;
  signature_image?: string | null;
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
  reconciliation_status: string | null;
  contract_text: string | null;
  signature_certificate?: SignatureCertificate | null;
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
