import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { licensesApi } from "@/api/licenses";
import { Badge } from "@/components/ui/Badge";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { formatCurrency, formatRelativeTime } from "@/lib/format";

export function LicenseIntelligenceCard() {
  const { data: summary, loading, error } = useApi(() => licensesApi.anomalySummary(), []);

  if (loading) {
    return (
      <Card>
        <CardBody className="animate-pulse p-6">
          <div className="h-6 w-48 rounded bg-slate-200" />
          <div className="mt-4 h-16 w-full rounded bg-slate-100" />
        </CardBody>
      </Card>
    );
  }

  if (error || !summary) return null;

  const isStale =
    !summary.last_scoring_run ||
    Date.now() - new Date(summary.last_scoring_run).getTime() > 25 * 3600 * 1000;

  return (
    <Card>
      <CardHeader
        title="License usage"
        action={<Link to="/app/licenses" className="text-13 font-medium text-accent hover:underline">View all licenses</Link>}
      />
      <CardBody className="flex flex-col gap-4">
        <LedgerStrip cols={4} label="Licences by usage">
          <MetricCard label="Anomalous" value={summary.anomalous} tone="danger" to="/app/licenses?status=anomalous" />
          <MetricCard label="Watch" value={summary.watch} tone="warning" to="/app/licenses?status=watch" />
          <MetricCard label="Normal" value={summary.normal} tone="neutral" to="/app/licenses?status=normal" />
          <MetricCard label="Insufficient history" value={summary.insufficient_history} tone="neutral" to="/app/licenses?status=insufficient_history" />
        </LedgerStrip>

        {/* Savings are good news: ink on the page, never alarm red, and a
            plain sentence when there's nothing to reclaim. */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-13 text-ink-2">Potential annual savings</p>
            {summary.potential_annual_savings > 0 ? (
              <>
                <p className="mt-0.5 text-figure font-medium tabular text-ink">{formatCurrency(summary.potential_annual_savings)}</p>
                <p className="mt-0.5 text-13 text-ink-3">
                  From {summary.anomalous} severely underused SaaS licence{summary.anomalous === 1 ? "" : "s"}
                </p>
              </>
            ) : (
              <p className="mt-0.5 text-sm text-ink">No reclaimable seats right now.</p>
            )}
          </div>

          <div className="flex flex-col items-start gap-1.5 sm:items-end">
            {isStale ? (
              <Badge tone="warning" icon={<AlertTriangle className="size-3" aria-hidden="true" />}>
                Scoring may be stale
              </Badge>
            ) : (
              <span className="text-caption text-ink-3">Last scored {formatRelativeTime(summary.last_scoring_run)}</span>
            )}
          </div>
        </div>
      </CardBody>
    </Card>
  );
}
