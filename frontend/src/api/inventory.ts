import { api } from "./client";
import type { InventorySnapshot, ReorderStatus } from "@/types/api";

export const inventoryApi = {
  get: (params?: { category?: string; search?: string }) => {
    const qs = new URLSearchParams();
    if (params?.category) qs.set("category", params.category);
    if (params?.search) qs.set("search", params.search);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return api.get<InventorySnapshot>(`/inventory/${suffix}`);
  },
  /** null = back to the business-rule default */
  setReorderSettings: (itemId: string, reorder_point: number | null, reorder_quantity: number | null) =>
    api.patch<{ id: string; sku: string; reorder: ReorderStatus }>(`/inventory/${itemId}/reorder-settings`, {
      reorder_point,
      reorder_quantity,
    }),
};
