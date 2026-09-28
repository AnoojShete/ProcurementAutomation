import { useState } from "react";
import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import { authorityApi } from "@/api/controls";
import { requestsApi } from "@/api/requests";
import { ApiError } from "@/api/client";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { usePolling } from "@/hooks/usePolling";
import { Button } from "@/components/ui/Button";
import { InlineError, InlineInfo, InlineSuccess } from "@/components/ui/ErrorState";
import { formatDateTime } from "@/lib/format";
import type { PurchaseRequest } from "@/types/api";

const STAFF = ["approver", "finance", "admin"];

/**
 * The approval agent's decision panel: approve / reject a purchase request.
 * The same component is used wherever a pending request shows up — the
 * request page, its lifecycle "Approval" step and the license page — so the
 * decision looks and behaves the same from every entry point. It talks only
 * to approval-inventory-agent (/requests, /authority).
 */
export function ApprovalActions({
  request,
  onDecided,
}: {
  request: PurchaseRequest;
  onDecided?: (updated: PurchaseRequest) => void;
}) {
  const { user } = useAuth();
  const { state: pollState, run: runPoll } = usePolling<PurchaseRequest>();
  const [comments, setComments] = useState("");
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const pending = request.status === "pending_approval";
  const canDecide = pending && STAFF.includes(user?.role ?? "");
  // Server-side authority rules (level assignment, limits, separation of
  // duties), shown up front instead of as a failed click.
  const { data: authority } = useApi(
    () => (canDecide ? authorityApi.check(request.id) : Promise.resolve({ data: null })),
    [canDecide, request.id, request.current_approver_index],
  );
  const blocked = authority != null && !authority.allowed;

  if (request.status === "pending_grace_period") {
    return (
      <InlineInfo message="In the reclaim grace period: the license holder can still decline; otherwise it moves to approval." />
    );
  }
  if (!pending) {
    const last = request.approval_history?.[request.approval_history.length - 1];
    return (
      <div className="flex flex-col gap-2">
        {done && <InlineSuccess message={done} />}
        <p className="text-sm text-slate-600">
          {request.status === "rejected" ? "Rejected" : "Approval complete"}
          {last ? ` — last decision by ${last.decided_by} on ${formatDateTime(last.decided_at)}.` : "."}
        </p>
      </div>
    );
  }
  if (!canDecide) {
    const level = request.approval_chain?.[request.current_approver_index];
    return <p className="text-sm text-slate-600">Waiting for {level ? level.replace(/_/g, " ") : "an approver"}.</p>;
  }

  const decide = async (decision: "approve" | "reject") => {
    if (!user) return;
    setActing(true);
    setError(null);
    try {
      if (decision === "approve") await requestsApi.approve(request.id, user.email, comments || undefined);
      else await requestsApi.reject(request.id, user.email, comments || undefined);
      // Applied by a Temporal workflow in the worker, so it settles a moment later.
      const startIndex = request.current_approver_index;
      const settled = await runPoll(() => requestsApi.get(request.id).then((r) => r.data), {
        isSettled: (r) => r.status !== "pending_approval" || r.current_approver_index !== startIndex,
        maxAttempts: 10,
        intervalMs: 700,
      });
      if (settled) {
        setDone(settled.status === "rejected" ? "Request rejected." : settled.status === "pending_approval" ? "Approved — moved to the next approver." : "Request approved.");
        onDecided?.(settled);
      } else {
        setError("The decision was submitted but hasn't settled yet — reload in a moment to check.");
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to submit the decision.");
    } finally {
      setActing(false);
    }
  };

  const busy = acting || pollState === "polling";
  return (
    <div className="flex flex-col gap-3">
      {blocked && (
        <div className="flex items-start gap-2 rounded-md border border-surface-border bg-surface-subtle px-3 py-2 text-13 text-slate-700">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-slate-500" />
          <span>
            <span className="font-medium">You can't approve this request.</span> {authority?.reason}
          </span>
        </div>
      )}
      {authority?.allowed && authority.via_delegation && (
        <InlineInfo message={`You're deciding on behalf of ${authority.via_delegation} (delegation).`} />
      )}
      <textarea
        value={comments}
        onChange={(e) => setComments(e.target.value)}
        rows={2}
        aria-label="Decision notes"
        className="w-full resize-none rounded-md border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
        placeholder="Notes for the audit trail (optional)"
      />
      <div className="flex gap-2">
        <Button variant="destructive" icon={<XCircle className="size-4" />} loading={busy} onClick={() => decide("reject")}>
          Reject
        </Button>
        <Button
          icon={<CheckCircle2 className="size-4" />}
          loading={busy}
          disabled={blocked}
          title={blocked ? authority?.reason : undefined}
          onClick={() => decide("approve")}
        >
          Approve
        </Button>
      </div>
      {pollState === "polling" && <InlineInfo message="Applying the decision — it settles within a few seconds." />}
      {done && <InlineSuccess message={done} />}
      {error && <InlineError message={error} />}
    </div>
  );
}
