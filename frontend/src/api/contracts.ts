import { api } from "./client";
import type { Contract, ContractTemplate } from "@/types/api";

export const contractsApi = {
  list: (limit = 200) => api.get<Contract[]>(`/contracts/?limit=${limit}`),
  get: (id: string) => api.get<Contract>(`/contracts/${id}`),
  renewalsDue: (withinDays = 60) => api.get<Contract[]>(`/contracts/renewals-due?within_days=${withinDays}`),
  generate: (purchase_request_id: string, template_name: ContractTemplate) =>
    api.post<Contract>("/contracts/generate", { purchase_request_id, template_name }),
  sendForSignature: (id: string, signer_email?: string) =>
    api.post<Contract>(`/contracts/${id}/send-for-signature`, { signer_email }),
};
