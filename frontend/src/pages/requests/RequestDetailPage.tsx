import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Ban, CheckCircle2, XCircle, ScrollText, FileSignature, Check } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { usePolling } from "@/hooks/usePolling";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { contractsApi } from "@/api/contracts";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { StatusBadge, ContractStatusBadge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { InlineError, InlineSuccess, InlineInfo } from "@/components/ui/ErrorState";
import { LifecycleStepper } from "@/components/ui/LifecycleStepper";
import { ApprovalChainVisual } from "@/components/requests/ApprovalChainVisual";
import { ProcurementAssessment } from "@/components/requests/ProcurementAssessment";
import { Timeline, type TimelineEvent } from "@/components/ui/Timeline";
import { Skeleton } from "@/components/ui/Skeleton";
import { DigitalSignatureModal } from "@/components/contracts/DigitalSignatureModal";
import { formatCurrency, formatDateTime, titleCase } from "@/lib/format";
import { deriveLifecycle } from "@/lib/lifecycle";
import type { PurchaseRequest, VendorRisk, ContractTemplate } from "@/types/api";
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

  const { data: contracts, reload: reloadContracts } = useApi(() => contractsApi.list(200), []);
  const linkedContract = contracts?.find((c) => c.purchase_request_id === request?.id) ?? null;

  // Contract & E-sign states
  const [selectedTemplate, setSelectedTemplate] = useState<ContractTemplate>("hardware_purchase");
  const [generatingContract, setGeneratingContract] = useState(false);
  const [contractActionError, setContractActionError] = useState<string | null>(null);
  const [contractActionSuccess, setContractActionSuccess] = useState<string | null>(null);

  const [isSignModalOpen, setIsSignModalOpen] = useState(false);
  const [isDigitalSignModalOpen, setIsDigitalSignModalOpen] = useState(false);
  const [signProvider, setSignProvider] = useState<"builtin" | "documenso">("builtin");
  const [signerEmail, setSignerEmail] = useState("");
  const [sendingSign, setSendingSign] = useState(false);

  useEffect(() => {
    if (request?.request_type === "hardware") setSelectedTemplate("hardware_purchase");
    else if (request?.request_type === "license" || request?.request_type === "saas") setSelectedTemplate("saas_subscription");
    else setSelectedTemplate("professional_services");
  }, [request?.request_type]);

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

  const handleGenerateContract = async () => {
    if (!request) return;
    setGeneratingContract(true);
    setContractActionError(null);
    setContractActionSuccess(null);
    try {
      await contractsApi.generate(request.id, selectedTemplate);
      setContractActionSuccess("Contract generated successfully!");
      reloadContracts();
      reload();
    } catch (e) {
      setContractActionError(e instanceof ApiError ? e.message : "Failed to generate contract.");
    } finally {
      setGeneratingContract(false);
    }
  };

  const handleOpenSignModal = () => {
    setSignerEmail(request?.requested_by || user?.email || "authorized_signer@company.com");
    setIsSignModalOpen(true);
  };

  const handleSendForSignature = async () => {
    if (!linkedContract) return;
    setSendingSign(true);
    setContractActionError(null);
    setContractActionSuccess(null);
    try {
      await contractsApi.sendForSignature(linkedContract.id, signerEmail || undefined, signProvider);
      setIsSignModalOpen(false);
      setContractActionSuccess(`Sent for signature via ${signProvider === "documenso" ? "Documenso" : "DocuSign"}.`);
      reloadContracts();
    } catch (e) {
      setContractActionError(e instanceof ApiError ? e.message : "Failed to send for signature.");
    } finally {
      setSendingSign(false);
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

          {contractActionSuccess && <InlineSuccess message={contractActionSuccess} />}
          {contractActionError && <InlineError message={contractActionError} />}

          {request.status === "approved" && !linkedContract && (
            <Card>
              <CardHeader
                title="Contract Generation"
                subtitle="Request is approved — generate the agreement for e-signing"
              />
              <CardBody className="flex flex-col gap-3">
                <div>
                  <label className="text-xs font-medium text-slate-700">Contract Template</label>
                  <select
                    value={selectedTemplate}
                    onChange={(e) => setSelectedTemplate(e.target.value as ContractTemplate)}
                    className="mt-1 w-full rounded-lg border border-surface-border px-3 py-1.5 text-sm focus:border-brand-500 focus:outline-none"
                  >
                    <option value="hardware_purchase">Hardware Purchase Agreement</option>
                    <option value="saas_subscription">SaaS Subscription Agreement</option>
                    <option value="professional_services">Professional Services Agreement</option>
                  </select>
                </div>
                <Button
                  loading={generatingContract}
                  onClick={handleGenerateContract}
                  icon={<ScrollText className="size-4" />}
                >
                  Generate Contract
                </Button>
              </CardBody>
            </Card>
          )}

          {linkedContract && (
            <Card>
              <CardHeader
                title="Contract & E-Signature"
                action={<ContractStatusBadge status={linkedContract.status} />}
              />
              <CardBody className="flex flex-col gap-3 text-sm">
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>Template: <strong className="text-slate-700">{titleCase(linkedContract.template_used)}</strong></span>
                  <span className="font-mono">{linkedContract.id.slice(0, 8)}</span>
                </div>

                {linkedContract.status === "draft" && (
                  <div className="flex flex-col gap-2 rounded-lg border border-surface-border bg-surface-subtle p-3">
                    <p className="text-xs text-slate-600">Contract is generated. Select an e-signature provider:</p>
                    <Button
                      size="sm"
                      icon={<FileSignature className="size-4" />}
                      onClick={handleOpenSignModal}
                    >
                      Send for Signature
                    </Button>
                  </div>
                )}

                {linkedContract.status === "pending_signature" && (
                  <div className="flex flex-col gap-2 rounded-lg border border-brand-100 bg-brand-50 p-3">
                    <div className="text-xs text-brand-800">
                      Awaiting signature ({linkedContract.esign_provider_ref ?? "Built-in Secure E-Sign"})
                    </div>
                    <p className="text-[11px] text-brand-600">
                      Signatures are cryptographically sealed under the US ESIGN Act and UETA.
                    </p>
                    <Button
                      size="sm"
                      icon={<FileSignature className="size-4" />}
                      onClick={() => setIsDigitalSignModalOpen(true)}
                    >
                      Sign Contract Now
                    </Button>
                  </div>
                )}

                {linkedContract.status === "signed" && (
                  <div className="rounded-lg bg-emerald-50 p-3 text-xs text-emerald-800">
                    ✓ Contract fully executed by {linkedContract.signed_by ?? "Authorized Signer"} on {formatDateTime(linkedContract.signed_at)}
                  </div>
                )}

                <Button variant="secondary" size="sm" onClick={() => navigate(`/app/contracts/${linkedContract.id}`)}>
                  View full contract details →
                </Button>
              </CardBody>
            </Card>
          )}
        </div>
      </div>

      <Modal
        open={isSignModalOpen}
        onClose={() => setIsSignModalOpen(false)}
        title="Send Contract for Signature"
        footer={
          <>
            <Button variant="secondary" onClick={() => setIsSignModalOpen(false)}>
              Cancel
            </Button>
            <Button loading={sendingSign} onClick={handleSendForSignature} icon={<FileSignature className="size-4" />}>
              Dispatch via {signProvider === "documenso" ? "Documenso" : "Built-in Secure E-Sign"}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4 text-sm">
          <div>
            <label className="mb-1 block font-medium text-slate-700">E-Signature Provider</label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setSignProvider("builtin")}
                className={`flex flex-col items-start rounded-lg border p-3 text-left transition-all ${
                  signProvider === "builtin"
                    ? "border-brand-600 bg-brand-50/50 ring-2 ring-brand-500/20"
                    : "border-surface-border hover:border-slate-300"
                }`}
              >
                <div className="flex items-center gap-1.5 font-medium text-slate-900">
                  <span>Built-in Secure E-Sign</span>
                  <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800">Recommended</span>
                </div>
                <p className="mt-1 text-xs text-slate-500">Instant in-platform legal signing with tamper-evident cryptographic SHA-256 seal.</p>
              </button>

              <button
                type="button"
                onClick={() => setSignProvider("documenso")}
                className={`flex flex-col items-start rounded-lg border p-3 text-left transition-all ${
                  signProvider === "documenso"
                    ? "border-brand-600 bg-brand-50/50 ring-2 ring-brand-500/20"
                    : "border-surface-border hover:border-slate-300"
                }`}
              >
                <div className="flex items-center gap-1.5 font-medium text-slate-900">
                  <span>Documenso</span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-700">REST API</span>
                </div>
                <p className="mt-1 text-xs text-slate-500">Open-source e-signature platform via Documenso cloud or self-hosted API.</p>
              </button>
            </div>
          </div>

          <div>
            <label className="mb-1 block font-medium text-slate-700">Signer Email Address</label>
            <input
              type="email"
              value={signerEmail}
              onChange={(e) => setSignerEmail(e.target.value)}
              placeholder="signer@company.com"
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
            />
            <p className="mt-1 text-xs text-slate-400">
              The contract signature request will be assigned to this email address.
            </p>
          </div>
        </div>
      </Modal>

      {/* Modal: Interactive Digital Signature */}
      {linkedContract && (
        <DigitalSignatureModal
          open={isDigitalSignModalOpen}
          onClose={() => setIsDigitalSignModalOpen(false)}
          contract={linkedContract}
          defaultSignerEmail={user?.email || "authorized_signer@company.com"}
          defaultSignerName={user?.email?.split("@")[0].replace(".", " ").replace(/\b\w/g, (c) => c.toUpperCase()) || "Authorized Signer"}
          onSuccess={(updated) => {
            setContractActionSuccess("Contract successfully signed and legally executed!");
            reloadContracts();
            reload();
          }}
        />
      )}
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
