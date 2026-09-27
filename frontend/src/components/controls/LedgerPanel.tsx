import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Play } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { ledgerApi } from "@/api/controls";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { ApiError } from "@/api/client";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusDot } from "@/components/ui/Badge";
import { InlineError } from "@/components/ui/ErrorState";
import { formatCurrency, formatRelativeTime } from "@/lib/format";
import type { InvoiceMatchResult, RequestLedger } from "@/types/api";
import { Explainer } from "./Explainer";

const TONE = { matched: "success", partial: "brand", variance: "danger", ambiguous: "warning", no_match: "neutral" } as const;
const VERDICT: Record<string, string> = {
  matched: "Would be booked — the request becomes fully invoiced",
  partial: "Would be booked as a partial invoice",
  variance: "Would be held for review — it doesn't fit the purchase request",
  ambiguous: "Would go to review — more than one request could take it",
  no_match: "Would go to review — nothing to match against",
};

type Line = { description: string; quantity: string; unit_price: string };

export function LedgerPanel() {
  const { data: requests } = useApi(() => requestsApi.list(200), []);
  const { data: vendors } = useApi(() => vendorsApi.list(200), []);
  const { data: recent } = useApi(() => ledgerApi.matches({ limit: 15 }), []);
  const open = useMemo(
    () =>
      (requests ?? []).filter(
        (r) => r.vendor_id && ["approved", "fulfilled", "partially_invoiced"].includes(r.status ?? "") && (r.items?.length ?? 0) > 0,
      ),
    [requests],
  );
  const vendorName = (id: string | null | undefined) => vendors?.find((v) => v.id === id)?.name ?? "—";

  const [requestId, setRequestId] = useState("");
  const [ledger, setLedger] = useState<RequestLedger | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [total, setTotal] = useState("");
  const [result, setResult] = useState<InvoiceMatchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (!requestId && open.length) setRequestId(open[0].id);
  }, [open, requestId]);

  useEffect(() => {
    if (!requestId) return;
    setResult(null);
    ledgerApi.forRequest(requestId).then((r) => {
      setLedger(r.data);
      const remaining = r.data.lines.map((l) => ({
        description: l.description,
        quantity: String(Math.max(l.quantity - l.invoiced_quantity, 0)),
        unit_price: String(l.unit_price),
      }));
      setLines(remaining);
      setTotal(String(r.data.remaining_amount));
    });
  }, [requestId]);

  const req = open.find((r) => r.id === requestId);

  const simulate = async () => {
    if (!req?.vendor_id) return;
    setRunning(true);
    setError(null);
    try {
      const res = await ledgerApi.simulate({
        document_id: crypto.randomUUID(),
        vendor_id: req.vendor_id,
        total: Number(total),
        lines: lines
          .filter((l) => Number(l.quantity) > 0)
          .map((l) => ({ description: l.description, quantity: Number(l.quantity), unit_price: Number(l.unit_price) })),
      });
      setResult(res.data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Simulation failed.");
    } finally {
      setRunning(false);
    }
  };

  const setLine = (i: number, key: keyof Line, value: string) =>
    setLines((prev) => prev.map((l, j) => (j === i ? { ...l, [key]: value } : l)));

  return (
    <div className="flex flex-col gap-4">
      <Explainer
        problem="Invoices were matched only to requests still marked approved (not ones whose contract was already signed), on the header total within ±5% — so 5% overbilling passed silently, no line or quantity was checked, and partial invoices weren't possible."
        control="Each request keeps a balance per line. An invoice matches only if every line fits what's left at no more than the agreed unit price; paying less is fine, paying more is always flagged. Booking locks the request so two invoices can't spend the same balance."
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title="Match simulator" subtitle="Runs the real matching rules without booking anything" />
          <CardBody className="flex flex-col gap-3 text-13">
            {open.length === 0 ? (
              <p className="text-slate-500">No approved requests with line items and a vendor yet.</p>
            ) : (
              <>
                <label className="flex flex-col gap-1">
                  <span className="font-medium text-slate-800">Purchase request</span>
                  <select value={requestId} onChange={(e) => setRequestId(e.target.value)} className="field">
                    {open.map((r) => (
                      <option key={r.id} value={r.id}>
                        PR-{r.id.slice(0, 8)} · {vendorName(r.vendor_id)} · {formatCurrency(r.amount)} · {r.status}
                      </option>
                    ))}
                  </select>
                </label>
                {ledger && (
                  <p className="text-slate-600">
                    Invoiced {formatCurrency(ledger.invoiced_amount)} of {formatCurrency(ledger.amount)} —{" "}
                    <span className="font-medium text-slate-900">{formatCurrency(ledger.remaining_amount)} left</span>. Edit the
                    invoice below; try raising a unit price by 2%, or a quantity past what's left.
                  </p>
                )}
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-xs text-slate-500">
                      <th className="pb-1 font-medium">Invoice line</th>
                      <th className="w-24 pb-1 font-medium">Qty</th>
                      <th className="w-32 pb-1 font-medium">Unit price</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((l, i) => (
                      <tr key={i}>
                        <td className="py-1 pr-2">
                          <input value={l.description} onChange={(e) => setLine(i, "description", e.target.value)} className="field" />
                        </td>
                        <td className="py-1 pr-2">
                          <input type="number" value={l.quantity} onChange={(e) => setLine(i, "quantity", e.target.value)} className="field" />
                        </td>
                        <td className="py-1">
                          <input type="number" value={l.unit_price} onChange={(e) => setLine(i, "unit_price", e.target.value)} className="field" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="flex items-end gap-2">
                  <label className="flex flex-col gap-1">
                    <span className="font-medium text-slate-800">Invoice total (incl. tax)</span>
                    <input type="number" value={total} onChange={(e) => setTotal(e.target.value)} className="field w-44" />
                  </label>
                  <Button icon={<Play className="size-3.5" />} loading={running} onClick={simulate} disabled={!total}>
                    Check invoice
                  </Button>
                </div>
                {error && <InlineError message={error} />}
                {result && (
                  <div className="rounded-md border border-surface-border bg-surface-subtle p-3">
                    <StatusDot tone={TONE[result.status]}>
                      <span className="font-medium text-slate-900">{VERDICT[result.status]}</span>
                    </StatusDot>
                    {result.issues.length > 0 && (
                      <ul className="mt-2 list-disc pl-5 text-slate-700">
                        {result.issues.map((i) => <li key={i}>{i}</li>)}
                      </ul>
                    )}
                    {result.remaining_after != null && (result.status === "matched" || result.status === "partial") && (
                      <p className="mt-2 text-slate-600">Left to invoice afterwards: {formatCurrency(result.remaining_after)}</p>
                    )}
                  </div>
                )}
              </>
            )}
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Recent invoice matches" />
          {!recent || recent.length === 0 ? (
            <CardBody className="text-13 text-slate-500">No invoices through the ledger yet.</CardBody>
          ) : (
            <ul className="divide-y divide-surface-border text-13">
              {recent.map((m) => (
                <li key={m.document_id} className="px-4 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <Link to={`/app/documents/${m.document_id}`} className="truncate font-medium text-brand-700 hover:underline">
                      {m.invoice_number ?? m.document_id.slice(0, 8)}
                    </Link>
                    <StatusDot tone={TONE[m.status]}>{m.status.replace("_", " ")}</StatusDot>
                  </div>
                  <p className="truncate text-xs text-slate-500">
                    {m.vendor_name ?? "—"} · {m.amount != null ? formatCurrency(m.amount) : "—"} · {formatRelativeTime(m.created_at)}
                  </p>
                  {m.issues[0] && (
                    <p className={`truncate text-xs ${m.status === "matched" || m.status === "partial" ? "text-slate-500" : "text-danger-600"}`}>
                      {m.issues[0]}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
