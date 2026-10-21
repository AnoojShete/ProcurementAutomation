import { useState } from "react";
import { Link } from "react-router-dom";
import { Download } from "lucide-react";
import { ApiError } from "@/api/client";
import { contractsApi, type EsignDocument } from "@/api/contracts";
import { useApi } from "@/hooks/useApi";
import { Card, CardHeader } from "@/components/ui/Card";
import { StatusDot } from "@/components/ui/Badge";
import { Tabs } from "@/components/ui/Tabs";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { InlineError } from "@/components/ui/ErrorState";
import { formatCurrency, formatRelativeTime } from "@/lib/format";

const TONE: Record<string, "success" | "warning" | "neutral" | "danger"> = {
  signed: "success",
  pending_signature: "warning",
  draft: "neutral",
  terminated: "danger",
  expired: "neutral",
};

const FILTERS = [
  { key: "", label: "All" },
  { key: "pending_signature", label: "Pending E-Signature" },
  { key: "signed", label: "E-Signature Complete" },
  { key: "draft", label: "Not sent" },
];

/** Every contract's e-signature state with its unsigned and signed PDFs,
 * fetched through the app (never MinIO or the provider's site). Sending
 * and signing stay on the contract's own page. */
export function EsignTracker() {
  const [status, setStatus] = useState("");
  const { data, error, loading } = useApi(() => contractsApi.esignDocuments(status || undefined), [status]);
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // Counts come with every response; keep the last ones while a filter loads.
  useApi(
    () =>
      contractsApi.esignDocuments().then((r) => {
        setCounts((r.meta?.counts as Record<string, number>) ?? null);
        return r;
      }),
    [],
  );

  const download = async (fn: () => Promise<void>) => {
    setDownloadError(null);
    try {
      await fn();
    } catch (e) {
      setDownloadError(e instanceof ApiError ? e.message : "Couldn't download the PDF.");
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <LedgerStrip cols={4} loading={!counts} label="Contracts by signature state">
        {counts && (
          <>
            <MetricCard label="Pending e-signature" value={counts.pending_signature ?? 0} tone="warning" onClick={() => setStatus("pending_signature")} />
            <MetricCard label="E-signature complete" value={counts.signed ?? 0} tone="success" onClick={() => setStatus("signed")} />
            <MetricCard label="Not sent yet" value={counts.draft ?? 0} tone="neutral" onClick={() => setStatus("draft")} />
            <MetricCard label="Ended" value={(counts.terminated ?? 0) + (counts.expired ?? 0)} tone="neutral" />
          </>
        )}
      </LedgerStrip>

      <Card>
        <CardHeader title="Contract documents" subtitle="Unsigned and signed PDFs, with each contract's signature status" />
        <div className="px-2">
          <Tabs tabs={FILTERS} active={status} onChange={setStatus} />
        </div>
        {downloadError && <div className="px-4 pt-3"><InlineError message={downloadError} /></div>}
        {loading && !data ? (
          <div className="p-4"><Skeleton className="h-40" /></div>
        ) : error ? (
          <div className="p-4"><InlineError message={error} /></div>
        ) : !data?.length ? (
          <p className="p-4 text-sm text-ink-3">No contracts {status ? "in this state" : "yet"}.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-13">
              <thead className="bg-sheet-sunk text-13 text-ink-3">
                <tr>
                  <th className="px-4 py-2 font-medium">Contract</th>
                  <th className="px-4 py-2 font-medium">Document</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Signer</th>
                  <th className="px-4 py-2 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {data.map((c) => (
                  <Row key={c.contract_id} c={c} download={download} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Row({ c, download }: { c: EsignDocument; download: (fn: () => Promise<void>) => void }) {
  const signed = c.status === "signed";
  return (
    <tr className="align-top">
      <td className="px-4 py-2.5">
        <Link to={`/app/contracts/${c.contract_id}`} className="font-medium text-accent hover:underline">
          {c.vendor_name ?? `Contract ${c.contract_id.slice(0, 8)}`}
        </Link>
        <p className="text-ink-3">
          {c.template_used?.replace(/_/g, " ") ?? "contract"} v{c.version ?? 1}
          {c.amount != null && ` · ${formatCurrency(c.amount, c.currency ?? "INR")}`}
        </p>
      </td>
      <td className="whitespace-nowrap px-4 py-2.5">
        <div className="flex flex-col gap-1">
          <PdfLink label="Unsigned contract PDF" onClick={() => download(() => contractsApi.downloadDocument(c.contract_id))} />
          {signed && <PdfLink label="Signed contract PDF" onClick={() => download(() => contractsApi.downloadSigned(c.contract_id))} />}
        </div>
      </td>
      <td className="px-4 py-2.5">
        <StatusDot tone={TONE[c.status] ?? "neutral"}>{c.status_label}</StatusDot>
        {c.status === "pending_signature" && (
          <p className="mt-1">
            <Link to={`/app/contracts/${c.contract_id}?action=sign`} className="text-accent hover:underline">
              Open to sign
            </Link>
          </p>
        )}
        {c.status === "draft" && (
          <p className="mt-1">
            <Link to={`/app/contracts/${c.contract_id}?action=send`} className="text-accent hover:underline">
              Send for signature
            </Link>
          </p>
        )}
      </td>
      <td className="px-4 py-2.5 text-ink-2">
        {signed ? c.signed_by ?? "—" : c.signer_email ?? "—"}
        {c.provider && <p className="text-ink-3">{c.provider === "builtin" ? "built-in e-sign" : c.provider}</p>}
      </td>
      <td className="whitespace-nowrap px-4 py-2.5 text-ink-3">
        {signed ? `Signed ${formatRelativeTime(c.signed_at)}` : c.sent_at ? `Sent ${formatRelativeTime(c.sent_at)}` : `Generated ${formatRelativeTime(c.generated_at)}`}
      </td>
    </tr>
  );
}

function PdfLink({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="inline-flex items-center gap-1 text-accent hover:underline">
      <Download className="size-3.5" aria-hidden="true" /> {label}
    </button>
  );
}
