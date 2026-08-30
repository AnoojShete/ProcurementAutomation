import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, FileSignature, Info, ScrollText } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { contractsApi } from "@/api/contracts";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ContractStatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
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

  const canAct = user?.role === "approver" || user?.role === "finance" || user?.role === "admin";

  const sendForSignature = async () => {
    if (!contract) return;
    setSending(true);
    setSignError(null);
    try {
      await contractsApi.sendForSignature(contract.id);
      setSignSuccess("Sent for signature. This is a simulated e-sign flow in this environment — the callback that marks it signed is delivered via a webhook, not a live provider.");
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
        {canAct && contract.status === "draft" && (
          <Button icon={<FileSignature className="size-4" />} loading={sending} onClick={sendForSignature}>
            Send for Signature
          </Button>
        )}
      </div>

      {signError && <InlineError message={signError} />}
      {signSuccess && <InlineSuccess message={signSuccess} />}

      {contract.status === "pending_signature" && (
        <div className="flex items-start gap-2 rounded-lg border border-brand-100 bg-brand-50 px-3.5 py-2.5 text-sm text-brand-700">
          <Info className="mt-0.5 size-4 shrink-0" />
          <span>
            Awaiting signature via <span className="font-medium">{contract.esign_provider_ref ?? "a simulated e-sign reference"}</span> — this
            environment simulates the provider callback rather than connecting to a live e-signature service.
          </span>
        </div>
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
