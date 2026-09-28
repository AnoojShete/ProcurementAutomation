import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { X } from "lucide-react";
import { InvoiceLedgerCard } from "@/components/controls/InvoiceLedgerCard";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { contractsApi } from "@/api/contracts";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { StatusBadge, ContractStatusBadge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { LifecycleStepper } from "@/components/ui/LifecycleStepper";
import { ApprovalChainVisual } from "@/components/requests/ApprovalChainVisual";
import { ProcurementAssessment } from "@/components/requests/ProcurementAssessment";
import { ApprovalActions } from "@/components/approvals/ApprovalActions";
import { ContractActions } from "@/components/contracts/ContractActions";
import { Timeline, type TimelineEvent } from "@/components/ui/Timeline";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatCurrency, formatDateTime, titleCase } from "@/lib/format";
import { deriveLifecycle, type LifecycleStage } from "@/lib/lifecycle";
import type { Contract, PurchaseRequest, VendorRisk, VendorSummary } from "@/types/api";

/** The approval agent's page for one purchase request. Other agents' parts
 * (the contract, the vendor) are shown through their own components and
 * link to their own pages. */
export function RequestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
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

  const { data: contracts, reload: reloadContracts } = useApi(() => contractsApi.list(200), []);
  const linkedContract = contracts?.find((c) => c.purchase_request_id === request?.id) ?? null;
  // The list endpoint omits the certificate; the contract itself has it.
  const { data: contract, reload: reloadContract } = useApi(
    () => (linkedContract ? contractsApi.get(linkedContract.id) : Promise.resolve({ data: null })),
    [linkedContract?.id, linkedContract?.status],
  );

  // ?step=<key> selects a lifecycle step (e.g. from the approval inbox).
  const selectedKey = params.get("step");
  const select = (stage: LifecycleStage | null) => {
    const next = new URLSearchParams(params);
    if (!stage || stage.key === selectedKey) next.delete("step");
    else next.set("step", stage.key);
    setParams(next, { replace: true });
  };

  const refresh = () => {
    reload();
    reloadContracts();
    reloadContract();
  };

  if (loading && !request) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (error || !request) return <ErrorState message={error ?? "Request not found."} onRetry={reload} />;

  const lifecycle = deriveLifecycle(request, null, contract ?? linkedContract);
  const selected = lifecycle.find((s) => s.key === selectedKey) ?? null;

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
      </div>

      <Card>
        <CardHeader title="Procurement Lifecycle" subtitle="Click a step for its details or to act on it" />
        <CardBody className="overflow-x-auto">
          <LifecycleStepper stages={lifecycle} onSelect={select} selectedKey={selectedKey} />
        </CardBody>
        {selected && (
          <div className="border-t border-surface-border bg-surface-subtle px-4 py-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-900">{selected.label}</p>
              <button onClick={() => select(null)} aria-label="Close step details" className="rounded p-1 text-slate-500 hover:bg-surface-muted">
                <X className="size-4" />
              </button>
            </div>
            <StageDetails
              stage={selected}
              request={request}
              vendor={vendor}
              vendorRisk={vendorRisk}
              contract={contract ?? null}
              onChanged={refresh}
            />
          </div>
        )}
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
                <Field
                  label="Vendor"
                  value={
                    vendor ? (
                      <Link to={`/app/vendors/${vendor.id}`} className="text-brand-700 hover:underline">
                        {vendor.name}
                      </Link>
                    ) : request.vendor_id ? (
                      "Unknown vendor"
                    ) : (
                      "Not linked"
                    )
                  }
                />
                <Field label="Spend Tier" value={titleCase(request.spend_tier)} />
                {request.is_backordered && <Field label="Fulfillment" value="Partially backordered" />}
              </dl>
              <LineItems request={request} />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Approval" subtitle={request.status === "pending_approval" ? "Decide here or from the lifecycle's Approval step" : undefined} />
            <CardBody className="flex flex-col gap-4">
              <ApprovalChainVisual request={request} />
              <ApprovalActions request={request} onDecided={refresh} />
            </CardBody>
          </Card>
        </div>

        <div className="flex flex-col gap-6">
          <ProcurementAssessment request={request} vendorRisk={vendorRisk} vendorRiskLoading={vendorRiskLoading} />
          {["approved", "fulfilled", "partially_invoiced", "invoice_received"].includes(request.status ?? "") && (
            <InvoiceLedgerCard requestId={request.id} currency={request.currency ?? "INR"} />
          )}

          {(contract || request.status === "approved") && (
            <Card>
              <CardHeader
                title="Contract & e-signature"
                action={contract ? <ContractStatusBadge status={contract.status} /> : undefined}
              />
              <CardBody className="flex flex-col gap-3 text-sm">
                {contract && (
                  <div className="flex items-center justify-between text-xs text-slate-500">
                    <span>
                      {titleCase(contract.template_used)}
                      {contract.signed_by && ` · signed by ${contract.signed_by}`}
                    </span>
                    <Link to={`/app/contracts/${contract.id}`} className="text-brand-700 hover:underline">
                      Open contract →
                    </Link>
                  </div>
                )}
                <ContractActions contract={contract ?? null} request={request} onChanged={refresh} layout="stack" />
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader title="Activity" />
            <CardBody>
              <Timeline events={activity} />
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}

/** What a lifecycle step shows when clicked: its facts, plus the owning
 * agent's action where the step is actionable. */
function StageDetails({
  stage,
  request,
  vendor,
  vendorRisk,
  contract,
  onChanged,
}: {
  stage: LifecycleStage;
  request: PurchaseRequest;
  vendor: VendorSummary | null;
  vendorRisk: VendorRisk | null;
  contract: Contract | null;
  onChanged: () => void;
}) {
  switch (stage.key) {
    case "created":
      return (
        <p className="text-sm text-slate-700">
          Raised by {request.requested_by ?? "—"} ({request.department ?? "no department"}) on {formatDateTime(request.created_at)} for{" "}
          {formatCurrency(request.amount, request.currency ?? "INR")}.
        </p>
      );
    case "document":
      return (
        <p className="text-sm text-slate-700">
          {stage.detail ?? "No document attached."} Documents are processed by the document agent —{" "}
          <Link to="/app/documents" className="text-brand-700 hover:underline">
            open Documents
          </Link>
          .
        </p>
      );
    case "vendor":
      return vendor ? (
        <p className="text-sm text-slate-700">
          <Link to={`/app/vendors/${vendor.id}`} className="font-medium text-brand-700 hover:underline">
            {vendor.name}
          </Link>
          {vendorRisk?.risk_band ? ` · risk ${vendorRisk.risk_band}` : ""}. Vendor details and risk are on the vendor page.
        </p>
      ) : (
        <p className="text-sm text-slate-700">No vendor is linked to this request yet.</p>
      );
    case "approval":
      return <ApprovalActions request={request} onDecided={onChanged} />;
    case "inventory":
      return (
        <div className="text-sm text-slate-700">
          {request.is_backordered ? "Part of this request is backordered." : stage.state === "completed" ? "Stock checked after approval." : "Checked once the request is approved."}
          <LineItems request={request} />
        </div>
      );
    case "contract":
      return (
        <div className="flex flex-col gap-2">
          {contract && (
            <p className="text-sm text-slate-700">
              {titleCase(contract.template_used)}, generated {formatDateTime(contract.generated_at)} —{" "}
              <Link to={`/app/contracts/${contract.id}`} className="text-brand-700 hover:underline">
                open contract
              </Link>
              .
            </p>
          )}
          <ContractActions contract={contract} request={request} onChanged={onChanged} />
        </div>
      );
    case "signature":
      if (!contract) return <p className="text-sm text-slate-700">Signing starts once a contract has been generated.</p>;
      return (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-slate-700">
            {contract.status === "signed"
              ? `Signed by ${contract.signed_by ?? "the signer"} on ${formatDateTime(contract.signed_at)}.`
              : contract.status === "pending_signature"
                ? `Waiting for signature (${contract.esign_provider_ref ?? "built-in e-sign"}).`
                : "Not sent for signature yet."}
          </p>
          <ContractActions contract={contract} request={request} onChanged={onChanged} autoOpen={contract.status !== "signed" ? "sign" : undefined} />
        </div>
      );
    case "fulfillment":
      return (
        <p className="text-sm text-slate-700">
          {request.status === "fulfilled" || request.status === "invoice_received"
            ? "Fulfilled: the contract is signed and the order is complete."
            : "Completes when the contract is signed (and, for invoices, when they're matched in the invoice ledger)."}
        </p>
      );
    default:
      return null;
  }
}

function LineItems({ request }: { request: PurchaseRequest }) {
  if (!request.items || request.items.length === 0) return null;
  return (
    <div className="mt-4 border-t border-surface-border pt-4">
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">Line Items</p>
      <div className="flex flex-col gap-1.5">
        {request.items.map((item, i) => (
          <div key={i} className="flex justify-between rounded-md bg-surface-subtle px-3 py-1.5 text-sm">
            <span className="text-slate-700">
              {item.license_id ? (
                <Link to={`/app/licenses/${String(item.license_id)}`} className="text-brand-700 hover:underline">
                  {String(item.name ?? item.app_name ?? "License")}
                </Link>
              ) : (
                String(item.sku ?? item.name ?? `Item ${i + 1}`)
              )}
            </span>
            <span className="text-slate-500">Qty {String(item.quantity ?? 1)}</span>
          </div>
        ))}
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
