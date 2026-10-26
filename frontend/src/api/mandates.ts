import { api } from "./client";

// Shapes match contract-risk-agent app/api/mandates.py.
export interface SigningMandate {
  id: string;
  user_id: string;
  role: string;
  scope: string;
  max_amount_per_contract: number;
  valid_from: string;
  valid_until: string;
  mandate_text_version: string;
  mandate_text_sha256: string;
  accepted_at: string;
  status: "active" | "revoked" | "expired";
  is_active: boolean;
  mandate_text?: string | null;
}

export interface MandateTemplate {
  version: string;
  template: string;
  sample_text: string;
  sample_sha256: string;
  is_eligible: boolean;
  max_allowed_amount: number;
  max_allowed_days: number;
}

export interface AutoSignedContract {
  contract_id: string;
  purchase_request_id: string | null;
  vendor_name: string;
  template: string | null;
  signed_at: string | null;
  signed_by: string | null;
  approval_channel: string | null;
  mandate_id: string | null;
  bulk_batch_id: string | null;
}

export const mandatesApi = {
  getTemplate: () => api.get<MandateTemplate>("/mandates/template"),
  getActive: () => api.get<SigningMandate | null>("/mandates/active"),
  create: (password: string, max_amount_per_contract: number, validity_days: number) =>
    api.post<SigningMandate>("/mandates", { password, max_amount_per_contract, validity_days }),
  revoke: (id: string) => api.post<{ id: string; status: string }>(`/mandates/${id}/revoke`),
  getRecentAutoSigned: () => api.get<AutoSignedContract[]>("/mandates/recent-auto-signed"),
};
