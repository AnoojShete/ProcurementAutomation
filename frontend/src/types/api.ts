// Mirrors the Pydantic response models read directly from each service's
// app/schemas.py — see the plan doc for the file-by-file source. Keep these
// in sync with the backend; never add a field the backend doesn't return.

export type Role = "requester" | "approver" | "finance" | "admin";

export interface CurrentUser {
  id: string;
  email: string;
  role: Role;
}

// --- auth-service ---
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
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

export interface LicenseItem {
  id: string;
  vendor_id: string | null;
  app_name: string;
  total_seats: number;
  active_seats_30d: number;
  active_seats_60d: number;
  active_seats_90d: number;
  utilisation_score: number;
  cost_per_seat: number | null;
  period_end: string | null;
  status: string;
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

export interface ApiEnvelope<T> {
  data: T;
  meta?: Record<string, unknown>;
}

export interface ApiErrorEnvelope {
  error: { code: string; message: string };
}
