import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  RotateCcw,
  Search,
  Filter,
  ArrowUpDown,
  Building,
  Clock,
  KeyRound,
  ShieldCheck,
  CheckCircle2,
} from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { licensesApi } from "@/api/licenses";
import { requestsApi } from "@/api/requests";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { formatCurrency, formatPercent } from "@/lib/format";
import type { LicenseItem, AnomalyStatus } from "@/types/api";

const STATUS_PRIORITY: Record<AnomalyStatus, number> = {
  anomalous: 3,
  watch: 2,
  normal: 1,
  insufficient_history: 0,
};

export function LicensesListPage() {
  usePageHeader("License Intelligence", "Licenses");
  const navigate = useNavigate();
  const { user } = useAuth();

  const { data: snapshot, loading, error, reload } = useApi(() => licensesApi.list(), []);
  const licenses = snapshot?.licenses ?? [];

  // Filter and search state
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [currentPage, setCurrentPage] = useState(1);

  const pageSize = 50;

  // Reclaim loading / success tracking per license id
  const [reclaimStates, setReclaimStates] = useState<Record<string, { loading?: boolean; done?: boolean }>>({});

  const handleReclaim = async (e: React.MouseEvent, lic: LicenseItem) => {
    e.stopPropagation();
    if (reclaimStates[lic.id]?.loading || reclaimStates[lic.id]?.done) return;

    setReclaimStates((prev) => ({ ...prev, [lic.id]: { loading: true } }));
    try {
      const unusedSeats = lic.total_seats - (lic.assigned_seats || 0);
      const savings = (lic.cost_per_seat || 0) * unusedSeats;

      await requestsApi.create({
        request_type: "reclaim",
        requested_by: user?.email || "admin@example.com",
        department: "IT",
        vendor_id: lic.vendor_id,
        amount: savings,
        currency: lic.currency || "INR",
        items: [
          {
            license_id: lic.id,
            app_name: lic.app_name,
            unused_seats: unusedSeats,
            utilisation_score: lic.utilisation_score,
            anomaly_score: lic.anomaly_score,
          },
        ],
        comments: `Reclaim initiated from License Intelligence. Unused seats: ${unusedSeats}.`,
      });

      setReclaimStates((prev) => ({ ...prev, [lic.id]: { loading: false, done: true } }));
    } catch (err: any) {
      alert(err.message || "Failed to initiate reclaim");
      setReclaimStates((prev) => ({ ...prev, [lic.id]: { loading: false } }));
    }
  };

  const filteredLicenses = useMemo(() => {
    if (!licenses) return [];

    let list = [...licenses];

    // Filter by search (app name or vendor)
    if (searchTerm.trim()) {
      const term = searchTerm.toLowerCase();
      list = list.filter(
        (l) =>
          l.app_name.toLowerCase().includes(term) ||
          (l.vendor_name && l.vendor_name.toLowerCase().includes(term)),
      );
    }

    // Filter by status badge
    if (selectedStatus !== "all") {
      list = list.filter((l) => {
        if (selectedStatus === "insufficient_history") {
          return l.anomaly_score === null || l.anomaly_status === "insufficient_history";
        }
        return l.anomaly_status === selectedStatus;
      });
    }

    // Default sort by anomaly status descending (Anomalous first)
    list.sort((a, b) => {
      const pA = a.anomaly_score === null ? 0 : STATUS_PRIORITY[a.anomaly_status] ?? 0;
      const pB = b.anomaly_score === null ? 0 : STATUS_PRIORITY[b.anomaly_status] ?? 0;
      if (pB !== pA) return pB - pA;
      return (b.anomaly_score || 0) - (a.anomaly_score || 0);
    });

    return list;
  }, [licenses, searchTerm, selectedStatus]);

  const totalPages = Math.ceil(filteredLicenses.length / pageSize) || 1;
  const paginatedLicenses = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredLicenses.slice(start, start + pageSize);
  }, [filteredLicenses, currentPage]);

  const renderBadge = (status: AnomalyStatus, score: number | null) => {
    if (score === null || status === "insufficient_history") {
      return <Badge tone="neutral">Insufficient data</Badge>;
    }
    if (status === "anomalous") return <Badge tone="danger">Anomalous</Badge>;
    if (status === "watch") return <Badge tone="warning">Watch</Badge>;
    return <Badge tone="success">Normal</Badge>;
  };

  const renderUtilisationBar = (score: number) => {
    const percent = Math.min(Math.round(score * 100), 100);
    let colorClass = "bg-rose-500";
    if (score >= 0.6) colorClass = "bg-emerald-500";
    else if (score >= 0.3) colorClass = "bg-amber-500";

    return (
      <div className="w-32">
        <div className="mb-1 flex justify-between text-xs">
          <span className="font-medium text-slate-700">{formatPercent(score)}</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div className={`h-full rounded-full ${colorClass}`} style={{ width: `${percent}%` }} />
        </div>
      </div>
    );
  };

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-6">
      {/* Top Header Card */}
      <Card>
        <CardHeader
          title="License Inventory & Usage Anomalies"
          subtitle="Real-time SSO usage scoring powered by Isolation Forest to detect inactive and declining seat subscriptions"
        />
        <CardBody className="flex flex-col gap-4">
          {/* Filter and Search Bar */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-1 flex-wrap items-center gap-3">
              <div className="relative min-w-64">
                <Search className="absolute left-3 top-2.5 size-4 text-slate-400" />
                <input
                  type="text"
                  placeholder="Filter by app or vendor..."
                  value={searchTerm}
                  onChange={(e) => {
                    setSearchTerm(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="w-full rounded-md border border-slate-300 py-2 pl-9 pr-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                />
              </div>

              <div className="flex items-center gap-1.5 text-xs text-slate-600">
                <Filter className="size-3.5 text-slate-400" />
                <span>Status:</span>
                <select
                  value={selectedStatus}
                  onChange={(e) => {
                    setSelectedStatus(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 focus:outline-none"
                >
                  <option value="all">All Licenses</option>
                  <option value="anomalous">Anomalous (Needs Action)</option>
                  <option value="watch">Watch</option>
                  <option value="normal">Normal</option>
                  <option value="insufficient_history">Insufficient Data</option>
                </select>
              </div>
            </div>

            <div className="text-xs text-slate-500">
              Showing <span className="font-semibold text-slate-700">{filteredLicenses.length}</span>{" "}
              licenses
            </div>
          </div>

          {/* Licenses Table */}
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
              <thead className="bg-slate-50 text-xs font-semibold text-slate-600">
                <tr>
                  <th className="px-4 py-3">Application & Vendor</th>
                  <th className="px-4 py-3">Total Seats</th>
                  <th className="px-4 py-3">Utilisation</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Last User Login</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 bg-white">
                {paginatedLicenses.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                      No licenses match your filter criteria.
                    </td>
                  </tr>
                ) : (
                  paginatedLicenses.map((lic) => {
                    const isAnomalous = lic.anomaly_status === "anomalous";
                    const isCooldown =
                      lic.reclaim_cooldown_until &&
                      new Date(lic.reclaim_cooldown_until) > new Date();
                    const state = reclaimStates[lic.id] || {};

                    return (
                      <tr
                        key={lic.id}
                        onClick={() => navigate(`/app/licenses/${lic.id}`)}
                        className="cursor-pointer hover:bg-slate-50 transition-colors"
                      >
                        <td className="px-4 py-3">
                          <p className="font-semibold text-slate-800">{lic.app_name}</p>
                          <p className="text-xs text-slate-500">
                            {lic.vendor_name || "Enterprise Vendor"}
                          </p>
                        </td>

                        <td className="px-4 py-3 text-slate-700">
                          <span className="font-medium">{lic.total_seats}</span> seats
                          {lic.cost_per_seat && (
                            <span className="block text-xs text-slate-400">
                              {formatCurrency(lic.cost_per_seat)}/seat
                            </span>
                          )}
                        </td>

                        <td className="px-4 py-3">
                          {renderUtilisationBar(lic.utilisation_score)}
                        </td>

                        <td className="px-4 py-3">
                          {renderBadge(lic.anomaly_status, lic.anomaly_score)}
                        </td>

                        <td className="px-4 py-3 text-slate-700">
                          <div className="flex items-center gap-1.5 font-medium text-slate-800">
                            <Clock className="size-3.5 text-amber-500" />
                            <span>{lic.days_since_last_login} days ago</span>
                          </div>
                        </td>

                        <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                          {state.done ? (
                            <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-600">
                              <CheckCircle2 className="size-3.5" /> Reclaim Opened
                            </span>
                          ) : isAnomalous ? (
                            isCooldown ? (
                              <span
                                className="inline-block rounded border border-slate-200 bg-slate-50 px-2 py-1 text-xs text-slate-400"
                                title={`Cooldown until ${new Date(lic.reclaim_cooldown_until!).toLocaleDateString()}`}
                              >
                                In Cooldown
                              </span>
                            ) : (
                              <Button
                                size="sm"
                                variant="destructive"
                                loading={state.loading}
                                onClick={(e) => handleReclaim(e, lic)}
                                icon={<RotateCcw className="size-3.5" />}
                              >
                                Reclaim
                              </Button>
                            )
                          ) : null}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500">
              <span>
                Page {currentPage} of {totalPages}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((p) => Math.max(p - 1, 1))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage((p) => Math.min(p + 1, totalPages))}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
