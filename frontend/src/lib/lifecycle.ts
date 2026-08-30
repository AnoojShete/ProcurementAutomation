import type { Contract, DocumentRecord, PurchaseRequest } from "@/types/api";

export type StageState = "completed" | "current" | "pending" | "blocked" | "failed";

export interface LifecycleStage {
  key: string;
  label: string;
  state: StageState;
  detail?: string;
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
  const fulfilled = status === "fulfilled";
  const approved = status === "approved" || fulfilled;
  const hasChain = (request.approval_chain?.length ?? 0) > 0;

  const stages: LifecycleStage[] = [];

  stages.push({
    key: "created",
    label: "Request Created",
    state: "completed",
    detail: request.created_at ?? undefined,
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
      label: "Document Processing",
      state: docState,
      detail: linkedDocument.needs_review ? "Needs review — low confidence" : linkedDocument.document_type ?? undefined,
    });
  } else {
    stages.push({ key: "document", label: "Document Processing", state: "completed", detail: "No document attached" });
  }

  stages.push({
    key: "vendor",
    label: "Vendor Validation",
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
    detail: rejected ? "Rejected" : hasChain ? `Stage ${Math.min(request.current_approver_index + 1, request.approval_chain!.length)} of ${request.approval_chain!.length}` : "Auto-approved",
  });

  stages.push({
    key: "inventory",
    label: "Inventory Check",
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
    detail: linkedContract?.template_used ?? undefined,
  });

  let signatureState: StageState = "pending";
  if (rejected) signatureState = "blocked";
  else if (linkedContract?.status === "signed") signatureState = "completed";
  else if (linkedContract?.status === "pending_signature") signatureState = "current";
  else signatureState = "pending";
  stages.push({ key: "signature", label: "Signature", state: signatureState });

  stages.push({
    key: "fulfillment",
    label: "Fulfillment",
    state: rejected ? "blocked" : fulfilled ? "completed" : "pending",
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
    case "fulfilled":
      return "Fulfilled";
    default:
      return status ?? "Unknown";
  }
}
