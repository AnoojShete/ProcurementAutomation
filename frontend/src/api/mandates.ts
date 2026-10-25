import { api } from "./client";

export interface SigningMandate {
  id: string;
  user_id: string;
  user_email: string;
  user_name: string;
  mandate_text: string;
  mandate_text_hash: string;
  mandate_text_version: string;
  status: "active" | "revoked" | "expired";
  valid_from: string;
  valid_until: string;
  created_at: string;
  revoked_at?: string | null;
  revocation_reason?: string | null;
}

export interface MandateTemplate {
  template_text: string;
  version: string;
}

export const mandatesApi = {
  getTemplate: () => api.get<MandateTemplate>("/mandates/template"),
  getActive: () => api.get<{ active: boolean; mandate: SigningMandate | null }>("/mandates/active"),
  create: (password: string, mandate_text_version: string) =>
    api.post<SigningMandate>("/mandates", { password, mandate_text_version }),
  revoke: (id: string, reason?: string) =>
    api.post<SigningMandate>(`/mandates/${id}/revoke`, { reason }),
  getRecentAutoSigned: () => api.get<any[]>("/mandates/recent-auto-signed"),
};
