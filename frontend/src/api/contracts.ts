import { api, downloadFile } from "./client";
import type {
  Contract, ContractObligation, ContractObligations, ContractTemplate, ObligationConfirm, ObligationType, SlaCredit,
} from "@/types/api";

/** One contract on the Control Panel's e-signature list. */
export interface EsignDocument {
  contract_id: string;
  status: string;
  status_label: string;
  version: number | null;
  template_used: string | null;
  vendor_name: string | null;
  request_id: string | null;
  amount: number | null;
  currency: string | null;
  generated_at: string | null;
  sent_at: string | null;
  signer_email: string | null;
  provider: string | null;
  signed_at: string | null;
  signed_by: string | null;
  esign_provider_ref?: string | null;
  unsigned_pdf: string;
  signed_pdf: string | null;
  certificate: string | null;
}

export const contractsApi = {
  /** Admin: every contract's e-signature state with its PDF links. */
  esignDocuments: (status?: string) =>
    api.get<EsignDocument[]>(`/contracts/esign/documents?limit=200${status ? `&status=${status}` : ""}`),
  list: (limit = 200, purchase_request_id?: string) =>
    api.get<Contract[]>(
      `/contracts/?limit=${limit}${purchase_request_id ? `&purchase_request_id=${encodeURIComponent(purchase_request_id)}` : ""}`,
    ),
  get: (id: string) => api.get<Contract>(`/contracts/${id}`),
  renewalsDue: (withinDays = 60) => api.get<Contract[]>(`/contracts/renewals-due?within_days=${withinDays}`),
  generate: (purchase_request_id: string, template_name: ContractTemplate) =>
    api.post<Contract>("/contracts/generate", { purchase_request_id, template_name }),
  sendForSignature: (id: string, signer_email?: string, provider = "documenso") =>
    api.post<Contract>(`/contracts/${id}/send-for-signature`, { signer_email, provider }),
  downloadDocument: (id: string) => downloadFile(`/contracts/${id}/document`, `contract-${id.slice(0, 8)}.pdf`),
  downloadSigned: (id: string) =>
    downloadFile(`/contracts/${id}/signed-document`, `contract-${id.slice(0, 8)}-signed.pdf`),
  signContract: (
    id: string,
    data: {
      signer_name: string;
      signer_email: string;
      signer_designation?: string | null;
      signature_data?: string;
      legal_consent: boolean;
      /** BR-6: required for a High-risk or unscored vendor */
      risk_acknowledged?: boolean;
    }
  ) => api.post<Contract>(`/contracts/${id}/sign`, data),
  getCertificate: (id: string) =>
    api.get<Record<string, unknown>>(`/contracts/${id}/signature-certificate`),
  simulateSign: (id: string) =>
    api.post<Contract>(`/contracts/${id}/sign-simulated`, {}),

  // Phase 2: obligations a signed contract commits the parties to.
  obligations: (id: string) => api.get<ContractObligations>(`/contracts/${id}/obligations`),
  obligationsForLicense: (licenseId: string) =>
    api.get<ContractObligation[]>(`/contracts/obligations/by-license/${licenseId}`),
  addObligation: (id: string, data: ObligationConfirm & { type: ObligationType; clause_text?: string }) =>
    api.post<ContractObligation>(`/contracts/${id}/obligations`, data),
  rereadObligations: (id: string) => api.post<{ added: string[] }>(`/contracts/${id}/obligations/extract`, {}),
  confirmObligation: (obligationId: string, data: ObligationConfirm) =>
    api.patch<ContractObligation>(`/contracts/obligations/${obligationId}/confirm`, data),
  obligationAction: (obligationId: string, action: "met" | "waived" | "reopened" | "breach", note?: string) =>
    api.post<ContractObligation>(`/contracts/obligations/${obligationId}/actions`, { action, note }),
  recordDowntime: (obligationId: string, period: string, measured_uptime_pct: number, note?: string) =>
    api.post<ContractObligation & { credit: SlaCredit | null }>(`/contracts/obligations/${obligationId}/downtime`,
      { period, measured_uptime_pct, note }),
  settleCredit: (creditId: string, status: "expected" | "applied" | "waived", note?: string) =>
    api.post<SlaCredit>(`/contracts/sla-credits/${creditId}`, { status, note }),
};
