import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  ArrowDownRight,
  Clock,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  ShieldCheck,
  Calendar,
  Users,
  DollarSign,
  Building,
} from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useAuth } from "@/hooks/useAuth";
import { licensesApi } from "@/api/licenses";
import { requestsApi } from "@/api/requests";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { UsageTrendChart } from "@/components/charts/UsageTrendChart";
import { formatCurrency, formatPercent } from "@/lib/format";
import type {
  LicenseItem,
  UsageHistoryEntry,
  ReclaimHistoryEntry,
  AnomalyStatus,
} from "@/types/api";

const FEATURE_LABELS: Record<string, string> = {
  active_seats_30d: "Seats active in the last 30 days",
  active_seats_7d: "Seats active in the last 7 days",
  active_seats_90d: "Seats active in the last 90 days",
  days_since_last_login: "Days since last user login",
  dod_rate_change: "Day-over-day change in active logins",
  wow_rate_change: "Week-over-week login velocity",
  utilisation_ratio: "Seat utilisation against licensed total",
  variance_daily_logins: "Daily login consistency and volatility",
  weekend_ratio: "Weekend vs weekday usage distribution",
};

export function LicenseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [license, setLicense] = useState<LicenseItem | null>(null);
  const [history, setHistory] = useState<UsageHistoryEntry[]>([]);
  const [reclaimHistory, setReclaimHistory] = useState<ReclaimHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Reclaim action state
  const [reclaimSuccessMsg, setReclaimSuccessMsg] = useState<string | null>(null);
  const [reclaimLoading, setReclaimLoading] = useState(false);

  // Review action state
  const [reviewSuccessMsg, setReviewSuccessMsg] = useState<string | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);

  usePageHeader(license ? `${license.app_name} License` : "License Detail", "Licenses");

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      licensesApi.list().then((res) => res.data?.licenses?.find((l: LicenseItem) => l.id === id) || null),
      licensesApi.usageHistory(id).then((r) => r.data).catch(() => []),
      licensesApi.reclaimHistory(id).then((r) => r.data).catch(() => []),
    ])
      .then(([lic, hist, recHist]) => {
        if (!lic) {
          setError("License not found");
        } else {
          setLicense(lic);
          setHistory(hist);
          setReclaimHistory(recHist);
        }
      })
      .catch((err) => setError(err.message || "Failed to load license details"))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="size-6 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
      </div>
    );
  }

  if (error || !license) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700">
        <p className="font-medium">{error || "License not found"}</p>
        <button
          onClick={() => navigate("/app/licenses")}
          className="mt-3 text-sm font-semibold underline"
        >
          Back to licenses
        </button>
      </div>
    );
  }

  const isAnomalous = license.anomaly_status === "anomalous";
  const isCooldown =
    license.reclaim_cooldown_until &&
    new Date(license.reclaim_cooldown_until) > new Date();

  const statusBadge = (status: AnomalyStatus, score: number | null) => {
    if (score === null || status === "insufficient_history") {
      return <Badge tone="neutral">Insufficient data</Badge>;
    }
    if (status === "anomalous") return <Badge tone="danger">Anomalous</Badge>;
    if (status === "watch") return <Badge tone="warning">Watch</Badge>;
    return <Badge tone="success">Normal</Badge>;
  };

  const handleInitiateReclaim = async () => {
    if (!license || reclaimLoading || isCooldown) return;
    setReclaimLoading(true);
    try {
      const unusedSeats = license.total_seats - (license.assigned_seats || 0);
      const savings = (license.cost_per_seat || 0) * unusedSeats;

      await requestsApi.create({
        request_type: "reclaim",
        requested_by: user?.email || "admin@example.com",
        department: "IT",
        vendor_id: license.vendor_id,
        amount: savings,
        currency: license.currency || "INR",
        items: [
          {
            license_id: license.id,
            app_name: license.app_name,
            unused_seats: unusedSeats,
            utilisation_score: license.utilisation_score,
            anomaly_score: license.anomaly_score,
          },
        ],
        comments: `Manual reclaim initiated from License Intelligence. Unused seats: ${unusedSeats}.`,
      });

      setReclaimSuccessMsg(
        "Reclaim request opened — the license holder will be notified within their 7-day grace period",
      );

      // Refresh reclaim history
      licensesApi.reclaimHistory(license.id).then((r) => setReclaimHistory(r.data)).catch(() => {});
    } catch (err: any) {
      alert(err.message || "Failed to initiate reclaim request");
    } finally {
      setReclaimLoading(false);
    }
  };

  const handleMarkReviewed = async () => {
    if (!license || reviewLoading) return;
    setReviewLoading(true);
    try {
      const res = await licensesApi.markReviewed(license.id);
      setReviewSuccessMsg("License marked as reviewed. 30-day review cooldown applied.");
      setLicense({
        ...license,
        reclaim_cooldown_until: res.data.reclaim_cooldown_until,
      });

      // Refresh reclaim history
      licensesApi.reclaimHistory(license.id).then((r) => setReclaimHistory(r.data)).catch(() => {});
    } catch (err: any) {
      alert(err.message || "Failed to mark license as reviewed");
    } finally {
      setReviewLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Top Header Card */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <button
          onClick={() => navigate("/app/licenses")}
          className="flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-800"
        >
          <ArrowLeft className="size-4" /> Back to Licenses
        </button>
        <div className="flex items-center gap-2">
          {statusBadge(license.anomaly_status, license.anomaly_score)}
          {isCooldown && (
            <Badge tone="warning">
              Cooldown until {new Date(license.reclaim_cooldown_until!).toLocaleDateString()}
            </Badge>
          )}
        </div>
      </div>

      {/* Overview Metric Cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Application</span>
            <Building className="size-4 text-brand-600" />
          </div>
          <p className="mt-1.5 truncate text-base font-bold text-slate-800">{license.app_name}</p>
          <p className="text-xs text-slate-500">{license.vendor_name || "Enterprise Vendor"}</p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Seat Utilisation</span>
            <Users className="size-4 text-brand-600" />
          </div>
          <p className="mt-1.5 text-base font-bold text-slate-800">
            {formatPercent(license.utilisation_score)}
          </p>
          <p className="text-xs text-slate-500">
            {license.active_seats_30d} of {license.total_seats} active in 30d
          </p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Last User Login</span>
            <Clock className="size-4 text-amber-600" />
          </div>
          <p className="mt-1.5 text-base font-bold text-slate-800">
            {license.days_since_last_login} days ago
          </p>
          <p className="text-xs text-slate-500">Across all licensed users</p>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Annual Seat Cost</span>
            <DollarSign className="size-4 text-emerald-600" />
          </div>
          <p className="mt-1.5 text-base font-bold text-slate-800">
            {formatCurrency(license.cost_per_seat)}
          </p>
          <p className="text-xs text-slate-500">Per seat recurring rate</p>
        </div>
      </div>

      {/* Usage Trend Chart */}
      <Card>
        <CardHeader
          title="Usage Trend Analysis (Last 90 Days)"
          subtitle="Daily active users logging into this SaaS application via SSO"
        />
        <CardBody>
          <UsageTrendChart
            data={history}
            thresholdSeats={Math.ceil(license.total_seats * 0.3)}
            totalSeats={license.total_seats}
          />
        </CardBody>
      </Card>

      {/* SHAP Explanation Section: "Why was this flagged?" */}
      <Card>
        <CardHeader
          title="Why was this flagged?"
          subtitle="Top contributing behavioral signals evaluated by the Isolation Forest model"
        />
        <CardBody>
          {license.anomaly_score === null ? (
            <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
              <Calendar className="size-5 shrink-0 text-slate-400" />
              <div>
                <p className="font-medium text-slate-700">Insufficient Login History</p>
                <p className="text-xs text-slate-500">
                  This license has fewer than the required active history days to determine an
                  anomaly profile reliably.
                </p>
              </div>
            </div>
          ) : !license.top_factors || license.top_factors.length === 0 ? (
            <p className="text-sm text-slate-500">No anomaly factors flagged for this license.</p>
          ) : (
            <div className="space-y-3">
              {license.top_factors.slice(0, 3).map((factor, idx) => {
                const label = FEATURE_LABELS[factor.feature] || factor.feature;
                const isIncreasingRisk = factor.direction === "increasing_risk" || factor.contribution > 0;
                return (
                  <div
                    key={idx}
                    className={`flex items-center justify-between rounded-lg border p-3.5 text-sm ${
                      isIncreasingRisk
                        ? "border-rose-100 bg-rose-50/50 text-slate-800"
                        : "border-emerald-100 bg-emerald-50/50 text-slate-800"
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex size-7 shrink-0 items-center justify-center rounded-full ${
                          isIncreasingRisk ? "bg-rose-100 text-rose-600" : "bg-emerald-100 text-emerald-600"
                        }`}
                      >
                        {isIncreasingRisk ? (
                          <ArrowUpRight className="size-4" />
                        ) : (
                          <ArrowDownRight className="size-4" />
                        )}
                      </div>
                      <div>
                        <span className="font-semibold text-slate-800">{label}</span>
                        <p className="text-xs text-slate-500">
                          {isIncreasingRisk
                            ? "Significant decline or irregular drop pushing license toward anomaly risk"
                            : "Stable login activity keeping license within normal operational bounds"}
                        </p>
                      </div>
                    </div>
                    <span
                      className={`text-xs font-semibold ${
                        isIncreasingRisk ? "text-rose-600" : "text-emerald-600"
                      }`}
                    >
                      {isIncreasingRisk ? "↑ Increases Risk" : "↓ Decreases Risk"}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Reclaim History Timeline */}
      <Card>
        <CardHeader
          title="Reclaim & Review History"
          subtitle="Audit log of previous reclaim requests and administrative reviews for this license"
        />
        <CardBody>
          {reclaimHistory.length === 0 ? (
            <div className="py-6 text-center text-sm text-slate-400">
              No previous reclaim or review actions taken on this license.
            </div>
          ) : (
            <div className="relative border-l-2 border-slate-200 pl-4 space-y-4">
              {reclaimHistory.map((item, idx) => (
                <div key={idx} className="relative flex flex-col gap-1 text-sm">
                  <div className="absolute -left-[21px] top-1 size-2.5 rounded-full border-2 border-white bg-brand-600" />
                  <div className="flex items-center gap-2">
                    <span className="font-semibold capitalize text-slate-800">
                      {item.event_type.replace(/_/g, " ")}
                    </span>
                    <span className="text-xs text-slate-400">
                      {new Date(item.event_at).toLocaleString()}
                    </span>
                  </div>
                  <p className="text-xs text-slate-600">
                    By <span className="font-medium">{item.by_user || "System"}</span>
                    {item.cooldown_set_until && (
                      <span className="ml-1 text-amber-600">
                        (Cooldown active until{" "}
                        {new Date(item.cooldown_set_until).toLocaleDateString()})
                      </span>
                    )}
                  </p>
                  {item.notes && <p className="text-xs italic text-slate-500">{item.notes}</p>}
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Action Buttons & Feedback */}
      <Card>
        <CardBody className="flex flex-col gap-4">
          {reclaimSuccessMsg && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3.5 text-sm font-medium text-emerald-800">
              <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />
              {reclaimSuccessMsg}
            </div>
          )}
          {reviewSuccessMsg && (
            <div className="flex items-center gap-2 rounded-lg border border-brand-200 bg-brand-50 p-3.5 text-sm font-medium text-brand-800">
              <CheckCircle2 className="size-4 shrink-0 text-brand-600" />
              {reviewSuccessMsg}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-slate-800">Available Actions</p>
              <p className="text-xs text-slate-500">
                Initiate automated reclaim flow or mark as reviewed to set a temporary cooldown
              </p>
            </div>

            <div className="flex items-center gap-3">
              {/* Mark as Reviewed Button: visible on any non-normal license */}
              {license.anomaly_status !== "normal" && (
                <Button
                  variant="secondary"
                  loading={reviewLoading}
                  onClick={handleMarkReviewed}
                  icon={<ShieldCheck className="size-4" />}
                >
                  Mark as Reviewed
                </Button>
              )}

              {/* Initiate Reclaim Button: visible only on Anomalous */}
              {isAnomalous && (
                <div title={isCooldown ? `In cooldown until ${license.reclaim_cooldown_until}` : undefined}>
                  <Button
                    variant="destructive"
                    disabled={Boolean(isCooldown) || Boolean(reclaimSuccessMsg)}
                    loading={reclaimLoading}
                    onClick={handleInitiateReclaim}
                    icon={<RotateCcw className="size-4" />}
                  >
                    Initiate Reclaim
                  </Button>
                </div>
              )}
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
