import { api } from "./client";

export interface PrivacyProcessingRecord {
  id: string;
  activity: string;
  purpose: string;
  data_categories: string;
  data_subjects: string;
  lawful_basis: string;
  retention_rule_key: string;
  recipients_processors: string;
  storage_location: string;
  reviewed_on?: string | null;
}

export interface PrivacyRequest {
  id: string;
  type: "access" | "rectification" | "erasure" | "restriction" | "objection";
  subject_email_hash: string;
  identity_verified_by: string;
  received_at: string;
  due_at: string;
  days_remaining: number;
  status: "pending" | "processing" | "completed" | "refused";
  handler: string;
  outcome?: string | null;
  outcome_reason?: string | null;
  second_admin_approver?: string | null;
}

export interface DataProcessor {
  id: string;
  name: string;
  purpose: string;
  country: string;
  dpa_reference?: string | null;
  transfer_mechanism_note?: string | null;
  reviewed_on?: string | null;
}

export interface PrivacyIncident {
  id: string;
  detected_at: string;
  hours_since_detection: number;
  description: string;
  data_categories?: string | null;
  subjects_affected_estimate: number;
  contained_at?: string | null;
  authority_notified_at?: string | null;
  individuals_notified_at?: string | null;
  notes?: string | null;
  gdpr_guidance: string;
}

export interface DomainHealthResult {
  domain: string;
  spf: { status: string; record: string };
  dmarc: { status: string; policy: string; record: string };
  dkim: { status: string; selector: string; key_size: number };
  tls_enforced: boolean;
  checked_at: string;
}

export interface PlaceholderClass {
  name: string;
  classification: "public" | "internal" | "personal" | "restricted";
  description: string;
}

export const privacyApi = {
  processingRecords: () => api.get<{ data: PrivacyProcessingRecord[] }>("/admin/privacy/processing-records"),
  exportProcessingRecordsCsvUrl: () => "/api/admin/privacy/processing-records/export",

  requests: () => api.get<{ data: PrivacyRequest[] }>("/admin/privacy/requests"),
  createRequest: (data: { type: string; subject_email: string; identity_verified_by: string; notes?: string }) =>
    api.post<{ data: { id: string; type: string; due_at: string; status: string } }>("/admin/privacy/requests", data),
  exportDsrUrl: (requestId: string, subjectEmail: string) =>
    `/api/admin/privacy/requests/${encodeURIComponent(requestId)}/export?subject_email=${encodeURIComponent(subjectEmail)}`,
  eraseRequest: (requestId: string, data: { second_admin_email: string; subject_email: string; reason: string }) =>
    api.post<{ data: any }>(`/admin/privacy/requests/${encodeURIComponent(requestId)}/erase`, data),

  processors: () => api.get<{ data: DataProcessor[] }>("/admin/privacy/processors"),
  incidents: () => api.get<{ data: PrivacyIncident[] }>("/admin/privacy/incidents"),
  createIncident: (data: { description: string; data_categories?: string; subjects_affected_estimate?: number; notes?: string }) =>
    api.post<{ data: { id: string; detected_at: string } }>("/admin/privacy/incidents", data),

  domainHealth: () => api.get<{ data: DomainHealthResult }>("/admin/privacy/domain-health"),
  placeholders: () => api.get<{ data: PlaceholderClass[] }>("/notifications/placeholders"),
};
