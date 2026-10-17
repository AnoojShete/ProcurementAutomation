import { api } from "./client";
import type {
  ApprovalDelegation,
  ApproverAssignment,
  AuthorityCheck,
  DlqEntry,
  EventingStatus,
  InvoiceMatchResult,
  InvoiceMatchRow,
  LearningStats,
  LookalikeScenario,
  ReconcileResult,
  RequestLedger,
  VendorPaymentChange,
} from "@/types/api";

// Replay runs the consuming service's own handler, so it goes to that service.
const REPLAY_PATH: Record<string, string> = {
  "approval-inventory-agent": "/ops/dlq",
  "contract-risk-agent": "/contracts/ops/dlq",
};

export const opsApi = {
  eventing: () => api.get<EventingStatus>("/ops/eventing"),
  dlq: (status = "open") => api.get<DlqEntry[]>(`/ops/dlq?status=${status}`),
  replay: (entry: DlqEntry) =>
    api.post<{ status: string; error?: string }>(`${REPLAY_PATH[entry.consumer] ?? "/ops/dlq"}/${entry.id}/replay`),
  discard: (id: string) => api.post(`/ops/dlq/${id}/discard`),
  reconcile: () => api.post<ReconcileResult[]>("/ops/reconcile"),
  injectOutOfOrderEvent: () =>
    api.post<{ event_id: string; purchase_request_id: string }>("/ops/showcase/inject-out-of-order-event"),
};

export const authorityApi = {
  get: () => api.get<{ assignments: ApproverAssignment[]; delegations: ApprovalDelegation[] }>("/authority/"),
  check: (requestId: string, decision: "approved" | "rejected" = "approved") =>
    api.get<AuthorityCheck>(`/authority/check/${requestId}?decision=${decision}`),
  addAssignment: (level: string, user_email: string, max_amount: number | null) =>
    api.post("/authority/assignments", { level, user_email, max_amount }),
  removeAssignment: (id: string) => api.request(`/authority/assignments/${id}`, "DELETE"),
  addDelegation: (body: { level: string; delegate_email: string; valid_until: string; reason: string }) =>
    api.post("/authority/delegations", body),
  revokeDelegation: (id: string) => api.request(`/authority/delegations/${id}`, "DELETE"),
};

export const ledgerApi = {
  simulate: (body: {
    document_id: string;
    vendor_id: string;
    total: number;
    lines: { description: string; quantity: number; unit_price: number }[];
  }) => api.post<InvoiceMatchResult>("/invoices/match?dry_run=true", body),
  forRequest: (requestId: string) => api.get<RequestLedger>(`/invoices/ledger/${requestId}`),
  matches: (params: { held?: boolean; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.held !== undefined) q.set("held", String(params.held));
    q.set("limit", String(params.limit ?? 50));
    return api.get<InvoiceMatchRow[]>(`/invoices/matches?${q}`);
  },
};

export const paymentControlsApi = {
  pending: () => api.get<(VendorPaymentChange & { vendor_name: string })[]>("/vendors/payment-changes/pending"),
  lookalikeScenario: () => api.post<LookalikeScenario>("/documents/showcase/lookalike-invoice"),
};

export const learningScenarioApi = {
  unusualLabelInvoice: () =>
    api.post<{ document_id: string; vendor: string; invoice_number: string; total: number }>(
      "/documents/showcase/unusual-label-invoice",
    ),
};

export const learningApi = {
  stats: () => api.get<LearningStats>("/documents/learning/stats"),
};
