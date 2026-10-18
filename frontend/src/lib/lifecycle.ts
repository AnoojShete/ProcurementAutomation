import type { Contract, DocumentRecord, PurchaseRequest } from "@/types/api";
import { documentTypeLabel, formatDateTime, titleCase } from "@/lib/format";

export type StageState = "completed" | "current" | "pending" | "blocked" | "failed";

export interface LifecycleStage {
  key: string;
  label: string;
  state: StageState;
  detail?: string;
  /** True only while an agent is actually processing (shows a spinner).
   * "current" alone means waiting on a person: a static marker. */
  working?: boolean;
}

/**
 * Maps a purchase request's real status/spend-tier plus any linked
 * document/contract onto the 8-stage visual lifecycle. Every stage is
 * derived from fields the backend actually returns — nothing invented.
 */
export function deriveLifecycle(
  request: PurchaseRequest,
  linkedDocument?: DocumentRecord | null,
  linkedContract?: Contract | null,
): LifecycleStage[] {
  const status = request.status ?? "pending_approval";
  const rejected = status === "rejected";
  // Past fulfilment: received, or invoiced after receipt.
  const fulfilled = ["fulfilled", "partially_invoiced", "invoice_received"].includes(status);
  const ordered = status === "ordered";
  const approved = status === "approved" || ordered || fulfilled;
  const hasChain = (request.approval_chain?.length ?? 0) > 0;

  const stages: LifecycleStage[] = [];

  stages.push({
    key: "created",
    label: "Request created",
    state: "completed",
    detail: request.created_at ? formatDateTime(request.created_at) : undefined,
  });

  if (linkedDocument) {
    const docState: StageState =
      linkedDocument.status === "failed"
        ? "failed"
        : linkedDocument.status === "classified"
          ? "completed"
          : "current";
    stages.push({
      key: "document",
      label: "Document processing",
      state: docState,
      detail: linkedDocument.needs_review
        ? "Needs review: low confidence"
        : docState === "current"
          ? "Reading the document"
          : linkedDocument.document_type
            ? documentTypeLabel(linkedDocument.document_type)
            : undefined,
      working: docState === "current" && !linkedDocument.needs_review,
    });
  } else {
    stages.push({ key: "document", label: "Document processing", state: "completed", detail: "No document attached" });
  }

  stages.push({
    key: "vendor",
    label: "Vendor validation",
    state: request.vendor_id ? "completed" : "pending",
    detail: request.vendor_id ? "Vendor matched" : "No vendor linked yet",
  });

  let approvalState: StageState = "pending";
  if (rejected) approvalState = "failed";
  else if (approved) approvalState = "completed";
  else if (hasChain) approvalState = "current";
  else approvalState = "completed";
  stages.push({
    key: "approval",
    label: "Approval",
    state: approvalState,
    detail: rejected
      ? "Rejected"
      : approvalState === "current"
        ? `Waiting on ${titleCase(request.approval_chain![Math.min(request.current_approver_index, request.approval_chain!.length - 1)])} · ${Math.min(request.current_approver_index + 1, request.approval_chain!.length)} of ${request.approval_chain!.length}`
        : hasChain
          ? `${request.approval_chain!.length} of ${request.approval_chain!.length} approved`
          : "Auto-approved",
  });

  stages.push({
    key: "inventory",
    label: "Inventory check",
    state: rejected ? "blocked" : approved ? "completed" : "pending",
    detail: request.is_backordered ? "Partially backordered" : undefined,
  });

  const contractState: StageState = rejected
    ? "blocked"
    : linkedContract
      ? "completed"
      : approved
        ? "current"
        : "pending";
  stages.push({
    key: "contract",
    label: "Contract",
    state: contractState,
    detail: linkedContract?.template_used
      ? titleCase(linkedContract.template_used)
      : contractState === "current"
        ? "Waiting on contract agent"
        : undefined,
  });

  let signatureState: StageState = "pending";
  if (rejected) signatureState = "blocked";
  else if (linkedContract?.status === "signed") signatureState = "completed";
  else if (linkedContract?.status === "pending_signature") signatureState = "current";
  else signatureState = "pending";
  stages.push({
    key: "signature",
    label: "Signature",
    state: signatureState,
    detail: signatureState === "current" ? "Waiting on signer" : linkedContract?.signed_at ? formatDateTime(linkedContract.signed_at) : undefined,
  });

  stages.push({
    key: "fulfillment",
    label: "Fulfillment",
    state: rejected ? "blocked" : fulfilled ? "completed" : ordered ? "current" : "pending",
    detail: ordered ? "Waiting on delivery" : undefined,
  });

  return stages;
}

export function requestStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "pending_approval":
      return "Pending Approval";
    case "approved":
      return "Approved";
    case "rejected":
      return "Rejected";
    case "ordered":
      return "Ordered";
    case "fulfilled":
      return "Fulfilled";
    default:
      return status ?? "Unknown";
  }
}
