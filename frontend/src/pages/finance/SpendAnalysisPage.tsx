import { useMemo } from "react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { CategoryBarChart } from "@/components/charts/CategoryBarChart";
import { ErrorState } from "@/components/ui/ErrorState";
import { formatCurrency } from "@/lib/format";

export function SpendAnalysisPage() {
  usePageHeader("Spend Analysis");
  const { data: requests, loading, error, reload } = useApi(() => requestsApi.list(200), []);
  const { data: vendors } = useApi(() => vendorsApi.list(200), []);

  const approved = useMemo(() => (requests ?? []).filter((r) => r.status === "approved" || r.status === "fulfilled"), [requests]);

  const byCategory = useMemo(() => {
    const map = new Map<string, number>();
    approved.forEach((r) => map.set(r.request_type ?? "other", (map.get(r.request_type ?? "other") ?? 0) + (r.amount ?? 0)));
    return Array.from(map.entries()).map(([label, value]) => ({ label, value }));
  }, [approved]);

  const byVendor = useMemo(() => {
    const map = new Map<string, number>();
    approved.forEach((r) => {
      if (!r.vendor_id) return;
      const name = vendors?.find((v) => v.id === r.vendor_id)?.name ?? r.vendor_id.slice(0, 8);
      map.set(name, (map.get(name) ?? 0) + (r.amount ?? 0));
    });
    return Array.from(map.entries())
      .map(([label, value]) => ({ label, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 8);
  }, [approved, vendors]);

  const byMonth = useMemo(() => {
    const map = new Map<string, number>();
    approved.forEach((r) => {
      if (!r.created_at) return;
      const d = new Date(r.created_at);
      const key = d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
      map.set(key, (map.get(key) ?? 0) + (r.amount ?? 0));
    });
    return Array.from(map.entries()).map(([label, value]) => ({ label, value }));
  }, [approved]);

  const totalSpend = approved.reduce((s, r) => s + (r.amount ?? 0), 0);

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader title="Total Approved Spend" subtitle="Across all approved and fulfilled requests" />
        <CardBody>
          <p className="text-3xl font-semibold tabular text-slate-900">{formatCurrency(totalSpend)}</p>
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Spend by Category" />
          <CardBody>
            {loading ? <p className="text-sm text-slate-400">Loading…</p> : byCategory.length ? (
              <CategoryBarChart data={byCategory} valueFormatter={(v) => formatCurrency(v)} />
            ) : (
              <p className="py-8 text-center text-sm text-slate-500">No approved spend recorded yet.</p>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Spend by Vendor" subtitle="Top 8 vendors by approved spend" />
          <CardBody>
            {byVendor.length ? (
              <CategoryBarChart data={byVendor} valueFormatter={(v) => formatCurrency(v)} />
            ) : (
              <p className="py-8 text-center text-sm text-slate-500">No vendor-linked spend recorded yet.</p>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Monthly Procurement Trend" />
        <CardBody>
          {byMonth.length ? (
            <CategoryBarChart data={byMonth} valueFormatter={(v) => formatCurrency(v)} />
          ) : (
            <p className="py-8 text-center text-sm text-slate-500">Not enough data yet to show a trend.</p>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
