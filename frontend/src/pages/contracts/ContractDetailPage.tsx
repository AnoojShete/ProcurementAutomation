import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, Clock, Download, FileCheck2, FileSignature } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { contractsApi } from "@/api/contracts";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ContractStatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { ErrorState, InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatDate, formatDateTime, titleCase } from "@/lib/format";
import { CONTRACT_RENEWAL_ALERT_DAYS } from "@/lib/constants";
import { ApiError } from "@/api/client";

export function ContractDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { data: contract, loading, error, reload } = useApi(() => contractsApi.get(id!), [id]);
  usePageHeader(contract ? `Contract ${contract.id.slice(0, 8)}` : "Contract", "Contracts");
  const { data: vendors } = useApi(() => vendorsApi.list(200), []);
  const vendor = vendors?.find((v) => v.id === contract?.vendor_id);

  const [sending, setSending] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [signError, setSignError] = useState<string | null>(null);
  const [signSuccess, setSignSuccess] = useState<string | null>(null);

  const [isSignModalOpen, setIsSignModalOpen] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<"documenso" | "docusign">("documenso");
  const [signerEmail, setSignerEmail] = useState("");

  const canAct = user?.role === "approver" || user?.role === "finance" || user?.role === "admin";

  const handleOpenSignModal = () => {
    setSignerEmail(user?.email || "authorized_signer@company.com");
    setIsSignModalOpen(true);
  };

  const handleSendForSignature = async () => {
    if (!contract) return;
    setSending(true);
    setSignError(null);
    try {
      await contractsApi.sendForSignature(contract.id, signerEmail || undefined, selectedProvider);
      setIsSignModalOpen(false);
      setSignSuccess(`Sent to ${signerEmail} for signature.`);
      reload();
    } catch (e) {
      setSignError(e instanceof ApiError ? e.message : "Unable to send for signature.");
    } finally {
      setSending(false);
    }
  };

  const handleSimulateSign = async () => {
    if (!contract) return;
    setSimulating(true);
    setSignError(null);
    try {
      await contractsApi.simulateSign(contract.id);
      setSignSuccess("Contract signed. The signed copy is ready to download.");
      reload();
    } catch (e) {
      setSignError(e instanceof ApiError ? e.message : "Unable to simulate signing.");
    } finally {
      setSimulating(false);
    }
  };

  const [downloading, setDownloading] = useState<"document" | "signed" | null>(null);
  const download = async (kind: "document" | "signed") => {
    if (!contract) return;
    setDownloading(kind);
    setSignError(null);
    try {
      if (kind === "signed") await contractsApi.downloadSigned(contract.id);
      else await contractsApi.downloadDocument(contract.id);
    } catch (e) {
      setSignError(e instanceof ApiError ? e.message : "Download failed.");
    } finally {
      setDownloading(null);
    }
  };

  const renewalMilestones = useMemo(() => {
    if (!contract?.contract_end_date || !contract.notice_period_days) return [];
    const end = new Date(contract.contract_end_date);
    const noticeStart = new Date(end);
    noticeStart.setDate(noticeStart.getDate() - contract.notice_period_days);
    return CONTRACT_RENEWAL_ALERT_DAYS.map((days) => {
      const date = new Date(end);
      date.setDate(date.getDate() - days);
      return { days, date, passed: date.getTime() < Date.now() };
    });
  }, [contract]);

  if (loading) return <Skeleton className="h-96" />;
  if (error || !contract) return <ErrorState message={error ?? "Contract not found."} onRetry={reload} />;

  const isDocumensoLive = contract.esign_provider_ref?.startsWith("documenso-doc-");
  const providerName = contract.esign_provider_ref?.startsWith("docusign") ? "DocuSign (sandbox)" : "Documenso";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h2 className="text-lg font-semibold text-slate-900">
              {vendor?.name ?? "Contract"} · {titleCase(contract.template_used)}
            </h2>
            <ContractStatusBadge status={contract.status} />
          </div>
          <p className="mt-0.5 font-mono text-xs text-slate-500">{contract.id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            icon={<Download className="size-4" />}
            loading={downloading === "document"}
            onClick={() => download("document")}
          >
            {contract.status === "signed" ? "Original PDF" : "Download PDF"}
          </Button>
          {contract.status === "signed" && (
            <Button icon={<FileCheck2 className="size-4" />} loading={downloading === "signed"} onClick={() => download("signed")}>
              Download signed copy
            </Button>
          )}
          {canAct && contract.status === "draft" && (
            <Button icon={<FileSignature className="size-4" />} onClick={handleOpenSignModal}>
              Send for signature
            </Button>
          )}
        </div>
      </div>

      {signError && <InlineError message={signError} />}
      {signSuccess && <InlineSuccess message={signSuccess} />}

      {contract.status === "pending_signature" && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-warning-500/40 bg-warning-50 px-4 py-2.5 text-13 text-slate-800">
          <div className="flex items-start gap-2">
            <Clock className="mt-0.5 size-4 shrink-0 text-warning-600" />
            <span>
              Waiting for the signer in {providerName}
              {contract.esign_provider_ref && (
                <span className="ml-1 font-mono text-xs text-slate-500">({contract.esign_provider_ref})</span>
              )}
              .{" "}
              {isDocumensoLive
                ? "The contract updates automatically when Documenso reports it completed."
                : "No live provider is configured, so signing is simulated in this environment."}
            </span>
          </div>
          {canAct && !isDocumensoLive && (
            <Button size="sm" variant="secondary" loading={simulating} onClick={handleSimulateSign}>
              Simulate signature
            </Button>
          )}
        </div>
      )}

      {contract.status === "signed" && (
        <div className="flex items-start gap-2 rounded-md border border-success-500/30 bg-success-50 px-4 py-2.5 text-13 text-slate-800">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-600" />
          <span>
            Signed by <span className="font-medium">{contract.signed_by ?? "the signer"}</span> on{" "}
            {formatDateTime(contract.signed_at)}. The signed copy includes a certificate of completion with the
            signing audit trail.
          </span>
        </div>
      )}

      <Modal
        open={isSignModalOpen}
        onClose={() => setIsSignModalOpen(false)}
        title="Send for signature"
        footer={
          <>
            <Button variant="secondary" onClick={() => setIsSignModalOpen(false)}>
              Cancel
            </Button>
            <Button loading={sending} onClick={handleSendForSignature} disabled={!signerEmail}>
              Send
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4 text-sm">
          <div>
            <label htmlFor="signer-email" className="mb-1 block font-medium text-slate-800">
              Signer email
            </label>
            <input
              id="signer-email"
              type="email"
              value={signerEmail}
              onChange={(e) => setSignerEmail(e.target.value)}
              placeholder="signer@company.com"
              className="field"
            />
          </div>
          <fieldset>
            <legend className="mb-1 font-medium text-slate-800">Provider</legend>
            <div className="divide-y divide-surface-border rounded-md border border-surface-border">
              {(
                [
                  ["documenso", "Documenso", "Self-hosted e-signature. Emails the signer a signing link when a Documenso instance is configured."],
                  ["docusign", "DocuSign (sandbox)", "Demo only. Nothing is sent; completion is simulated."],
                ] as const
              ).map(([value, name, desc]) => (
                <label key={value} className="flex cursor-pointer items-start gap-2.5 px-3 py-2.5 hover:bg-surface-subtle">
                  <input
                    type="radio"
                    name="provider"
                    value={value}
                    checked={selectedProvider === value}
                    onChange={() => setSelectedProvider(value)}
                    className="mt-0.5 accent-brand-500"
                  />
                  <span>
                    <span className="block font-medium text-slate-900">{name}</span>
                    <span className="block text-xs text-slate-500">{desc}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <p className="text-xs text-slate-500">The signer receives the contract as a PDF, the same file as “Download PDF”.</p>
        </div>
      </Modal>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Details" />
          <CardBody>
            <dl className="flex flex-col gap-2.5 text-13">
              <Row label="Vendor" value={vendor?.name ?? "—"} />
              <Row label="Template" value={titleCase(contract.template_used)} />
              <Row label="Version" value={String(contract.version ?? 1)} />
              <Row label="Renewal Type" value={titleCase(contract.renewal_type)} />
              <Row label="Notice Period" value={contract.notice_period_days ? `${contract.notice_period_days} days` : "—"} />
              <Row label="End Date" value={formatDate(contract.contract_end_date)} />
              <Row label="Generated" value={formatDateTime(contract.generated_at)} />
              {contract.signed_at && <Row label="Signed" value={formatDateTime(contract.signed_at)} />}
              {contract.signed_by && <Row label="Signed By" value={contract.signed_by} />}
              {contract.reconciliation_status && <Row label="Reconciliation" value={titleCase(contract.reconciliation_status)} />}
            </dl>
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Contract text" subtitle="As generated from the template; clause extraction runs on this text" />
          <CardBody>
            {contract.contract_text ? (
              <pre className="max-h-[28rem] overflow-y-auto whitespace-pre-wrap rounded-md border border-surface-border bg-surface-subtle p-3 font-mono text-xs leading-relaxed text-slate-800">
                {contract.contract_text}
              </pre>
            ) : (
              <p className="text-sm text-slate-500">No contract text available.</p>
            )}
          </CardBody>
        </Card>
      </div>

      {renewalMilestones.length > 0 && (
        <Card>
          <CardHeader title="Renewal Timeline" subtitle="Alert milestones before the notice deadline" />
          <CardBody>
            <div className="flex flex-col gap-0 sm:flex-row">
              {renewalMilestones.map((m, i) => (
                <div key={m.days} className="flex flex-1 items-center">
                  <div className="flex flex-col items-center gap-1.5 text-center">
                    <div className={`flex size-8 items-center justify-center rounded-full ${m.passed ? "bg-success-500 text-white" : "border border-slate-300 text-slate-400"}`}>
                      {m.passed ? <CheckCircle2 className="size-4" /> : <span className="text-xs font-medium">{m.days}d</span>}
                    </div>
                    <p className="text-xs text-slate-600">{formatDate(m.date.toISOString())}</p>
                  </div>
                  {i < renewalMilestones.length - 1 && <div className="mx-2 h-0.5 flex-1 bg-slate-200" />}
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="truncate text-right text-slate-900">{value}</dd>
    </div>
  );
}
