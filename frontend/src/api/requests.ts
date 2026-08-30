import { api } from "./client";
import type { CreatePurchaseRequestBody, InboxItem, PurchaseRequest } from "@/types/api";

export const requestsApi = {
  list: (limit = 200) => api.get<PurchaseRequest[]>(`/requests/?limit=${limit}`),
  get: (id: string) => api.get<PurchaseRequest>(`/requests/${id}`),
  create: (body: CreatePurchaseRequestBody) => api.post<PurchaseRequest>("/requests/", body),
  approve: (id: string, decided_by: string, comments?: string) =>
    api.post<PurchaseRequest>(`/requests/${id}/approve`, { decided_by, comments }),
  reject: (id: string, decided_by: string, comments?: string) =>
    api.post<PurchaseRequest>(`/requests/${id}/reject`, { decided_by, comments }),
  inbox: (approverRole: string) => api.get<InboxItem[]>(`/inbox/${encodeURIComponent(approverRole)}`),
};
