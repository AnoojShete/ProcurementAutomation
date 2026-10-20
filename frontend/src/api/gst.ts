import { api } from "./client";
import type { GstInvoice, GstRate, GstSummary, Gstr2bUpload } from "@/types/api";

/** GST checks, rates and GSTR-2B reconciliation (document-vendor-agent, Phase 4). */
export const gstApi = {
  summary: (month?: string) => api.get<GstSummary>(`/gst/summary${month ? `?month=${month}` : ""}`),
  invoices: (month?: string, status?: string) => {
    const q = new URLSearchParams(Object.entries({ month, status }).filter(([, v]) => v) as [string, string][]);
    return api.get<GstInvoice[]>(`/gst/invoices${q.toString() ? `?${q}` : ""}`);
  },
  rates: () => api.get<GstRate[]>("/gst/rates"),
  saveRate: (rate: Omit<GstRate, "updated_by" | "updated_at">) => api.request<GstRate>(`/gst/rates/${rate.code}`, "PUT", rate),
  uploads: () => api.get<Gstr2bUpload[]>("/gst/2b"),
  upload: (id: string) => api.get<Gstr2bUpload>(`/gst/2b/${id}`),
  reconcile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.upload<Gstr2bUpload>("/gst/2b", form);
  },
};
