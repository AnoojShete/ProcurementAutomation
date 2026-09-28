import { Link } from "react-router-dom";
import { useApi } from "@/hooks/useApi";
import { ledgerApi } from "@/api/controls";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge, StatusDot } from "@/components/ui/Badge";
import { formatCurrency, formatDateTime } from "@/lib/format";

const MATCH_TONE = { matched: "success", partial: "brand", variance: "danger", ambiguous: "warning", no_match: "neutral" } as const;

/** What has been invoiced against a purchase request, and what's left. */
export function InvoiceLedgerCard({ requestId, currency = "INR" }: { requestId: string; currency?: string }) {
  const { data: ledger, loading } = useApi(() => ledgerApi.forRequest(requestId), [requestId]);
  if (loading || !ledger) return null;
  const pct = ledger.amount > 0 ? Math.min(100, (ledger.invoiced_amount / ledger.amount) * 100) : 0;

  return (
    <Card>
      <CardHeader title="Invoice ledger" subtitle="Invoices booked against this request's lines" />
      <CardBody className="flex flex-col gap-3 text-13">
        <div>
          <div className="flex justify-between text-slate-600">
            <span>
              Invoiced <span className="font-medium text-slate-900 tabular">{formatCurrency(ledger.invoiced_amount, currency)}</span> of{" "}
              {formatCurrency(ledger.amount, currency)}
            </span>
            <span className="tabular">{formatCurrency(ledger.remaining_amount, currency)} left</span>
          </div>
          <div className="mt-1.5 h-1.5 rounded-full bg-surface-muted">
            <div className="h-1.5 rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
          </div>
        </div>
        {ledger.lines.length > 0 && (
          <table className="w-full text-13">
            <thead>
              <tr className="border-b border-surface-border text-left text-xs text-slate-500">
                <th className="py-1.5 font-medium">Line</th>
                <th className="py-1.5 text-right font-medium">Ordered</th>
                <th className="py-1.5 text-right font-medium">Invoiced</th>
                <th className="py-1.5 text-right font-medium">Unit price</th>
              </tr>
            </thead>
            <tbody>
              {ledger.lines.map((l) => (
                <tr key={l.line_no} className="border-b border-surface-border last:border-0">
                  <td className="py-1.5 text-slate-800">{l.description || `Line ${l.line_no + 1}`}</td>
                  <td className="py-1.5 text-right tabular">{l.quantity}</td>
                  <td className="py-1.5 text-right tabular">{l.invoiced_quantity}</td>
                  <td className="py-1.5 text-right tabular">{formatCurrency(l.unit_price, currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {ledger.invoices.length === 0 ? (
          <p className="text-slate-500">No invoices booked yet.</p>
        ) : (
          <ul className="divide-y divide-surface-border rounded-md border border-surface-border">
            {ledger.invoices.map((inv) => (
              <li key={inv.document_id} className="flex items-center justify-between gap-2 px-3 py-2">
                <Link to={`/app/documents/${inv.document_id}`} className="font-medium text-brand-700 hover:underline">
                  {inv.invoice_number ?? inv.document_id.slice(0, 8)}
                </Link>
                <span className="flex items-center gap-2">
                  {inv.payment_hold && <Badge tone="warning">Payment hold</Badge>}
                  <StatusDot tone={MATCH_TONE[inv.status]}>{inv.status.replace("_", " ")}</StatusDot>
                  <span className="tabular text-slate-600">{inv.amount != null ? formatCurrency(inv.amount, currency) : "—"}</span>
                  <span className="hidden text-xs text-slate-400 sm:inline">{formatDateTime(inv.created_at)}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
