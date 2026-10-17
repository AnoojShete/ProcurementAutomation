import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FilePlus2 } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { learningApi, learningScenarioApi } from "@/api/controls";
import { documentsApi } from "@/api/documents";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/ErrorState";
import { formatCurrency } from "@/lib/format";
import type { DocumentRecord } from "@/types/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Explainer } from "./Explainer";

const MODE = { relaxed: "success", strict: "danger", default: "neutral" } as const;

type Sent = { document_id: string; invoice_number: string; total: number; doc?: DocumentRecord };

export function LearningPanel({ showcase }: { showcase: boolean }) {
  const { data: stats, reload } = useApi(() => learningApi.stats(), []);
  const [sent, setSent] = useState<Sent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pendingIds = sent.filter((s) => !s.doc || !["classified", "failed"].includes(s.doc.status)).map((s) => s.document_id);
  useEffect(() => {
    if (!pendingIds.length) return;
    const t = setInterval(async () => {
      const docs = await Promise.all(pendingIds.map((id) => documentsApi.get(id).then((r) => r.data).catch(() => null)));
      setSent((prev) => prev.map((s) => ({ ...s, doc: docs.find((d) => d?.id === s.document_id) ?? s.doc })));
    }, 1500);
    return () => clearInterval(t);
  }, [pendingIds.join(",")]);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await learningScenarioApi.unusualLabelInvoice();
      setSent((prev) => [{ ...res.data }, ...prev]);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't create the invoice.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Explainer
        problem="Every reviewer correction was thrown away: the next invoice from the same vendor needed the same fix, and one global confidence threshold treated a vendor reviewers always confirm the same as one they always correct."
        control="Each correction records where the right value sits in that vendor's documents (the label before it). Once two reviews agree, new documents are read that way automatically. Each vendor's review threshold follows how often its documents need fixing."
      />
      <Card>
        <CardHeader title="Scenario" subtitle="A vendor that labels its total “Balance Payable”, which the extractor doesn't recognise" />
        <CardBody className="flex flex-col gap-3 text-13 text-slate-600">
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" variant="secondary" icon={<FilePlus2 className="size-3.5" />} loading={busy} disabled={!showcase} onClick={send}>
              Receive a Northwind invoice
            </Button>
            <span>
              Open it, type the total shown on the document, and save. Do that twice; the third invoice comes in with the
              total already filled from the learned label.
            </span>
            <Button size="sm" variant="ghost" onClick={reload}>
              Refresh stats
            </Button>
          </div>
          {error && <InlineError message={error} />}
          {sent.length > 0 && (
            <ul className="divide-y divide-surface-border rounded-md border border-surface-border">
              {sent.map((s) => {
                const learned = (s.doc?.extracted_fields as Record<string, unknown> | undefined)?.learned_fields as
                  | { field: string; action: string }[]
                  | undefined;
                const extracted = s.doc?.extracted_fields?.total as number | null | undefined;
                return (
                  <li key={s.document_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                    <Link to={`/app/documents/${s.document_id}`} className="font-medium text-brand-700 hover:underline">
                      {s.invoice_number}
                    </Link>
                    <span className="text-slate-600">
                      on the document {formatCurrency(s.total)} · extracted{" "}
                      {!s.doc || !["classified", "failed"].includes(s.doc.status) ? (
                        "…"
                      ) : (
                        <span className={extracted === s.total ? "font-medium text-success-700" : "font-medium text-danger-600"}>
                          {extracted != null ? formatCurrency(extracted) : "nothing"}
                        </span>
                      )}
                      {learned?.some((l) => l.field === "total") && " (from learned label)"}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </CardBody>
      </Card>

      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Global review threshold" value={`${Math.round(stats.base_threshold * 100)}%`} />
          <Stat label="Reviews before a label is used" value={String(stats.min_support)} />
          <Stat label="Reviews before calibrating a vendor" value={String(stats.min_reviews_for_calibration)} />
          <Stat
            label="Documents read with learned labels (30d)"
            value={String(stats.daily.reduce((n, d) => n + d.learned, 0))}
          />
        </div>
      )}

      <Card>
        <CardHeader title="Per-vendor learning" subtitle="From reviewed documents" />
        {!stats || stats.vendors.length === 0 ? (
          <CardBody className="text-13 text-slate-500">
            No reviews yet. Correct a field on a document in review — the second agreeing correction for a vendor turns into
            a learned label.
          </CardBody>
        ) : (
          <table className="w-full text-13">
            <thead>
              <tr className="border-b border-surface-border text-left text-xs text-slate-500">
                <th className="px-4 py-2 font-semibold">Vendor</th>
                <th className="px-4 py-2 text-right font-semibold">Reviews</th>
                <th className="px-4 py-2 text-right font-semibold">Needed no fix</th>
                <th className="px-4 py-2 font-semibold">Review threshold</th>
                <th className="px-4 py-2 font-semibold">Learned labels</th>
              </tr>
            </thead>
            <tbody>
              {stats.vendors.map((v) => (
                <tr key={v.vendor_id} className="border-b border-surface-border align-top last:border-0">
                  <td className="px-4 py-2 font-medium text-slate-900">{v.vendor_name}</td>
                  <td className="px-4 py-2 text-right tabular">{v.reviews}</td>
                  <td className="px-4 py-2 text-right tabular">{v.clean}</td>
                  <td className="px-4 py-2">
                    <Badge tone={MODE[v.mode]}>
                      {Math.round(v.threshold * 100)}% · {v.mode}
                    </Badge>
                  </td>
                  <td className="px-4 py-2">
                    {v.hints.length === 0 ? (
                      <span className="text-slate-400">—</span>
                    ) : (
                      <ul className="flex flex-col gap-0.5">
                        {v.hints.map((h) => (
                          <li key={`${h.field}-${h.label}`} className={h.active ? "text-slate-800" : "text-slate-400"}>
                            {h.field.replace(/_/g, " ")} ← “{h.label}” ×{h.support}
                            {!h.active && " (needs another review)"}
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {stats && stats.daily.length > 0 && (
        <Card>
          <CardHeader title="Review rate, last 30 days" subtitle="Share of processed documents sent to human review" />
          <CardBody>
            <div className="flex h-28 items-end gap-1">
              {stats.daily.map((d) => {
                const pct = d.documents ? d.needs_review / d.documents : 0;
                return (
                  <div key={d.day} className="flex h-full flex-1 flex-col justify-end" title={`${d.day}: ${d.needs_review}/${d.documents} to review, ${d.learned} with learned labels`}>
                    <div className="w-full rounded-t bg-brand-500/80" style={{ height: `${Math.max(pct * 100, 2)}%` }} />
                  </div>
                );
              })}
            </div>
            <div className="mt-1 flex justify-between text-xs text-slate-500">
              <span>{stats.daily[0].day}</span>
              <span>{stats.daily[stats.daily.length - 1].day}</span>
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-surface-border bg-white px-4 py-3">
      <p className="text-xs text-slate-600">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular text-slate-900">{value}</p>
    </div>
  );
}
