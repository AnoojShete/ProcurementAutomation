import { useMemo } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { CheckCircle2, Clock } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { contractsApi } from "@/api/contracts";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ContractStatusBadge } from "@/components/ui/Badge";
import { ContractActions, isDocumensoLive } from "@/components/contracts/ContractActions";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatDate, formatDateTime, titleCase } from "@/lib/format";
import { CONTRACT_RENEWAL_ALERT_DAYS } from "@/lib/constants";

/** The contract agent's page for one contract. Its actions come from
 * ContractActions, the same panel the request page uses. */
export function ContractDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const { data: contract, loading, error, reload } = useApi(() => contractsApi.get(id!), [id]);
  usePageHeader(contract ? `Contract ${contract.id.slice(0, 8)}` : "Contract", "Contracts");
  const { data: vendors } = useApi(() => vendorsApi.list(200), []);
  const vendor = vendors?.find((v) => v.id === contract?.vendor_id);
  const action = params.get("action");

  const renewalMilestones = useMemo(() => {
    if (!contract?.contract_end_date || !contract.notice_period_days) return [];
    const end = new Date(contract.contract_end_date);
    return CONTRACT_RENEWAL_ALERT_DAYS.map((days) => {
      const date = new Date(end);
      date.setDate(date.getDate() - days);
      return { days, date, passed: date.getTime() < Date.now() };
    });
  }, [contract]);

  if (loading && !contract) return <Skeleton className="h-96" />;
  if (error || !contract) return <ErrorState message={error ?? "Contract not found."} onRetry={reload} />;

  const ref = contract.esign_provider_ref ?? "";
  const providerName = ref.startsWith("docusign") ? "DocuSign (sandbox)" : ref.startsWith("builtin") ? "the built-in e-sign" : "Documenso";

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
          {contract.purchase_request_id && (
            <Link to={`/app/requests/${contract.purchase_request_id}`} className="text-xs text-brand-700 hover:underline">
              From request PR-{contract.purchase_request_id.slice(0, 8)} →
            </Link>
          )}
        </div>
        <ContractActions
          contract={contract}
          onChanged={reload}
          autoOpen={action === "sign" || action === "send" ? action : undefined}
        />
      </div>

      {contract.status === "pending_signature" && (
        <div className="flex items-start gap-2 rounded-md border border-warning-500/40 bg-warning-50 px-4 py-2.5 text-13 text-slate-800">
          <Clock className="mt-0.5 size-4 shrink-0 text-warning-600" />
          <span>
            Waiting for the signer in {providerName}
            {ref && <span className="ml-1 font-mono text-xs text-slate-500">({ref})</span>}.{" "}
            {isDocumensoLive(contract)
              ? "The contract updates automatically when Documenso reports it completed."
              : "Use “Sign now” to sign it in the platform."}
          </span>
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
