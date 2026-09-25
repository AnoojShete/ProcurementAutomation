import { api } from "./client";
import type { BusinessRule, BusinessRuleHistory } from "@/types/api";

export interface HistoryFilterParams {
  category?: string;
  rule_key?: string;
  changed_by?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export const businessRulesApi = {
  getAll: () => api.get<Record<string, BusinessRule[]>>("/admin/business-rules"),
  getByKey: (ruleKey: string) =>
    api.get<{ rule: BusinessRule; history: BusinessRuleHistory[] }>(`/admin/business-rules/${encodeURIComponent(ruleKey)}`),
  updateRule: (ruleKey: string, newValue: unknown, justification: string) =>
    api.patch<BusinessRule>(`/admin/business-rules/${encodeURIComponent(ruleKey)}`, {
      new_value: newValue,
      justification,
    }),
  resetRule: (ruleKey: string, justification: string) =>
    api.post<BusinessRule>(`/admin/business-rules/${encodeURIComponent(ruleKey)}/reset`, {
      justification,
    }),
  getHistory: (params: HistoryFilterParams = {}) => {
    const q = new URLSearchParams();
    if (params.category) q.set("category", params.category);
    if (params.rule_key) q.set("rule_key", params.rule_key);
    if (params.changed_by) q.set("changed_by", params.changed_by);
    if (params.date_from) q.set("date_from", params.date_from);
    if (params.date_to) q.set("date_to", params.date_to);
    if (params.limit) q.set("limit", String(params.limit));
    if (params.offset) q.set("offset", String(params.offset));
    const qs = q.toString();
    return api.get<BusinessRuleHistory[]>(`/admin/business-rules/history${qs ? `?${qs}` : ""}`);
  },
};
