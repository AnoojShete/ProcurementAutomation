import { api } from "./client";
import type {
  DriftCheckResult,
  OffboardResult,
  VendorPaymentChange,
  VendorRisk,
  VendorSummary,
} from "@/types/api";

export interface VendorProfileInput {
  name: string;
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
  riskSignals: (vendorId: string) => api.get<RiskSignals>(`/vendors/${vendorId}/risk-signals`),
  updateRiskSignals: (vendorId: string, body: Partial<ComplianceSignals>) =>
    api.patch<{ risk: VendorRisk; signals: RiskSignals }>(`/vendors/${vendorId}/risk-signals`, body),
  validateOnboarding: (profile: VendorProfileInput) => api.post<ProfileCheck>("/vendors/onboard/validate", profile),
  onboard: (profile: VendorProfileInput) =>
    api.post<{ id: string; name: string; payment_details_pending_verification: boolean }>("/vendors/onboard", profile),
  list: (limit = 200) => api.get<VendorSummary[]>(`/vendors/?limit=${limit}`),
  risk: (vendorId: string) => api.get<VendorRisk>(`/vendors/${vendorId}/risk`),
  recomputeRisk: (vendorId: string) => api.post<VendorRisk>(`/vendors/${vendorId}/risk/recompute`),
  logOutcome: (vendorId: string, actual_incident_occurred: boolean, logged_by: string, notes?: string) =>
    api.post(`/vendors/${vendorId}/log-outcome`, { actual_incident_occurred, logged_by, notes }),
  driftCheck: () => api.get<DriftCheckResult>("/vendors/risk-model/drift-check"),
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
};
