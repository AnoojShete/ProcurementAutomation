import { api } from "./client";
import type {
  DriftCheckResult,
  OffboardResult,
  VendorPaymentChange,
  VendorRisk,
  VendorSummary,
} from "@/types/api";

export const vendorsApi = {
  list: (limit = 200) => api.get<VendorSummary[]>(`/vendors/?limit=${limit}`),
  risk: (vendorId: string) => api.get<VendorRisk>(`/vendors/${vendorId}/risk`),
  recomputeRisk: (vendorId: string) => api.post<VendorRisk>(`/vendors/${vendorId}/risk/recompute`),
  logOutcome: (vendorId: string, actual_incident_occurred: boolean, logged_by: string, notes?: string) =>
    api.post(`/vendors/${vendorId}/log-outcome`, { actual_incident_occurred, logged_by, notes }),
  driftCheck: () => api.get<DriftCheckResult>("/vendors/risk-model/drift-check"),
  offboard: (vendorId: string, offboarded_by: string, reason: string) =>
    api.post<OffboardResult>(`/vendors/${vendorId}/offboard`, { offboarded_by, reason }),
  paymentChanges: (vendorId: string) => api.get<VendorPaymentChange[]>(`/vendors/${vendorId}/payment-changes`),
  verifyPaymentChange: (
    vendorId: string,
    change_request_id: string,
    verified_by: string,
    channel: string,
    approve: boolean,
    notes?: string,
  ) =>
    api.post<VendorPaymentChange>(`/vendors/${vendorId}/verify-payment-change`, {
      change_request_id,
      verified_by,
      channel,
      approve,
      notes,
    }),
};
