import { api } from "./client";
import type { PurchaseRequest, RfqCriterion, RfqDetail, RfqInput, RfqResponseInput, RfqSummary } from "@/types/api";

/** Phase 3b: RFQ events (approval-inventory-agent). */
export const sourcingApi = {
  list: () => api.get<RfqSummary[]>("/rfqs/"),
  criteria: () => api.get<{ criteria: RfqCriterion[]; default: Record<RfqCriterion, number> }>("/rfqs/criteria"),
  get: (id: string) => api.get<RfqDetail>(`/rfqs/${id}`),
  create: (body: RfqInput) => api.post<RfqDetail>("/rfqs/", body),
  recordResponse: (id: string, body: RfqResponseInput) => api.post<RfqDetail>(`/rfqs/${id}/responses`, body),
  extend: (id: string, deadline: string) => api.post<RfqDetail>(`/rfqs/${id}/extend`, { deadline }),
  close: (id: string) => api.post<RfqDetail>(`/rfqs/${id}/close`, {}),
  nextRound: (id: string, vendor_ids: string[], deadline: string) =>
    api.post<RfqDetail>(`/rfqs/${id}/rounds`, { vendor_ids, deadline }),
  award: (id: string, response_id: string) =>
    api.post<RfqDetail & { request: PurchaseRequest }>(`/rfqs/${id}/award`, { response_id }),
  cancel: (id: string, reason: string) => api.post<RfqDetail>(`/rfqs/${id}/cancel`, { reason }),
};
