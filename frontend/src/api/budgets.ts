import { api } from "./client";
import type { Budget, BudgetDetail, BudgetInput, BudgetPeriod, RequestBudgetLine } from "@/types/api";

/** Budgets per department × IT category × fiscal period (approval-inventory-agent). */
export const budgetsApi = {
  period: () => api.get<BudgetPeriod>("/budgets/period"),
  list: (params: { fiscal_year?: string; period?: string } = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return api.get<Budget[]>(`/budgets/${q.toString() ? `?${q}` : ""}`);
  },
  get: (id: string) => api.get<BudgetDetail>(`/budgets/${id}`),
  create: (body: BudgetInput) => api.post<Budget>("/budgets/", body),
  update: (id: string, body: { amount_inr?: number; owner_email?: string | null }) =>
    api.patch<Budget>(`/budgets/${id}`, body),
  remove: (id: string) => api.request<{ deleted: string }>(`/budgets/${id}`, "DELETE"),
  importRows: (rows: BudgetInput[]) =>
    api.post<{ created: number; updated: number; rows: number }>("/budgets/import", { rows }),
  /** The budget line of one request (same visibility as the request). */
  forRequest: (requestId: string) => api.get<RequestBudgetLine>(`/requests/${requestId}/budget`),
};
