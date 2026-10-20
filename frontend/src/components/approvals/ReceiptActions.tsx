import { useState } from "react";
import { PackageCheck } from "lucide-react";
import { ApiError } from "@/api/client";
import { requestsApi } from "@/api/requests";
import { useApi } from "@/hooks/useApi";
import { Button } from "@/components/ui/Button";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { formatDateTime } from "@/lib/format";
import type { PurchaseRequest } from "@/types/api";

const field = "h-9 w-full rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink focus:border-accent";

/** Deliveries (Phase 3d): record what arrived per line, with asset tags for
 * hardware, or receive everything that's left at once. Part of the approval
 * agent's request actions (ApprovalActions shows it once ordered). */
export function ReceiptActions({ request, onDecided }: { request: PurchaseRequest; onDecided?: (updated: PurchaseRequest) => void }) {
  const { data, reload } = useApi(() => requestsApi.receipts(request.id), [request.id, request.status]);
  const [qty, setQty] = useState<Record<number, string>>({});
  const [tags, setTags] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<"part" | "all" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const lines = (data?.lines ?? []).filter((l) => l.ordered - l.received > 0);

  const run = async (kind: "part" | "all") => {
    setBusy(kind);
    setError(null);
    setDone(null);
    try {
      if (kind === "all") {
        const res = await requestsApi.receive(request.id);
        onDecided?.(res.data);
      } else {
        const body = lines.map((l) => ({
          line_no: l.line_no, quantity: Math.floor(Number(qty[l.line_no] || 0)),
          asset_tags: (tags[l.line_no] ?? "").split(/[,\n]/).map((t) => t.trim()).filter(Boolean),
        })).filter((l) => l.quantity > 0);
        if (!body.length) {
          setError("Enter how many arrived for at least one line.");
          return;
        }
        const res = await requestsApi.recordReceipt(request.id, body);
        setQty({});
        setTags({});
        setDone(res.data.outcome === "partially_received" ? "Delivery recorded; the rest is still to come." : "Everything has arrived.");
        reload();
        onDecided?.(res.data.request);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to record the delivery.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-ink-2">
        {request.status === "partially_received" ? "Partly received: the rest of the order is still with the vendor." : "Ordered: the contract is signed and the order is with the vendor."}
      </p>
      {lines.length > 0 && (
        <table className="w-full text-13">
          <thead><tr className="border-b border-rule text-left text-ink-3">
            <th className="py-1.5 pr-2 font-medium">Line</th><th className="py-1.5 pr-2 text-right font-medium">Received</th>
            <th className="py-1.5 pr-2 font-medium">Arrived now</th><th className="py-1.5 font-medium">Asset tags / serials</th>
          </tr></thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.line_no} className="border-b border-rule last:border-0">
                <td className="py-1.5 pr-2 text-ink">{l.description}</td>
                <td className="py-1.5 pr-2 text-right tabular text-ink-2">{l.received} of {l.ordered}</td>
                <td className="w-24 py-1.5 pr-2"><input aria-label={`Arrived now: ${l.description}`} className={field} type="number" min={0} max={l.ordered - l.received}
                  value={qty[l.line_no] ?? ""} onChange={(e) => setQty({ ...qty, [l.line_no]: e.target.value })} /></td>
                <td className="py-1.5"><input aria-label={`Asset tags: ${l.description}`} className={field} value={tags[l.line_no] ?? ""} placeholder="LT-0101, LT-0102"
                  onChange={(e) => setTags({ ...tags, [l.line_no]: e.target.value })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="flex flex-wrap gap-2">
        {lines.length > 0 && <Button variant="secondary" loading={busy === "part"} onClick={() => run("part")}>Record delivery</Button>}
        <Button icon={<PackageCheck className="size-4" />} loading={busy === "all"} onClick={() => run("all")}>
          {request.status === "partially_received" ? "Everything else arrived" : "Mark as received"}
        </Button>
      </div>
      {error && <InlineError message={error} />}
      {done && <InlineSuccess message={done} />}
      {(data?.receipts.length ?? 0) > 0 && (
        <ul className="flex flex-col text-13 text-ink-3">
          {data!.receipts.map((r) => (
            <li key={r.id}>{formatDateTime(r.received_at)}: {r.lines.map((l) => `${l.quantity} on line ${l.line_no + 1}`).join(", ")}
              {r.lines.some((l) => l.asset_tags.length) && ` (${r.lines.flatMap((l) => l.asset_tags).join(", ")})`}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
