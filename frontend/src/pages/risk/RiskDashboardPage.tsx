import { useMemo, useState } from "react";
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
import { Button } from "@/components/ui/Button";
import { ErrorState, InlineError, InlineInfo } from "@/components/ui/ErrorState";
import type { VendorSummary } from "@/types/api";
import { ApiError } from "@/api/client";

export function RiskDashboardPage() {
  usePageHeader("Risk Management");
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: vendors, loading, error, reload } = useApi(() => vendorsApi.list(200), []);
  const [driftResult, setDriftResult] = useState<Record<string, unknown> | null>(null);
  const [driftLoading, setDriftLoading] = useState(false);
  const [driftError, setDriftError] = useState<string | null>(null);

  const scored = useMemo(() => (vendors ?? []).filter((v) => v.risk_band), [vendors]);
  const distribution = useMemo(() => {
    const bands = { Low: 0, Medium: 0, High: 0 } as Record<string, number>;
    scored.forEach((v) => {
      if (v.risk_band && v.risk_band in bands) bands[v.risk_band] += 1;
    });
    return bands;
  }, [scored]);
  const total = scored.length || 1;

  const runDriftCheck = async () => {
    setDriftLoading(true);
    setDriftError(null);
    try {
      const res = await vendorsApi.driftCheck();
      setDriftResult(res.data);
    } catch (e) {
      setDriftError(e instanceof ApiError ? e.message : "Unable to run drift check.");
    } finally {
      setDriftLoading(false);
    }
  };

  const columns: Column<VendorSummary>[] = [
    { key: "name", header: "Vendor", render: (v) => <span className="font-medium text-slate-800">{v.name}</span> },
    { key: "score", header: "Risk Score", render: (v) => (v.risk_score != null ? v.risk_score.toFixed(2) : "—"), sortValue: (v) => v.risk_score ?? -1 },
    { key: "band", header: "Risk Band", render: (v) => <RiskBadge band={v.risk_band} /> },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-6">
      <LedgerStrip cols={3} label="Vendors by risk band">
        <MetricCard label="Low risk" value={distribution.Low} icon={ShieldCheck} tone="success" hint={`${Math.round((distribution.Low / total) * 100)}% of scored vendors`} />
        <MetricCard label="Medium risk" value={distribution.Medium} icon={ShieldQuestion} tone="warning" hint={`${Math.round((distribution.Medium / total) * 100)}% of scored vendors`} />
        <MetricCard label="High risk" value={distribution.High} icon={AlertTriangle} tone="danger" hint={`${Math.round((distribution.High / total) * 100)}% of scored vendors`} />
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
        <CardHeader title="Vendor Risk" subtitle="Click a vendor for contributing factors and assessment history" />
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

      {user?.role === "admin" && (
        <Card>
          <CardHeader title="Model Drift Monitoring" subtitle="Population Stability Index vs. the training-time score distribution — a monitoring signal only, never auto-retrains" />
          <CardBody className="flex flex-col gap-3">
            <Button variant="secondary" loading={driftLoading} onClick={runDriftCheck}>
              Run Drift Check
            </Button>
            {driftError && <InlineError message={driftError} />}
            {driftResult && (
              <pre className="overflow-x-auto rounded-lg bg-surface-subtle p-3 text-xs text-slate-700">{JSON.stringify(driftResult, null, 2)}</pre>
            )}
            <InlineInfo message="The vendor risk model is trained on documented synthetic data for this environment — treat scores as a demonstration of the scoring pipeline, not live external intelligence." />
          </CardBody>
        </Card>
      )}
    </div>
  );
}
