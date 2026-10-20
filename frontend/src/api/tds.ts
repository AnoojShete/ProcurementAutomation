import { api } from "./client";
import type { MsmeDeadline, TdsRegister, TdsSection, VendorTaxInput, VendorTaxProfile } from "@/types/api";

/** TDS sections, vendor tax profiles, the TDS register and MSME deadlines
 * (approval-inventory-agent, Phase 4). */
export const tdsApi = {
  sections: () => api.get<TdsSection[]>("/tds/sections"),
  saveSection: (section: string, body: Omit<TdsSection, "section" | "updated_by" | "updated_at">) =>
    api.request<TdsSection>(`/tds/sections/${encodeURIComponent(section)}`, "PUT", body),
  vendor: (vendorId: string) => api.get<VendorTaxProfile>(`/tds/vendors/${vendorId}`),
  saveVendor: (vendorId: string, body: VendorTaxInput) => api.request<VendorTaxProfile>(`/tds/vendors/${vendorId}`, "PUT", body),
  register: (fy?: string) => api.get<TdsRegister>(`/tds/register${fy ? `?fy=${fy}` : ""}`),
  msme: (includePaid = false) => api.get<MsmeDeadline[]>(`/tds/msme${includePaid ? "?include_paid=true" : ""}`),
  recordPaid: (documentId: string, body: { paid_on?: string; reference?: string }) =>
    api.post<{ document_id: string; paid_at: string; paid_by: string }>(`/tds/invoices/${documentId}/paid`, body),
};
