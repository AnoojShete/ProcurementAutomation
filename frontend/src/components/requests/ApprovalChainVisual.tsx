import { Check, Clock, User } from "lucide-react";
import { cn } from "@/lib/cn";
import { titleCase } from "@/lib/format";
import type { PurchaseRequest } from "@/types/api";

export function ApprovalChainVisual({ request }: { request: PurchaseRequest }) {
  const chain = request.approval_chain ?? [];
  const rejected = request.status === "rejected";
  const nodes = [
    { label: "Requester", sub: request.requested_by ?? undefined },
    ...chain.map((role) => ({ label: titleCase(role), sub: undefined })),
    { label: "Approved", sub: undefined },
  ];

  return (
    <div className="flex flex-col">
      {nodes.map((node, i) => {
        const isRequester = i === 0;
        const isFinal = i === nodes.length - 1;
        const approverIndex = i - 1;
        let state: "completed" | "current" | "pending" | "failed" = "pending";
        if (isRequester) state = "completed";
        else if (isFinal) state = request.status === "approved" || request.status === "fulfilled" ? "completed" : rejected ? "failed" : "pending";
        else if (rejected && approverIndex <= request.current_approver_index) state = "failed";
        else if (approverIndex < request.current_approver_index) state = "completed";
        else if (approverIndex === request.current_approver_index && request.status === "pending_approval") state = "current";
        else state = "pending";

        return (
          <div key={i} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full",
                  state === "completed" && "bg-success-500 text-white",
                  state === "current" && "bg-brand-600 text-white ring-4 ring-brand-100",
                  state === "pending" && "border border-slate-300 bg-slate-100 text-slate-400",
                  state === "failed" && "bg-danger-500 text-white",
                )}
              >
                {state === "completed" ? <Check className="size-3.5" /> : state === "current" ? <Clock className="size-3.5" /> : <User className="size-3.5" />}
              </div>
              {!isFinal && <div className={cn("my-0.5 h-6 w-0.5", state === "completed" ? "bg-success-500" : "bg-slate-200")} />}
            </div>
            <div className="pb-6">
              <p className={cn("text-sm", state === "current" ? "font-semibold text-brand-700" : "font-medium text-slate-700")}>{node.label}</p>
              {node.sub && <p className="text-xs text-slate-500">{node.sub}</p>}
              {state === "current" && <p className="text-xs text-brand-600">Awaiting decision</p>}
              {state === "failed" && <p className="text-xs text-danger-600">Rejected</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
