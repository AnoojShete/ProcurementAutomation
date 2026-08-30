import { api } from "./client";
import type { InventorySnapshot } from "@/types/api";

export const inventoryApi = {
  get: (params?: { category?: string; search?: string }) => {
    const qs = new URLSearchParams();
    if (params?.category) qs.set("category", params.category);
    if (params?.search) qs.set("search", params.search);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return api.get<InventorySnapshot>(`/inventory/${suffix}`);
  },
};
