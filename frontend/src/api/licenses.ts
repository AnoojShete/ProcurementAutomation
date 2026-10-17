import { api } from "./client";
import type {
  ApiEnvelope,
  InventorySnapshot,
  UsageHistoryEntry,
  LicenseAnomalySummary,
  ReclaimHistoryEntry,
} from "@/types/api";

export const licensesApi = {
  list: () => api.get<InventorySnapshot>("/inventory/"),
  anomalySummary: () => api.get<LicenseAnomalySummary>("/licenses/anomaly-summary"),
  usageHistory: (id: string, days = 90) =>
    api.get<UsageHistoryEntry[]>(`/licenses/${id}/usage-history?days=${days}`),
  reclaimHistory: (id: string) =>
    api.get<ReclaimHistoryEntry[]>(`/licenses/${id}/reclaim-history`),
  markReviewed: (id: string) =>
    api.post<{ status: string; license_id: string; reclaim_cooldown_until: string }>(
      `/licenses/${id}/mark-reviewed`,
      {},
    ),
};
