import { useState, useEffect } from "react";
import {
  BarChart3,
  AlertTriangle,
  CheckCircle,
  HelpCircle,
  RefreshCw,
  Scale,
  Flame,
  Skull,
  Radio,
} from "lucide-react";
import { rulesetsApi } from "@/api/vendors";
import type { MonitoringReport } from "@/types/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/ErrorState";
import { formatDateTime } from "@/lib/format";

export function ScorecardMonitoringCard() {
  const [report, setReport] = useState<MonitoringReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lookbackDays, setLookbackDays] = useState(30);

  const fetchReport = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await rulesetsApi.monitoring(lookbackDays);
      setReport(res.data);
    } catch (err: any) {
      setError(err?.message || "Failed to load scorecard monitoring telemetry");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReport();
  }, [lookbackDays]);

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Radio className="size-4 text-brand-600" />
            Vendor Risk Scorecard Telemetry & Calibration
          </span>
        }
        subtitle="Weekly descriptive monitoring replaces PSI drift check: tracks rule sensitivity, missing data rates, and incident calibration"
        action={
          <div className="flex items-center gap-2">
            <select
              className="text-xs border border-rule rounded px-2 py-1 bg-sheet text-ink"
              value={lookbackDays}
              onChange={(e) => setLookbackDays(Number(e.target.value))}
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
            <Button variant="secondary" size="sm" loading={loading} onClick={fetchReport}>
              <RefreshCw className="size-3 mr-1" /> Refresh
            </Button>
          </div>
        }
      />
      <CardBody className="space-y-6">
        {error && <InlineError message={error} />}

        {loading && !report && (
          <div className="flex h-32 items-center justify-center">
            <div className="size-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
          </div>
        )}

        {report && (
          <>
            {/* Top Metric Strip: Rating Distribution */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="p-3 bg-emerald-50/60 border border-emerald-200 rounded-lg">
                <span className="text-11 font-medium text-emerald-800">Low Risk Vendors</span>
                <p className="text-lg font-bold text-emerald-950 mt-0.5">
                  {report.rating_distribution?.low || 0}{" "}
                  <span className="text-xs font-normal">({report.rating_distribution?.low_pct || 0}%)</span>
                </p>
              </div>
              <div className="p-3 bg-amber-50/60 border border-amber-200 rounded-lg">
                <span className="text-11 font-medium text-amber-800">Medium Risk Vendors</span>
                <p className="text-lg font-bold text-amber-950 mt-0.5">
                  {report.rating_distribution?.medium || 0}{" "}
                  <span className="text-xs font-normal">({report.rating_distribution?.medium_pct || 0}%)</span>
                </p>
              </div>
              <div className="p-3 bg-rose-50/60 border border-rose-200 rounded-lg">
                <span className="text-11 font-medium text-rose-800">High Risk Vendors</span>
                <p className="text-lg font-bold text-rose-950 mt-0.5">
                  {report.rating_distribution?.high || 0}{" "}
                  <span className="text-xs font-normal">({report.rating_distribution?.high_pct || 0}%)</span>
                </p>
              </div>
              <div className="p-3 bg-slate-100 border border-slate-300 rounded-lg">
                <span className="text-11 font-medium text-slate-700">Provisional Ratings</span>
                <p className="text-lg font-bold text-slate-900 mt-0.5">
                  {report.rating_distribution?.provisional || 0}{" "}
                  <span className="text-xs font-normal">({report.rating_distribution?.provisional_pct || 0}%)</span>
                </p>
              </div>
            </div>

            {/* Rule Frequencies & Sensitivity */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-semibold text-ink">Rule Trigger Frequency & Sensitivity</h4>
                <div className="flex gap-2 text-11 text-ink-3">
                  <span className="inline-flex items-center gap-1">
                    <Skull className="size-3 text-slate-400" /> Dead Rule (0 fires)
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Flame className="size-3 text-amber-600" /> Overly Sensitive (&gt;50%)
                  </span>
                </div>
              </div>
              <div className="border border-rule rounded-lg overflow-x-auto max-h-60 overflow-y-auto">
                <table className="min-w-full text-xs text-left divide-y divide-rule">
                  <thead className="bg-sheet-subtle text-ink-2 font-medium sticky top-0">
                    <tr>
                      <th className="px-3 py-2">Rule ID</th>
                      <th className="px-3 py-2">Signal</th>
                      <th className="px-3 py-2">Description</th>
                      <th className="px-3 py-2">Times Fired</th>
                      <th className="px-3 py-2">Trigger Rate</th>
                      <th className="px-3 py-2">Health Flag</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rule">
                    {(report.rule_frequencies || []).map((r) => (
                      <tr key={r.rule_id} className="hover:bg-sheet-subtle/50">
                        <td className="px-3 py-1.5 font-mono font-bold text-ink">{r.rule_id}</td>
                        <td className="px-3 py-1.5 text-ink-2">{r.signal_key}</td>
                        <td className="px-3 py-1.5 text-ink max-w-xs truncate">{r.description}</td>
                        <td className="px-3 py-1.5 font-semibold text-ink tabular-nums">{r.times_fired}</td>
                        <td className="px-3 py-1.5 text-ink-2 tabular-nums">{r.fire_pct}%</td>
                        <td className="px-3 py-1.5">
                          {r.is_dead ? (
                            <Badge tone="neutral">Dead (0 fires)</Badge>
                          ) : r.is_overly_sensitive ? (
                            <Badge tone="warning">Overly Sensitive (&gt;50%)</Badge>
                          ) : (
                            <span className="text-emerald-600 text-11 font-medium">Normal</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {(!report.rule_frequencies || report.rule_frequencies.length === 0) && (
                      <tr>
                        <td colSpan={6} className="px-3 py-4 text-center text-ink-3">No rule triggers in lookback window.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Grid: Missing Data Rates & Disputes */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Missing Data Rates */}
              <div className="border border-rule rounded-lg p-3 space-y-2">
                <h4 className="text-xs font-semibold text-ink">Missing Data Rate by Signal</h4>
                <p className="text-11 text-ink-3">Signals with missing observations exceed 20% tolerance</p>
                <div className="space-y-1.5 max-h-48 overflow-y-auto">
                  {(report.missing_signal_rates || []).map((m) => (
                    <div key={m.signal_key} className="flex items-center justify-between text-xs p-1.5 rounded bg-sheet-subtle">
                      <span className="font-medium text-ink">{m.signal_key}</span>
                      <div className="flex items-center gap-2">
                        <span className="tabular-nums text-ink-2">{m.missing_rate_pct}% missing ({m.not_assessed_count})</span>
                        {m.exceeds_threshold && <Badge tone="danger">&gt;20% Tolerance</Badge>}
                      </div>
                    </div>
                  ))}
                  {(!report.missing_signal_rates || report.missing_signal_rates.length === 0) && (
                    <p className="text-11 text-ink-3 text-center py-2">No missing signals recorded.</p>
                  )}
                </div>
              </div>

              {/* Disputes & Overrides */}
              <div className="border border-rule rounded-lg p-3 space-y-3">
                <h4 className="text-xs font-semibold text-ink">Dispute Governance & Hard Overrides</h4>
                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="p-2 bg-sheet-subtle rounded border border-rule">
                    <span className="text-caption text-ink-3">Raised</span>
                    <p className="font-bold text-ink mt-0.5">{report.dispute_stats?.raised_count || 0}</p>
                  </div>
                  <div className="p-2 bg-emerald-50 rounded border border-emerald-200">
                    <span className="text-caption text-emerald-800">Upheld</span>
                    <p className="font-bold text-emerald-950 mt-0.5">{report.dispute_stats?.upheld_count || 0}</p>
                  </div>
                  <div className="p-2 bg-rose-50 rounded border border-rose-200">
                    <span className="text-caption text-rose-800">Rejected</span>
                    <p className="font-bold text-rose-950 mt-0.5">{report.dispute_stats?.rejected_count || 0}</p>
                  </div>
                </div>

                <div>
                  <span className="text-11 font-medium text-ink-2">Active Override Rule Triggers:</span>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {Object.entries(report.override_frequencies || {}).map(([rId, count]) => (
                      <Badge key={rId} tone="danger">{rId}: {count} fired</Badge>
                    ))}
                    {Object.keys(report.override_frequencies || {}).length === 0 && (
                      <span className="text-11 text-ink-3 italic">No override rules fired in window.</span>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Calibration Candidates */}
            {report.calibration_candidates && report.calibration_candidates.length > 0 && (
              <div className="border border-amber-300 bg-amber-50/50 rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="size-4 text-amber-700" />
                  <h4 className="text-xs font-semibold text-amber-950">Incident Calibration Candidates</h4>
                </div>
                <p className="text-11 text-amber-900">
                  Vendors with logged incidents within 90 days of an assessment. Compares their assigned risk band with actual performance outcomes for ruleset tuning.
                </p>
                <div className="overflow-x-auto border border-amber-200 rounded bg-sheet">
                  <table className="min-w-full text-xs text-left divide-y divide-amber-100">
                    <thead className="bg-amber-50/80 text-amber-900 font-medium">
                      <tr>
                        <th className="px-3 py-1.5">Vendor ID</th>
                        <th className="px-3 py-1.5">Incident Date</th>
                        <th className="px-3 py-1.5">Score at Incident</th>
                        <th className="px-3 py-1.5">Band at Incident</th>
                        <th className="px-3 py-1.5">Notes</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-amber-100">
                      {report.calibration_candidates.map((c, i) => (
                        <tr key={i}>
                          <td className="px-3 py-1.5 font-mono text-ink-2">{c.vendor_id?.substring(0, 8)}...</td>
                          <td className="px-3 py-1.5 text-ink-2">{c.incident_date}</td>
                          <td className="px-3 py-1.5 font-semibold tabular-nums">{c.score_at_incident} pts</td>
                          <td className="px-3 py-1.5">
                            <Badge tone={c.band_at_incident === "High" ? "danger" : c.band_at_incident === "Medium" ? "warning" : "success"}>
                              {c.band_at_incident}
                            </Badge>
                          </td>
                          <td className="px-3 py-1.5 text-ink-2 max-w-xs truncate">{c.notes || "Reported incident"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}
