import { api } from "./client";
import type { CatalogItem, CatalogItemInput } from "@/types/api";

/** Phase 3a: the IT catalog (approval-inventory-agent). */
export const catalogApi = {
  list: (opts: { q?: string; includeUnavailable?: boolean } = {}) => {
    const p = new URLSearchParams();
    if (opts.q) p.set("q", opts.q);
    if (opts.includeUnavailable) p.set("include_unavailable", "true");
    return api.get<CatalogItem[]>(`/catalog/${p.size ? `?${p}` : ""}`);
  },
  get: (id: string) => api.get<CatalogItem>(`/catalog/${id}`),
  create: (body: CatalogItemInput) => api.post<CatalogItem>("/catalog/", body),
  update: (id: string, body: Partial<CatalogItemInput> & { active?: boolean; clear_valid_until?: boolean }) =>
    api.patch<CatalogItem>(`/catalog/${id}`, body),
};
