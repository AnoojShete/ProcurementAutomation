import { api } from "./client";
import type { CreatePurchaseRequestBody, GoodsReceipt, InboxItem, PurchaseRequest, RequestReceipts } from "@/types/api";

export const requestsApi = {
  list: (limit = 200) => api.get<PurchaseRequest[]>(`/requests/?limit=${limit}`),
  get: (id: string) => api.get<PurchaseRequest>(`/requests/${id}`),
  create: (body: CreatePurchaseRequestBody) => api.post<PurchaseRequest>("/requests/", body),
  approve: (id: string, decided_by: string, comments?: string) =>
    api.post<PurchaseRequest>(`/requests/${id}/approve`, { decided_by, comments }),
  reject: (id: string, decided_by: string, comments?: string) =>
    api.post<PurchaseRequest>(`/requests/${id}/reject`, { decided_by, comments }),
  /** Goods/licences arrived: ordered -> fulfilled (activates licences, releases stock). */
  receive: (id: string) => api.post<PurchaseRequest>(`/requests/${id}/receive`, {}),
  // Phase 3: deliveries (partial goods receipts).
  receipts: (id: string) => api.get<RequestReceipts>(`/requests/${id}/receipts`),
  recordReceipt: (id: string, lines: { line_no: number; quantity: number; asset_tags?: string[] }[], notes?: string) =>
    api.post<{ receipt: GoodsReceipt; outcome: string; request: PurchaseRequest }>(`/requests/${id}/receipts`, { lines, notes }),
  inbox: (approverRole: string) => api.get<InboxItem[]>(`/inbox/${encodeURIComponent(approverRole)}`),
};
