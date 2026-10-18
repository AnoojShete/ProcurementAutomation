import { usePeople } from "@/hooks/usePeople";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { CheckCircle2, Clock } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { contractsApi } from "@/api/contracts";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ContractStatusBadge } from "@/components/ui/Badge";
import { ContractActions, isProviderLive } from "@/components/contracts/ContractActions";
import { VendorRiskPanel } from "@/components/contracts/VendorRiskPanel";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { DocketHeader, RefCopy } from "@/components/ui/DocketHeader";
import { formatDate, formatDateTime, titleCase } from "@/lib/format";

/** The contract agent's page for one contract. Its actions come from
 * ContractActions, the same panel the request page uses. */
export function ContractDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const { withNames } = usePeople();
  const { data: contract, loading, error, reload } = useApi(() => contractsApi.get(id!), [id]);
  usePageHeader(contract ? `Contract ${contract.id.slice(0, 8)}` : "Contract", "Contracts");
  const { data: vendors } = useApi(() => vendorsApi.list(200), []);
  const vendor = vendors?.find((v) => v.id === contract?.vendor_id);
  const action = params.get("action");

  // Same dates the renewal workflow uses: counted back from the notice deadline.
  const renewalMilestones = contract?.renewal_reminders ?? [];

  if (loading && !contract) return <Skeleton className="h-96" />;
  if (error || !contract) return <ErrorState message={error ?? "Contract not found."} onRetry={reload} />;

  const ref = contract.esign_provider_ref ?? "";
  const providerName = ref.startsWith("docusign") ? "DocuSign (sandbox)" : ref.startsWith("builtin") ? "the built-in e-sign" : "Documenso";

  return (
    <div className="flex flex-col gap-4">
      <DocketHeader
        reference={
          <>
            <RefCopy prefix="CT" id={contract.id} />
            {contract.purchase_request_id && (
              <Link to={`/app/requests/${contract.purchase_request_id}`} className="text-13 text-accent hover:underline">
                From request PR-{contract.purchase_request_id.slice(0, 8)}
              </Link>
            )}
          </>
        }
        title={`${vendor?.name ?? "Contract"} · ${titleCase(contract.template_used)}`}
        status={<ContractStatusBadge status={contract.status} />}
        meta={<span>Version {contract.version ?? 1} · generated {formatDate(contract.generated_at)}</span>}
        actions={
          <ContractActions
            contract={contract}
            onChanged={reload}
            autoOpen={action === "sign" || action === "send" ? action : undefined}
          />
        }
      />

      {contract.status === "pending_signature" && (
        <div className="flex items-start gap-2 rounded-md border border-warning-500/40 bg-warning-50 px-4 py-2.5 text-13 text-slate-800">
          <Clock className="mt-0.5 size-4 shrink-0 text-warning-600" />
          <span>
            Waiting for the signer in {providerName}
            {ref && <span className="ml-1 font-mono text-xs text-slate-500">({ref})</span>}.{" "}
            {isProviderLive(contract)
              ? `The contract updates automatically when ${ref.startsWith("docusign") ? "DocuSign" : "Documenso"} reports it completed.`
              : "Use “Sign now” to sign it in the platform."}
          </span>
        </div>
      )}

      {contract.status !== "signed" && contract.vendor_risk && (
        <div className="flex flex-col gap-1">
          <VendorRiskPanel risk={contract.vendor_risk} />
          {contract.vendor_id && (
            <Link to={`/app/vendors/${contract.vendor_id}`} className="self-end text-xs text-brand-700 hover:underline">
              Vendor's full risk profile
            </Link>
          )}
        </div>
      )}

      {contract.status === "signed" && (
        <div className="flex items-start gap-2 rounded-md border border-success-500/30 bg-success-50 px-4 py-2.5 text-13 text-slate-800">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-600" />
          <span>
            Signed by <span className="font-medium">{withNames(contract.signed_by) || "the signer"}</span> on{" "}
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
              <Row label="Notice Deadline" value={formatDate(contract.notice_deadline ?? null)} />
              <Row label="Next Renewal Reminder" value={contract.next_renewal_reminder ? formatDate(contract.next_renewal_reminder) : "—"} />
              <Row label="Generated" value={formatDateTime(contract.generated_at)} />
              {contract.signed_at && <Row label="Signed" value={formatDateTime(contract.signed_at)} />}
              {contract.signed_by && <Row label="Signed By" value={withNames(contract.signed_by)} />}
              {contract.signature_certificate?.signer_designation && (
                <Row label="Designation" value={contract.signature_certificate.signer_designation} />
              )}
              {contract.reconciliation_status && <Row label="Reconciliation" value={titleCase(contract.reconciliation_status)} />}
            </dl>
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Contract text" />
          <CardBody>
            {contract.contract_text ? (
              <pre
                tabIndex={0}
                role="region"
                aria-label="Contract text"
                className="max-h-[28rem] overflow-y-auto whitespace-pre-wrap rounded border border-rule bg-paper px-4 py-3 font-mono text-13 leading-relaxed text-ink scrollbar-thin"
              >
                {contract.contract_text}
              </pre>
            ) : (
              <p className="text-sm text-slate-500">No contract text available.</p>
            )}

            {contract.status === "signed" && (
              <div className="mt-4 rounded-md border border-slate-200 bg-sheet p-4">
                <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Executed Signature</h4>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3">
                    <span className="text-xs font-medium text-slate-500">For the Company</span>
                    {contract.signature_certificate?.signature_image ? (
                      <div className="my-2 flex h-16 items-center justify-start">
                        <img
                          src={contract.signature_certificate.signature_image}
                          alt="Signature Mark"
                          className="max-h-full max-w-full object-contain"
                        />
                      </div>
                    ) : (
                      <div className="my-2 py-2 font-serif text-lg italic text-slate-800">
                        {contract.signature_certificate?.signer_name ?? contract.signed_by ?? "Signed"}
                      </div>
                    )}
                    <div className="border-t border-slate-300 pt-1.5 text-xs">
                      <p className="font-semibold text-slate-900">
                        {contract.signature_certificate?.signer_name ?? contract.signed_by?.split("<")[0].trim() ?? "—"}
                      </p>
                      {contract.signature_certificate?.signer_designation && (
                        <p className="font-medium text-slate-600">
                          {contract.signature_certificate.signer_designation}
                        </p>
                      )}
                      <p className="mt-0.5 text-caption text-slate-400">
                        Electronically signed · {formatDateTime(contract.signed_at)}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {renewalMilestones.length > 0 && (
        <Card>
          <CardHeader title="Renewal Timeline" />
          <CardBody>
            <div className="flex flex-col gap-0 sm:flex-row">
              {renewalMilestones.map((m, i) => (
                <div key={m.alert_level} className="flex flex-1 items-center">
                  <div className="flex flex-col items-center gap-1.5 text-center">
                    <div className={`flex size-8 items-center justify-center rounded-full ${m.passed ? "bg-success-500 text-white" : "border border-slate-300 text-slate-400"}`}>
                      {m.passed ? <CheckCircle2 className="size-4" /> : <span className="text-xs font-medium">{m.alert_level}d</span>}
                    </div>
                    <p className="text-xs text-slate-600">{formatDate(m.date)}</p>
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
    <div className="flex items-baseline justify-between gap-4 border-b border-rule pb-2 last:border-0 last:pb-0">
      <dt className="shrink-0 text-ink-3">{label}</dt>
      <dd className="min-w-0 break-words text-right text-ink">{value}</dd>
    </div>
  );
}
