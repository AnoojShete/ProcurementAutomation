import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, FileSignature, Info, ScrollText, Check, ShieldCheck } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { contractsApi } from "@/api/contracts";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ContractStatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { DigitalSignatureModal } from "@/components/contracts/DigitalSignatureModal";
import { SignatureCertificateModal } from "@/components/contracts/SignatureCertificateModal";
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
  const [signError, setSignError] = useState<string | null>(null);
  const [signSuccess, setSignSuccess] = useState<string | null>(null);

  const [isSignModalOpen, setIsSignModalOpen] = useState(false);
  const [isDigitalSignModalOpen, setIsDigitalSignModalOpen] = useState(false);
  const [isCertModalOpen, setIsCertModalOpen] = useState(false);

  const [selectedProvider, setSelectedProvider] = useState<"builtin" | "documenso">("builtin");
  const [signerEmail, setSignerEmail] = useState("");

  const canAct = user?.role === "approver" || user?.role === "finance" || user?.role === "admin";

  const handleOpenSendModal = () => {
    setSignerEmail(user?.email || "authorized_signer@company.com");
    setIsSignModalOpen(true);
  };

  const handleOpenDigitalSignModal = () => {
    setIsDigitalSignModalOpen(true);
  };

  const handleSendForSignature = async () => {
    if (!contract) return;
    setSending(true);
    setSignError(null);
    try {
      await contractsApi.sendForSignature(contract.id, signerEmail || undefined, selectedProvider);
      setIsSignModalOpen(false);
      setSignSuccess(`Contract dispatched for signature via ${selectedProvider === "documenso" ? "Documenso" : "Built-in Secure E-Sign"}.`);
      reload();
    } catch (e) {
      setSignError(e instanceof ApiError ? e.message : "Unable to send for signature.");
    } finally {
      setSending(false);
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

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <ScrollText className="size-5 text-slate-400" />
            <h1 className="text-xl font-semibold text-slate-900">{vendor?.name ?? "Contract"} — {titleCase(contract.template_used)}</h1>
            <ContractStatusBadge status={contract.status} />
          </div>
          <p className="mt-1 font-mono text-xs text-slate-400">{contract.id}</p>
        </div>
        <div className="flex items-center gap-2">
          {canAct && contract.status === "draft" && (
            <>
              <Button icon={<FileSignature className="size-4" />} onClick={handleOpenDigitalSignModal}>
                Sign Contract
              </Button>
              <Button variant="secondary" onClick={handleOpenSendModal}>
                Send for Signature
              </Button>
            </>
          )}
          {canAct && contract.status === "pending_signature" && (
            <Button
              icon={<FileSignature className="size-4" />}
              onClick={handleOpenDigitalSignModal}
            >
              Sign Contract Now
            </Button>
          )}
          {contract.status === "signed" && (
            <Button
              variant="secondary"
              icon={<ShieldCheck className="size-4 text-emerald-600" />}
              onClick={() => setIsCertModalOpen(true)}
            >
              View Signature Certificate
            </Button>
          )}
        </div>
      </div>

      {signError && <InlineError message={signError} />}
      {signSuccess && <InlineSuccess message={signSuccess} />}

      {contract.status === "pending_signature" && (
        <div className="flex items-start justify-between gap-4 rounded-lg border border-brand-100 bg-brand-50 px-3.5 py-2.5 text-sm text-brand-700">
          <div className="flex items-start gap-2">
            <Info className="mt-0.5 size-4 shrink-0" />
            <div className="flex flex-col gap-1">
              <span>
                Awaiting electronic signature ({contract.esign_provider_ref ?? "Built-in E-Sign"}). Click &ldquo;Sign Contract Now&rdquo; above to execute with legal cryptographic seal.
              </span>
              <span className="text-xs text-brand-600">
                Signatures are verified under the US ESIGN Act and UETA with tamper-evident cryptographic hashes.
              </span>
            </div>
          </div>
        </div>
      )}

      {contract.status === "signed" && (
        <div className="flex items-center justify-between gap-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-sm text-emerald-800">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="size-4 text-emerald-600 shrink-0" />
            <span>
              Contract fully executed and legally signed by <strong>{contract.signed_by ?? "Authorized Signer"}</strong> on {formatDateTime(contract.signed_at)}.
            </span>
          </div>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setIsCertModalOpen(true)}
            icon={<ShieldCheck className="size-3.5 text-emerald-600" />}
          >
            Audit Certificate
          </Button>
        </div>
      )}

      {/* Modal: Dispatch for Signature */}
      <Modal
        open={isSignModalOpen}
        onClose={() => setIsSignModalOpen(false)}
        title="Send Contract for Signature"
        footer={
          <>
            <Button variant="secondary" onClick={() => setIsSignModalOpen(false)}>
              Cancel
            </Button>
            <Button loading={sending} onClick={handleSendForSignature} icon={<FileSignature className="size-4" />}>
              Dispatch via {selectedProvider === "documenso" ? "Documenso" : "Built-in Secure E-Sign"}
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
                onClick={() => setSelectedProvider("builtin")}
                className={`flex flex-col items-start rounded-lg border p-3 text-left transition-all ${
                  selectedProvider === "builtin"
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
                onClick={() => setSelectedProvider("documenso")}
                className={`flex flex-col items-start rounded-lg border p-3 text-left transition-all ${
                  selectedProvider === "documenso"
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
      {contract && (
        <DigitalSignatureModal
          open={isDigitalSignModalOpen}
          onClose={() => setIsDigitalSignModalOpen(false)}
          contract={contract}
          defaultSignerEmail={user?.email || "authorized_signer@company.com"}
          defaultSignerName={user?.email?.split("@")[0].replace(".", " ").replace(/\b\w/g, (c) => c.toUpperCase()) || "Authorized Signer"}
          onSuccess={(updated) => {
            setSignSuccess("Contract successfully signed and legally executed!");
            reload();
          }}
        />
      )}

      {/* Modal: Cryptographic Signature Certificate */}
      {contract && (
        <SignatureCertificateModal
          open={isCertModalOpen}
          onClose={() => setIsCertModalOpen(false)}
          contract={contract}
          certificate={contract.signature_certificate}
        />
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="Contract Details" />
          <CardBody>
            <dl className="flex flex-col gap-3 text-sm">
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
          <CardHeader title="Contract Preview" subtitle="Generated text, with clause extraction run on the output" />
          <CardBody>
            {contract.contract_text ? (
              <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded-lg bg-surface-subtle p-4 font-mono text-xs leading-relaxed text-slate-700">
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
    <div className="flex items-center justify-between">
      <dt className="text-slate-400">{label}</dt>
      <dd className="font-medium text-slate-800">{value}</dd>
    </div>
  );
}
