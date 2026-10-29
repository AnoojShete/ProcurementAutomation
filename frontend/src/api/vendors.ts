import { api } from "./client";
import type {
  DriftCheckResult,
  OffboardResult,
  VendorPaymentChange,
  VendorRisk,
  VendorScorecard,
  VendorSummary,
  ScorecardExplanation,
  RemediationPlan,
  WhatIfResult,
  RiskHistoryEntry,
  VendorDispute,
  VendorEvidence,
  VendorEvidenceCreate,
  RulesetResponse,
  DryRunReport,
  MonitoringReport,
} from "@/types/api";

export interface VendorProfileInput {
  name: string;
  country?: string;
  inherent_tier?: "low" | "moderate" | "high" | "critical" | string;
  swift_bic?: string;
  bank_name?: string;
  website?: string;
  contact_email?: string;
  contact_phone?: string;
  address?: string;
  category?: string;
  gstin?: string;
  bank_account_number?: string;
  routing_code?: string;
  payment_beneficiary_name?: string;
  confirm?: string[];
  no_gstin_reason?: string;
}

export interface VendorClearance {
  cleared: boolean;
  purpose: string;
  rating_status: "not_rated" | "provisional" | "assessed";
  final_band: "Low" | "Medium" | "High" | "Unrated";
  points_band: "Low" | "Medium" | "High";
  risk_score: number | null;
  blocked_by: string[];
  overrides_active: string[];
  required_signals_missing: string[];
  post_score_decision: "approved" | "approved_with_conditions" | "risk_accepted" | "rejected" | null;
  decision_expires_at: string | null;
  conditions: Array<{ id: string; text: string; due_date?: string; status: string; overdue: boolean }>;
  reasons: string[];
}

export interface ProfileIssue {
  field: string;
  message: string;
  code?: string;
  vendor_id?: string;
}

export interface ProfileCheck {
  ok: boolean;
  errors: ProfileIssue[];
  warnings: ProfileIssue[];
  needs_confirmation: string[];
}

export interface ComplianceSignals {
  security_cert_flag: boolean | null;
  geo_risk_flag: boolean | null;
  breach_disclosure_count: number | null;
  financial_stability_score: number | null;
}

export interface RiskSignals {
  platform: {
    vendor_tenure_months: number | null;
    on_time_delivery_rate: number | null;
    deliveries: number;
    deliveries_on_time: number;
    expected_delivery_days: number;
  };
  compliance: ComplianceSignals;
  updated_at: string | null;
}

export interface SanctionsMatch {
  entity_id: string;
  listed_name: string;
  matched_name: string;
  score: number;
  countries: string;
  lists: string;
}

export interface SanctionsScreening {
  id: string;
  status: "clear" | "potential_match" | "cleared";
  screened_at: string | null;
  list_version: string | null;
  screened_name: string;
  matches: SanctionsMatch[];
  threshold: number | null;
  screened_by: string | null;
  justification: string | null;
}

export interface SanctionsState {
  list: { available: boolean; version?: string; entries?: number };
  latest: SanctionsScreening | null;
}

export const vendorsApi = {
  sanctions: (vendorId: string) => api.get<SanctionsState>(`/vendors/${vendorId}/sanctions`),
  screenSanctions: (vendorId: string) =>
    api.post<{ screening: SanctionsScreening; risk: VendorRisk }>(`/vendors/${vendorId}/screen-sanctions`),
  clearSanctionsFlag: (vendorId: string, justification: string) =>
    api.post<{ screening: SanctionsScreening; risk: VendorRisk }>(`/vendors/${vendorId}/clear-sanctions-flag`, { justification }),
  validateOnboarding: (profile: VendorProfileInput) => api.post<ProfileCheck>("/vendors/onboard/validate", profile),
  onboard: (profile: VendorProfileInput) =>
    api.post<{ id: string; name: string; payment_details_pending_verification: boolean }>("/vendors/onboard", profile),
  list: (limit = 200) => api.get<VendorSummary[]>(`/vendors/?limit=${limit}`),
  risk: (vendorId: string) => api.get<VendorRisk>(`/vendors/${vendorId}/risk`),
  /** Phase 3c: on-time, invoice accuracy, RFQ response rate, SLA breaches. */
  scorecard: (vendorId: string) => api.get<VendorScorecard>(`/vendors/${vendorId}/scorecard`),
  recomputeRisk: (vendorId: string) => api.post<VendorRisk>(`/vendors/${vendorId}/risk/recompute`),
  update: (vendorId: string, partial: Partial<VendorProfileInput>) =>
    api.patch<VendorSummary>(`/vendors/${vendorId}`, partial),
  offboard: (vendorId: string, offboarded_by: string, reason: string) =>
    api.post<OffboardResult>(`/vendors/${vendorId}/offboard`, { offboarded_by, reason }),
  paymentChanges: (vendorId: string) => api.get<VendorPaymentChange[]>(`/vendors/${vendorId}/payment-changes`),
  verifyPaymentChange: (
    vendorId: string,
    change_request_id: string,
    channel: string,
    approve: boolean,
    notes?: string,
  ) =>
    api.post<VendorPaymentChange>(`/vendors/${vendorId}/verify-payment-change`, {
      change_request_id,
      channel,
      approve,
      notes,
    }),
  explanation: (vendorId: string) => api.get<ScorecardExplanation>(`/vendors/${vendorId}/risk/explanation`),
  clearance: (vendorId: string, purpose = "purchase", spendAmount?: number, contractId?: string) =>
    api.get<VendorClearance>(
      `/vendors/${vendorId}/clearance?purpose=${purpose}${spendAmount !== undefined ? `&spend_amount=${spendAmount}` : ""}${contractId ? `&contract_id=${contractId}` : ""}`
    ),
  recordDecision: (vendorId: string, body: { decision: string; justification: string; conditions?: any[]; expires_in_days?: number }) =>
    api.post(`/vendors/${vendorId}/decisions`, body),
  remediationPlan: (vendorId: string, audience: "vendor" | "buyer" = "buyer") =>
    api.get<RemediationPlan>(`/vendors/${vendorId}/risk/remediation-plan?audience=${audience}`),
  whatIf: (vendorId: string, simulate_resolved_rules: string[]) =>
    api.post<WhatIfResult>(`/vendors/${vendorId}/risk/what-if`, { simulate_resolved_rules }),
  history: (vendorId: string) => api.get<RiskHistoryEntry[]>(`/vendors/${vendorId}/risk/history`),
  disputes: (vendorId: string) => api.get<VendorDispute[]>(`/vendors/${vendorId}/risk/disputes`),
  raiseDispute: (vendorId: string, body: { rule_result_id: string; reason: string; evidence_id?: string }) =>
    api.post<VendorDispute>(`/vendors/${vendorId}/risk/disputes`, body),
  replay: (vendorId: string, scoreId?: string) =>
    api.post<{ match: boolean; replayed_score: any; replayed_rule_results: any[] }>(
      `/vendors/${vendorId}/risk/replay${scoreId ? `?score_id=${scoreId}` : ""}`
    ),
  evidence: (vendorId: string) => api.get<VendorEvidence[]>(`/vendors/${vendorId}/evidence`),
  addEvidence: (vendorId: string, body: VendorEvidenceCreate) =>
    api.post<VendorEvidence>(`/vendors/${vendorId}/evidence`, body),
};

export const rulesetsApi = {
  active: () => api.get<RulesetResponse>("/admin/risk-rulesets/active"),
  draft: () => api.get<RulesetResponse>("/admin/risk-rulesets/draft"),
  saveDraft: (definition: any) => api.post<RulesetResponse>("/admin/risk-rulesets/draft", { definition }),
  validate: (definition: any) => api.post<{ valid: boolean; errors: string[] }>("/admin/risk-rulesets/validate", { definition }),
  dryRun: (definition: any, sample_size = 100) =>
    api.post<DryRunReport>("/admin/risk-rulesets/dry-run", { definition, sample_size }),
  activate: (definition: any, change_justification: string) =>
    api.post<RulesetResponse>("/admin/risk-rulesets/activate", { definition, change_justification }),
  history: () => api.get<RulesetResponse[]>("/admin/risk-rulesets/history"),
  monitoring: (lookback_days = 30) => api.get<MonitoringReport>(`/admin/risk-rulesets/monitoring?lookback_days=${lookback_days}`),
};
