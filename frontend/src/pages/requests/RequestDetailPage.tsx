import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Ban, CheckCircle2, XCircle } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { usePolling } from "@/hooks/usePolling";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { contractsApi } from "@/api/contracts";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusBadge, ContractStatusBadge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { InlineError, InlineSuccess, InlineInfo } from "@/components/ui/ErrorState";
import { LifecycleStepper } from "@/components/ui/LifecycleStepper";
import { ApprovalChainVisual } from "@/components/requests/ApprovalChainVisual";
import { ProcurementAssessment } from "@/components/requests/ProcurementAssessment";
import { Timeline, type TimelineEvent } from "@/components/ui/Timeline";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatCurrency, formatDateTime, titleCase } from "@/lib/format";
import { deriveLifecycle } from "@/lib/lifecycle";
import type { PurchaseRequest, VendorRisk } from "@/types/api";
import { ApiError } from "@/api/client";
import { Link } from "react-router-dom";

export function RequestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: request, loading, error, reload } = useApi(() => requestsApi.get(id!), [id]);
  usePageHeader(request ? `${titleCase(request.request_type)} Request` : "Request", "Requests");

  const { data: vendors } = useApi(() => vendorsApi.list(200), []);
  const vendor = vendors?.find((v) => v.id === request?.vendor_id) ?? null;

  const [vendorRisk, setVendorRisk] = useState<VendorRisk | null>(null);
  const [vendorRiskLoading, setVendorRiskLoading] = useState(false);
  useEffect(() => {
    if (!request?.vendor_id) return;
    setVendorRiskLoading(true);
    vendorsApi
      .risk(request.vendor_id)
      .then((r) => setVendorRisk(r.data))
      .catch(() => setVendorRisk(null))
      .finally(() => setVendorRiskLoading(false));
  }, [request?.vendor_id]);

  const { data: contracts } = useApi(() => contractsApi.list(200), []);
  const linkedContract = contracts?.find((c) => c.purchase_request_id === request?.id) ?? null;

  const { state: pollState, run: runPoll } = usePolling<PurchaseRequest>();
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [decisionDone, setDecisionDone] = useState<"approved" | "rejected" | null>(null);
  const [comments, setComments] = useState("");
  const [acting, setActing] = useState(false);

  const canDecide =
    request?.status === "pending_approval" &&
    (user?.role === "approver" || user?.role === "finance" || user?.role === "admin");

  const decide = async (decision: "approve" | "reject") => {
    if (!request || !user) return;
    setActing(true);
    setDecisionError(null);
    try {
      if (decision === "approve") await requestsApi.approve(request.id, user.email, comments || undefined);
      else await requestsApi.reject(request.id, user.email, comments || undefined);

      const settled = await runPoll(() => requestsApi.get(request.id).then((r) => r.data), {
        isSettled: (r) => r.status !== "pending_approval",
        maxAttempts: 10,
        intervalMs: 700,
      });
      if (settled) {
        setDecisionDone(settled.status === "approved" ? "approved" : "rejected");
        reload();
      } else {
        setDecisionError("The decision was submitted but hasn't settled yet — reload in a moment to check its status.");
      }
    } catch (e) {
      setDecisionError(e instanceof ApiError ? e.message : "Unable to submit decision.");
    } finally {
      setActing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (error || !request) return <ErrorState message={error ?? "Request not found."} onRetry={reload} />;

  const lifecycle = deriveLifecycle(request, null, linkedContract);

  const activity: TimelineEvent[] = [
    { key: "created", title: "Request created", timestamp: formatDateTime(request.created_at), description: request.requested_by ?? undefined },
    ...(request.approval_history ?? []).map(
      (h): TimelineEvent => ({
        key: h.id,
        title: `${h.decision === "approved" ? "Approved" : "Rejected"} by ${h.decided_by}`,
        timestamp: formatDateTime(h.decided_at),
        description: h.comments ?? undefined,
        tone: h.decision === "approved" ? "success" : "danger",
      }),
    ),
    ...(linkedContract
      ? [
          {
            key: `contract-${linkedContract.id}`,
            title: "Contract generated",
            timestamp: formatDateTime(linkedContract.generated_at),
            description: (
              <Link to={`/app/contracts/${linkedContract.id}`} className="text-brand-700 hover:underline">
                View contract →
              </Link>
            ),
          },
        ]
      : []),
  ];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-mono text-xs text-slate-400">PR-{request.id.slice(0, 8)}</h2>
            <StatusBadge status={request.status} />
          </div>
          <h1 className="mt-1 text-xl font-semibold text-slate-900">
            {titleCase(request.request_type)} Procurement — {request.department ?? "—"}
          </h1>
        </div>
        {canDecide && (
          <div className="flex gap-2">
            <Button
              variant="destructive"
              icon={<XCircle className="size-4" />}
              loading={acting || pollState === "polling"}
              onClick={() => decide("reject")}
            >
              Reject
            </Button>
            <Button icon={<CheckCircle2 className="size-4" />} loading={acting || pollState === "polling"} onClick={() => decide("approve")}>
              Approve
            </Button>
            <Button variant="ghost" disabled title="Not available — the backend supports approve/reject decisions only today.">
              <Ban className="size-4" />
              Request Changes
            </Button>
          </div>
        )}
      </div>

      {pollState === "polling" && (
        <InlineInfo message="Processing decision — this is applied by a background workflow and settles within a few seconds." />
      )}
      {decisionDone && <InlineSuccess message={`Request ${decisionDone}.`} />}
      {decisionError && <InlineError message={decisionError} />}

      <Card>
        <CardHeader title="Procurement Lifecycle" />
        <CardBody className="overflow-x-auto">
          <LifecycleStepper stages={lifecycle} />
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <Card>
            <CardHeader title="Request Information" />
            <CardBody>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
                <Field label="Requester" value={request.requested_by} />
                <Field label="Department" value={request.department} />
                <Field label="Category" value={titleCase(request.request_type)} />
                <Field label="Amount" value={formatCurrency(request.amount, request.currency ?? "INR")} />
                <Field label="Vendor" value={vendor?.name ?? (request.vendor_id ? "Unknown vendor" : "Not linked")} />
                <Field label="Spend Tier" value={titleCase(request.spend_tier)} />
                {request.is_backordered && <Field label="Fulfillment" value="Partially backordered" />}
              </dl>
              {request.items && request.items.length > 0 && (
                <div className="mt-4 border-t border-surface-border pt-4">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">Line Items</p>
                  <div className="flex flex-col gap-1.5">
                    {request.items.map((item, i) => (
                      <div key={i} className="flex justify-between rounded-md bg-surface-subtle px-3 py-1.5 text-sm">
                        <span className="text-slate-700">{String(item.sku ?? item.name ?? `Item ${i + 1}`)}</span>
                        <span className="text-slate-500">Qty {String(item.quantity ?? 1)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Approval Chain" />
            <CardBody>
              <ApprovalChainVisual request={request} />
            </CardBody>
          </Card>
        </div>

        <div className="flex flex-col gap-6">
          <ProcurementAssessment request={request} vendorRisk={vendorRisk} vendorRiskLoading={vendorRiskLoading} />

          {canDecide && (
            <Card>
              <CardHeader title="Decision Notes" subtitle="Optional — included with your approval or rejection" />
              <CardBody>
                <textarea
                  value={comments}
                  onChange={(e) => setComments(e.target.value)}
                  rows={3}
                  className="w-full resize-none rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
                  placeholder="Add a comment for the audit trail…"
                />
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader title="Activity" />
            <CardBody>
              <Timeline events={activity} />
            </CardBody>
          </Card>

          {linkedContract && (
            <Card>
              <CardHeader
                title="Contract"
                action={<ContractStatusBadge status={linkedContract.status} />}
              />
              <CardBody>
                <Button variant="secondary" size="sm" onClick={() => navigate(`/app/contracts/${linkedContract.id}`)}>
                  View contract
                </Button>
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-400">{label}</dt>
      <dd className="mt-0.5 font-medium text-slate-800">{value ?? "—"}</dd>
    </div>
  );
}
