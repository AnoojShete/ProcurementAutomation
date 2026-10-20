import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, ShieldCheck, ShieldQuestion } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { RiskBadge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { ScorecardMonitoringCard } from "@/components/risk/ScorecardMonitoringCard";
import type { VendorSummary } from "@/types/api";

export function RiskDashboardPage() {
  usePageHeader("Risk Management");
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: vendors, loading, error, reload } = useApi(() => vendorsApi.list(200), []);

  const scored = useMemo(() => (vendors ?? []).filter((v) => v.risk_band), [vendors]);
  const distribution = useMemo(() => {
    const bands = { Low: 0, Medium: 0, High: 0 } as Record<string, number>;
    scored.forEach((v) => {
      if (v.risk_band && v.risk_band in bands) bands[v.risk_band] += 1;
    });
    return bands;
  }, [scored]);
  const total = scored.length || 1;

  const columns: Column<VendorSummary>[] = [
    { key: "name", header: "Vendor", render: (v) => <span className="font-medium text-slate-800">{v.name}</span> },
    { key: "score", header: "Risk Score", render: (v) => (v.risk_score != null ? v.risk_score.toFixed(2) : "—"), sortValue: (v) => v.risk_score ?? -1 },
    { key: "band", header: "Risk Band", render: (v) => <RiskBadge band={v.risk_band} /> },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-6">
      <LedgerStrip cols={3} label="Vendors by risk band">
        <MetricCard label="Low risk" value={distribution.Low} icon={ShieldCheck} tone="success" hint={`${Math.round((distribution.Low / total) * 100)}% of scored vendors`} to="/app/vendors?risk=Low" />
        <MetricCard label="Medium risk" value={distribution.Medium} icon={ShieldQuestion} tone="warning" hint={`${Math.round((distribution.Medium / total) * 100)}% of scored vendors`} to="/app/vendors?risk=Medium" />
        <MetricCard label="High risk" value={distribution.High} icon={AlertTriangle} tone="danger" hint={`${Math.round((distribution.High / total) * 100)}% of scored vendors`} to="/app/vendors?risk=High" />
      </LedgerStrip>

      <Card>
        <CardHeader title="Risk Distribution" />
        <CardBody>
          <div className="flex h-3 w-full overflow-hidden rounded-sm bg-sheet-sunk" role="img" aria-label={`Low ${distribution.Low}, medium ${distribution.Medium}, high ${distribution.High}`}>
            {(["Low", "Medium", "High"] as const).map((band) => (
              <div
                key={band}
                className={band === "Low" ? "bg-success-500" : band === "Medium" ? "bg-warning-500" : "bg-danger-500"}
                style={{ width: `${(distribution[band] / total) * 100}%` }}
                title={`${band}: ${distribution[band]}`}
              />
            ))}
          </div>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-13 text-ink-2">
            {(["Low", "Medium", "High"] as const).map((band) => (
              <span key={band} className="inline-flex items-center gap-1.5">
                <span className={`size-2.5 rounded-sm ${band === "Low" ? "bg-success-500" : band === "Medium" ? "bg-warning-500" : "bg-danger-500"}`} aria-hidden="true" />
                {band} <span className="tabular font-medium text-ink">{distribution[band]}</span>
              </span>
            ))}
          </div>
          <p className="mt-2 text-caption text-ink-3">{scored.length} of {vendors?.length ?? 0} vendors have been risk-scored.</p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Vendor Risk" />
        <CardBody>
          <DataTable
            columns={columns}
            rows={vendors ?? []}
            rowKey={(v) => v.id}
            loading={loading}
            onRowClick={(v) => navigate(`/app/vendors/${v.id}`)}
            emptyTitle="No vendors to assess yet"
          />
        </CardBody>
      </Card>

      <ScorecardMonitoringCard />
    </div>
  );
}
