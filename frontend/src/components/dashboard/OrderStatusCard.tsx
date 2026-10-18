import { useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { ordersApi } from "@/api/orders";
import { ApiError } from "@/api/client";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import { formatCurrency, formatRelativeTime } from "@/lib/format";
import type { OrderSummary } from "@/types/api";

const SEVERITY_DOT: Record<string, string> = {
  high: "bg-danger-500",
  medium: "bg-warning-500",
  low: "bg-slate-400",
};

/** Latest snapshot from the order monitor agent (approval-inventory-agent,
 * hourly): where every open order is stuck, and what changed since the
 * previous check. */
export function OrderStatusCard() {
  const { data, loading, error, reload } = useApi(() => ordersApi.latestSummary(), []);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [fresh, setFresh] = useState<OrderSummary | null>(null);
  const summary = fresh ?? data;

  const runNow = async () => {
    setRunning(true);
    setRunError(null);
    try {
      const res = await ordersApi.runNow();
      setFresh(res.data);
      reload();
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : "Check failed.");
    } finally {
      setRunning(false);
    }
  };

  const action = (
    <Button size="sm" variant="secondary" icon={<RefreshCw className="size-3.5" />} loading={running} onClick={runNow}>
      Check now
    </Button>
  );

  return (
    <Card>
      <CardHeader
        title="Order status"
        subtitle={
          summary
            ? `Checked ${formatRelativeTime(summary.generated_at)}`
            : undefined
        }
        action={action}
      />
      {loading && !summary ? (
        <CardBody>
          <Skeleton className="h-24" />
        </CardBody>
      ) : !summary ? (
        <CardBody className="text-13 text-slate-600">
          {error && !/no order summary/i.test(error) ? error : "No check has run yet."}
          {runError && <p className="mt-1 text-danger-600">{runError}</p>}
        </CardBody>
      ) : (
        <>
          <div className="grid grid-cols-2 divide-surface-border border-b border-surface-border sm:grid-cols-4 sm:divide-x">
            <Stat
              label="Awaiting approval"
              value={summary.counts.pending_approval}
              flag={summary.counts.approval_overdue}
              flagLabel="past SLA"
              to="/app/requests?scope=all&status=pending_approval"
            />
            <Stat label="Awaiting signature" value={summary.counts.awaiting_signature} to="/app/contracts?status=pending_signature" />
            <Stat
              label="Awaiting delivery"
              value={summary.counts.awaiting_delivery}
              flag={summary.counts.delivery_overdue}
              flagLabel="overdue"
              to="/app/requests?scope=all&status=ordered"
            />
            <Stat label="Backordered" value={summary.counts.backordered} to="/app/requests?scope=all&backordered=1" />
          </div>
          <CardBody className="flex flex-col gap-3">
            <p className="text-13 text-slate-600">
              Since the previous check: {summary.changes.new_requests} new, {summary.changes.approved} approved,{" "}
              {summary.changes.invoices_received} invoiced, {summary.changes.rejected} rejected.
              {summary.open_order_value != null && (
                <> Open order value {formatCurrency(summary.open_order_value)}.</>
              )}
            </p>
            {runError && <p className="text-13 text-danger-600">{runError}</p>}
            {summary.attention.length > 0 ? (
              <ul className="divide-y divide-surface-border rounded-md border border-surface-border">
                {summary.attention.slice(0, 6).map((a) => (
                  <li key={`${a.kind}-${a.request_id}`}>
                    <Link
                      to={`/app/requests/${a.request_id}`}
                      className="flex items-start gap-2.5 px-3 py-2 text-13 text-slate-700 hover:bg-surface-subtle"
                    >
                      <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", SEVERITY_DOT[a.severity])} aria-hidden="true" />
                      {a.message}
                    </Link>
                  </li>
                ))}
                {summary.attention.length > 6 && (
                  <li className="px-3 py-2 text-xs text-slate-500">+{summary.attention.length - 6} more</li>
                )}
              </ul>
            ) : (
              <p className="text-13 text-slate-500">No orders need follow-up.</p>
            )}
          </CardBody>
        </>
      )}
    </Card>
  );
}

function Stat({ label, value, flag, flagLabel, to }: { label: string; value: number; flag?: number; flagLabel?: string; to: string }) {
  return (
    <Link to={to} className="block px-4 py-3 transition-colors duration-1 hover:bg-sheet-sunk focus-visible:ring-inset focus-visible:ring-offset-0">
      <span className="block text-xs text-slate-600">{label}</span>
      <span className="mt-0.5 flex items-baseline gap-2">
        <span className="text-xl font-semibold tabular text-slate-900">{value}</span>
        {!!flag && (
          <span className="text-xs font-medium text-danger-600">
            {flag} {flagLabel}
          </span>
        )}
      </span>
    </Link>
  );
}
