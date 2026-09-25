import { Link } from "react-router-dom";
import { ArrowRight, AlertTriangle, KeyRound } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { licensesApi } from "@/api/licenses";
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
    <Card className="border-brand-100 bg-gradient-to-br from-white to-brand-50/20 shadow-sm">
      <CardHeader
        title={
          <div className="flex items-center gap-2 text-brand-900">
            <KeyRound className="size-5 text-brand-600" />
            <span>License Intelligence</span>
          </div>
        }
        subtitle="Automated SSO usage anomaly tracking & seat reclamation potential"
      />
      <CardBody className="flex flex-col gap-5 pt-0">
        <div className="grid grid-cols-2 gap-4 rounded-xl border border-slate-100 bg-white p-4 shadow-xs sm:grid-cols-4">
          <div className="flex items-center gap-2.5">
            <span className="flex size-3 rounded-full bg-rose-500 ring-4 ring-rose-100" />
            <div>
              <p className="text-lg font-bold text-slate-900">{summary.anomalous}</p>
              <p className="text-xs font-medium text-slate-500">Anomalous</p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <span className="flex size-3 rounded-full bg-amber-500 ring-4 ring-amber-100" />
            <div>
              <p className="text-lg font-bold text-slate-900">{summary.watch}</p>
              <p className="text-xs font-medium text-slate-500">Watch</p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <span className="flex size-3 rounded-full bg-emerald-500 ring-4 ring-emerald-100" />
            <div>
              <p className="text-lg font-bold text-slate-900">{summary.normal}</p>
              <p className="text-xs font-medium text-slate-500">Normal</p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <span className="flex size-3 rounded-full bg-slate-400 ring-4 ring-slate-100" />
            <div>
              <p className="text-lg font-bold text-slate-900">{summary.insufficient_history}</p>
              <p className="text-xs font-medium text-slate-500">Insufficient</p>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-end justify-between gap-4 rounded-xl border border-rose-100 bg-rose-50/40 p-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-rose-700">
              Potential Annual Savings
            </p>
            <p className="mt-1 text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl">
              {formatCurrency(summary.potential_annual_savings)}
            </p>
            <p className="mt-0.5 text-xs text-rose-800">
              Identified across {summary.anomalous} severely underutilised SaaS licenses
            </p>
          </div>

          <div className="flex flex-col items-start sm:items-end gap-1.5">
            {isStale ? (
              <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                <AlertTriangle className="size-3" /> Scoring may be stale
              </span>
            ) : (
              <span className="text-xs text-slate-500">
                Last scored: {formatRelativeTime(summary.last_scoring_run)}
              </span>
            )}
            <Link
              to="/app/licenses"
              className="inline-flex items-center gap-1 text-sm font-semibold text-brand-600 hover:text-brand-800 hover:underline"
            >
              View all licenses <ArrowRight className="size-4" />
            </Link>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}
