import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { X } from "lucide-react";
import { InvoiceLedgerCard } from "@/components/controls/InvoiceLedgerCard";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { contractsApi } from "@/api/contracts";
import { documentsApi } from "@/api/documents";
import { DocumentPreviewCard } from "@/components/documents/DocumentPreviewCard";
import { Card, CardBody, CardHeader, Section } from "@/components/ui/Card";
import { Badge, StatusBadge, ContractStatusBadge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { LifecycleStepper } from "@/components/ui/LifecycleStepper";
import { ApprovalChainVisual } from "@/components/requests/ApprovalChainVisual";
import { ProcurementAssessment } from "@/components/requests/ProcurementAssessment";
import { ApprovalActions } from "@/components/approvals/ApprovalActions";
import { ContractActions } from "@/components/contracts/ContractActions";
import { Timeline, type TimelineEvent } from "@/components/ui/Timeline";
import { Skeleton } from "@/components/ui/Skeleton";
import { DocketHeader, RefCopy } from "@/components/ui/DocketHeader";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { PersonName } from "@/components/people/PersonName";
import { usePeople } from "@/hooks/usePeople";
import { formatCurrency, formatDate, formatDateTime, titleCase } from "@/lib/format";
import { deriveLifecycle, type LifecycleStage } from "@/lib/lifecycle";
import type { Contract, DocumentRecord, PurchaseRequest, VendorRisk, VendorSummary } from "@/types/api";

/** The approval agent's page for one purchase request. Other agents' parts
 * (the contract, the vendor) are shown through their own components and
 * link to their own pages. */
export function RequestDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [params, setParams] = useSearchParams();
  const { withNames } = usePeople();
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

  const { data: contracts, reload: reloadContracts } = useApi(
    () => (request?.id ? contractsApi.list(200, request.id) : contractsApi.list(200)),
    [request?.id],
  );
  const linkedContract = contracts?.find((c) => c.purchase_request_id === request?.id) ?? contracts?.[0] ?? null;
  // The list endpoint omits the certificate; the contract itself has it.
  const { data: contract, reload: reloadContract } = useApi(
    () => (linkedContract ? contractsApi.get(linkedContract.id) : Promise.resolve({ data: null })),
    [linkedContract?.id, linkedContract?.status],
  );

  const { data: allDocs, reload: reloadDocs } = useApi(() => documentsApi.list(200), []);
  const attachedDoc = useMemo(() => {
    if (!request || !allDocs) return null;
    // Only the document the request was created with: guessing by vendor
    // or uploader showed unrelated invoices as this request's attachment.
    if (!request.document_id) return null;
    return allDocs.find((d) => d.id === request.document_id) ?? null;
  }, [request, allDocs]);

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
    reloadDocs();
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

  const lifecycle = deriveLifecycle(request, attachedDoc, contract ?? linkedContract);
  const selected = lifecycle.find((s) => s.key === selectedKey) ?? null;

  // The paper trail: who (person or agent) did what, when. Built only from
  // fields the request, its contract and its document already carry.
  const shownContract = contract ?? linkedContract;
  const trail: TimelineEvent[] = [
    {
      key: "created",
      title: "Request raised",
      timestamp: formatDateTime(request.created_at),
      actor: request.requested_by ? <PersonName email={request.requested_by} /> : undefined,
      description: `${formatCurrency(request.amount, request.currency ?? "INR")} · ${titleCase(request.request_type)}`,
    },
    ...(attachedDoc
      ? [
          {
            key: `doc-${attachedDoc.id}`,
            title: attachedDoc.status === "classified" ? "Document read and classified" : "Document received",
            timestamp: formatDateTime(attachedDoc.uploaded_at),
            actor: "Document & Vendor agent",
            description: attachedDoc.original_filename ?? undefined,
          } satisfies TimelineEvent,
        ]
      : []),
    ...(request.approval_history ?? []).map(
      (h): TimelineEvent => ({
        key: h.id,
        title: `${h.decision === "approved" ? "Approved" : "Rejected"}${h.decision_level ? ` · ${titleCase(h.decision_level)}` : ""}`,
        timestamp: formatDateTime(h.decided_at),
        actor: <PersonName email={h.decided_by} />,
        description: h.comments ?? undefined,
        tone: h.decision === "approved" ? "success" : "danger",
        stamp: h.decision === "approved" ? "Approved" : "Rejected",
        at: h.decided_at,
      }),
    ),
    ...(shownContract
      ? [
          {
            key: `contract-${shownContract.id}`,
            title: "Contract generated",
            timestamp: formatDateTime(shownContract.generated_at),
            actor: "Contract & Risk agent",
            description: (
              <Link to={`/app/contracts/${shownContract.id}`} className="text-accent hover:underline">
                {titleCase(shownContract.template_used)} contract
              </Link>
            ),
          } satisfies TimelineEvent,
        ]
      : []),
    ...(shownContract?.status === "signed"
      ? [
          {
            key: `signed-${shownContract.id}`,
            title: "Contract signed",
            timestamp: formatDateTime(shownContract.signed_at),
            actor: withNames(shownContract.signed_by) || "Signer",
            tone: "success",
            stamp: "Signed",
            at: shownContract.signed_at,
          } satisfies TimelineEvent,
        ]
      : []),
  ];

  // The step waiting on someone, shown above everything else. A plain
  // expression, not a hook: the page returns early while loading, so a hook
  // here would change the hook count between renders and crash the page.
  // `kind` says whose actions the panel holds, so the cards below don't
  // show a second copy of them.
  const nextAction = ((): { kind: "approval" | "contract" | "receipt"; title: string; subtitle: string; badge: ReactNode; content: ReactNode } | null => {
    if (request.status === "pending_approval") {
      return {
        kind: "approval",
        title: "Next Action: Approval Decision",
        subtitle: `Stage ${Math.min(request.current_approver_index + 1, (request.approval_chain ?? []).length)} of ${(request.approval_chain ?? []).length}: Waiting for ${request.approval_chain?.[request.current_approver_index] ? titleCase(request.approval_chain[request.current_approver_index]) : "Approver"}`, 
        badge: <StatusBadge status={request.status} />,
        content: (
          <div className="flex flex-col gap-4">
            <ApprovalChainVisual request={request} />
            <ApprovalActions request={request} onDecided={refresh} />
          </div>
        ),
      };
    }

    if (request.status === "approved") {
      if (shownContract && shownContract.status !== "signed") {
        return {
          kind: "contract",
          title: "Next Action: Sign Contract",
          subtitle: `Contract generated (${titleCase(shownContract.template_used)}). Review and execute digital signature.`,
          badge: <ContractStatusBadge status={shownContract.status} />,
          content: (
            <div className="flex flex-col gap-3">
              <ContractActions contract={shownContract} request={request} onChanged={refresh} autoOpen={params.get("action") === "sign" ? "sign" : undefined} />
            </div>
          ),
        };
      }
      if (!shownContract) {
        return {
          kind: "contract",
          title: "Next Action: Generate Contract",
          subtitle: "Purchase request is fully approved. Generate the legal agreement to proceed.",
          badge: <Badge tone="brand">Ready for contract</Badge>,
          content: (
            <div className="flex flex-col gap-3">
              <ContractActions contract={null} request={request} onChanged={refresh} />
            </div>
          ),
        };
      }
    }

    if (request.status === "ordered" || request.status === "partially_received") {
      return {
        kind: "receipt",
        title: "Next Action: Confirm Delivery / Receipt",
        subtitle: "Items have been ordered. Record deliveries as goods and licenses arrive.",
        badge: <StatusBadge status={request.status} />,
        content: (
          <div className="flex flex-col gap-3">
            <ApprovalActions request={request} onDecided={refresh} />
          </div>
        ),
      };
    }

    return null;
  })();

  const chain = request.approval_chain ?? [];
  const approvalFigure =
    request.status === "rejected"
      ? "Rejected"
      : chain.length === 0
        ? "Auto-approved"
        : request.status === "pending_approval"
          ? `${Math.min(request.current_approver_index, chain.length)} of ${chain.length} done`
          : `${chain.length} of ${chain.length} done`;

  return (
    <div className="flex flex-col gap-6">
      <DocketHeader
        reference={<RefCopy prefix="PR" id={request.id} />}
        title={`${titleCase(request.request_type)} procurement — ${request.department ?? "no department"}`}
        status={<StatusBadge status={request.status} />}
        meta={<span>Submitted by <PersonName email={request.requested_by} /> on {formatDate(request.created_at)}</span>}
      />

      {/* Topmost Next Action Panel */}
      {nextAction && (
        <Card className="border-accent/40 bg-sheet shadow-sm ring-1 ring-accent/20 animate-fade-in">
          <CardHeader
            title={nextAction.title}
            subtitle={nextAction.subtitle}
            action={nextAction.badge}
          />
          <CardBody>{nextAction.content}</CardBody>
        </Card>
      )}

      <LedgerStrip cols={4} label="Request figures">
        <MetricCard label="Amount" value={formatCurrency(request.amount, request.currency ?? "INR")} />
        <MetricCard
          label="Vendor risk"
          value={vendorRisk?.risk_band ?? (request.vendor_id ? (vendorRiskLoading ? "…" : "Not scored") : "No vendor")}
          tone={vendorRisk?.risk_band === "High" ? "danger" : vendorRisk?.risk_band === "Medium" ? "warning" : "neutral"}
          hint={vendorRisk?.risk_score != null ? `Score ${Math.round(vendorRisk.risk_score * 100)} of 100` : undefined}
        />
        <MetricCard label="Approval" value={approvalFigure} tone={request.status === "rejected" ? "danger" : "neutral"} />
        <MetricCard
          label="Contract"
          value={shownContract ? titleCase(shownContract.status) : "Not yet"}
          hint={shownContract?.generated_at ? `Generated ${formatDate(shownContract.generated_at)}` : undefined}
        />
      </LedgerStrip>

      <Card>
        <CardHeader title="Procurement lifecycle" />
        <CardBody className="overflow-x-auto scrollbar-thin" tabIndex={0} role="region" aria-label="Procurement lifecycle steps">
          <LifecycleStepper stages={lifecycle} onSelect={select} selectedKey={selectedKey} />
        </CardBody>
        {selected && (
          <div className="border-t border-rule bg-surface-subtle px-4 py-4 sm:px-5 animate-slide-up">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-heading font-semibold text-ink">{selected.label}</p>
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
              attachedDoc={attachedDoc}
              onChanged={refresh}
            />
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <div className="flex min-w-0 flex-col gap-6 xl:col-span-8">
          <Card>
            <CardHeader title="Request information" />
            <CardBody>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
                <Field label="Requester" value={<PersonName email={request.requested_by} />} />
                <Field label="Department" value={request.department} />
                <Field label="Category" value={titleCase(request.request_type)} />
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

          {(request.document_id || attachedDoc) && (
            <DocumentPreviewCard
              documentId={request.document_id ?? attachedDoc?.id}
              initialDocument={attachedDoc}
              title="Attached Supporting Document"
              subtitle={attachedDoc?.original_filename ? `Uploaded file: ${attachedDoc.original_filename}` : undefined}
            />
          )}

          <Card>
            <CardHeader title="Approval"  />
            <CardBody className="flex flex-col gap-4">
              <ApprovalChainVisual request={request} />
              {nextAction?.kind !== "approval" && nextAction?.kind !== "receipt" && (
                <ApprovalActions request={request} onDecided={refresh} />
              )}
            </CardBody>
          </Card>
        </div>

        <div className="flex min-w-0 flex-col gap-6 xl:col-span-4">
          <ProcurementAssessment request={request} vendorRisk={vendorRisk} vendorRiskLoading={vendorRiskLoading} />
          {["approved", "ordered", "partially_received", "fulfilled", "partially_invoiced", "invoice_received"].includes(request.status ?? "") && (
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
                      {contract.signed_by && ` · signed by ${withNames(contract.signed_by)}`}
                    </span>
                    <Link to={`/app/contracts/${contract.id}`} className="font-medium text-accent hover:underline">
                      Open contract
                    </Link>
                  </div>
                )}
                {nextAction?.kind !== "contract" && (
                  <ContractActions contract={contract ?? null} request={request} onChanged={refresh} layout="stack" />
                )}
              </CardBody>
            </Card>
          )}

          <Section title="Paper trail">
            <Timeline events={trail} />
          </Section>
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
  attachedDoc,
  onChanged,
}: {
  stage: LifecycleStage;
  request: PurchaseRequest;
  vendor: VendorSummary | null;
  vendorRisk: VendorRisk | null;
  contract: Contract | null;
  attachedDoc?: DocumentRecord | null;
  onChanged: () => void;
}) {
  const { withNames } = usePeople();
  switch (stage.key) {
    case "created":
      return (
        <p className="text-sm text-slate-700">
          Raised by <PersonName email={request.requested_by} /> ({request.department ?? "no department"}) on {formatDateTime(request.created_at)} for{" "}
          {formatCurrency(request.amount, request.currency ?? "INR")}.
        </p>
      );
    case "document":
      return (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-slate-700">
            {stage.detail ?? (attachedDoc ? "Supporting document attached." : "No document attached.")} Documents are processed by the document intelligence pipeline —{" "}
            <Link to="/app/documents" className="text-brand-700 hover:underline">
              open Documents
            </Link>
            .
          </p>
          {attachedDoc && (
            <div className="max-w-md">
              <DocumentPreviewCard initialDocument={attachedDoc} title="Attached Document Preview" compact />
            </div>
          )}
        </div>
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
              ? `Signed by ${withNames(contract.signed_by) || "the signer"} on ${formatDateTime(contract.signed_at)}.`
              : contract.status === "pending_signature"
                ? `${contract.sent_automatically ? "Sent for signature automatically after approval — w" : "W"}aiting for signature (${contract.esign_provider_ref ?? "built-in e-sign"}).`
                : "Not sent for signature yet."}
          </p>
          <ContractActions contract={contract} request={request} onChanged={onChanged} autoOpen={contract.status !== "signed" ? "sign" : undefined} />
        </div>
      );
    case "fulfillment":
      if (request.status === "ordered") {
        return <ApprovalActions request={request} onDecided={() => onChanged()} />;
      }
      return (
        <p className="text-sm text-slate-700">
          {["fulfilled", "partially_invoiced", "invoice_received"].includes(request.status ?? "")
            ? "Fulfilled: the goods/licences were received."
            : "After the contract is signed the request is ordered; it's fulfilled once someone confirms the goods/licences arrived."}
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
      <p className="mb-2 text-13 font-medium text-ink-2">Line items</p>
      <div className="flex flex-col gap-1.5">
        {request.items.map((item, i) => (
          <div key={i} className="flex justify-between border-b border-rule px-1 py-1.5 text-sm last:border-0">
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
    <div className="min-w-0">
      <dt className="text-13 text-ink-3">{label}</dt>
      <dd className="mt-0.5 break-words font-medium text-ink">{value ?? "—"}</dd>
    </div>
  );
}
