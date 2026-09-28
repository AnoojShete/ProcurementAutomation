import { useMemo, useState } from "react";
import { Boxes, PackageCheck, PackageMinus, PackageX } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { inventoryApi } from "@/api/inventory";
import { requestsApi } from "@/api/requests";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { MetricCard } from "@/components/ui/MetricCard";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Badge } from "@/components/ui/Badge";
import { Tabs } from "@/components/ui/Tabs";
import { ErrorState } from "@/components/ui/ErrorState";
import { formatCurrency, formatPercent } from "@/lib/format";
import type { InventoryItem, LicenseItem } from "@/types/api";

export function InventoryPage() {
  usePageHeader("Inventory");
  const { data: snapshot, loading, error, reload } = useApi(() => inventoryApi.get(), []);
  const { data: requests } = useApi(() => requestsApi.list(200), []);
  const [tab, setTab] = useState<"hardware" | "licenses">("hardware");

  const hardware = snapshot?.hardware ?? [];
  const licenses = snapshot?.licenses ?? [];

  const backorderedRequests = useMemo(
    () => (requests ?? []).filter((r) => r.is_backordered && r.status !== "rejected"),
    [requests],
  );

  const totals = useMemo(
    () => ({
      available: hardware.reduce((s, i) => s + i.available_quantity, 0),
      reserved: hardware.reduce((s, i) => s + i.reserved_quantity, 0),
      lowStock: hardware.filter((i) => i.available_quantity === 0 || i.available_quantity < i.total_quantity * 0.1).length,
    }),
    [hardware],
  );

  const hwColumns: Column<InventoryItem>[] = [
    { key: "name", header: "Item", render: (i) => <span className="font-medium text-slate-800">{i.name}</span> },
    { key: "sku", header: "SKU", render: (i) => <span className="font-mono text-xs text-slate-500">{i.sku}</span> },
    { key: "category", header: "Category", render: (i) => <span className="capitalize">{i.category ?? "—"}</span> },
    { key: "available", header: "Available", render: (i) => i.available_quantity, sortValue: (i) => i.available_quantity },
    { key: "reserved", header: "Reserved", render: (i) => i.reserved_quantity, sortValue: (i) => i.reserved_quantity },
    { key: "reorder", header: "Reorder Point", render: (i) => Math.ceil(i.total_quantity * 0.1) },
    {
      key: "status",
      header: "Status",
      render: (i) => {
        if (i.available_quantity === 0) return <Badge tone="danger">Out of Stock</Badge>;
        if (i.available_quantity < i.total_quantity * 0.1) return <Badge tone="warning">Low Stock</Badge>;
        return <Badge tone="success">In Stock</Badge>;
      },
    },
  ];

  const licColumns: Column<LicenseItem>[] = [
    {
      key: "app",
      header: "Application",
      render: (l) => (
        <div>
          <a href={`/app/licenses/${l.id}`} className="font-semibold text-brand-600 hover:underline">
            {l.app_name}
          </a>
          <p className="text-xs text-slate-500">{l.vendor_name || "Enterprise Vendor"}</p>
        </div>
      ),
    },
    { key: "seats", header: "Total Seats", render: (l) => l.total_seats },
    { key: "active30", header: "Active (30d)", render: (l) => l.active_seats_30d },
    { key: "util", header: "Utilisation", render: (l) => formatPercent(l.utilisation_score), sortValue: (l) => l.utilisation_score },
    {
      key: "last_login",
      header: "Last Login",
      render: (l) => `${l.days_since_last_login ?? 0}d ago`,
    },
    {
      key: "anomaly",
      header: "Anomaly Status",
      render: (l) => {
        if (l.anomaly_score === null || l.anomaly_status === "insufficient_history") {
          return <Badge tone="neutral">Insufficient data</Badge>;
        }
        if (l.anomaly_status === "anomalous") return <Badge tone="danger">Anomalous</Badge>;
        if (l.anomaly_status === "watch") return <Badge tone="warning">Watch</Badge>;
        return <Badge tone="success">Normal</Badge>;
      },
    },
    {
      key: "action",
      header: "Action",
      render: (l) => (
        <a
          href={`/app/licenses/${l.id}`}
          className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          Details →
        </a>
      ),
    },
  ];


  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard label="Available Units" value={totals.available} icon={PackageCheck} tone="success" />
        <MetricCard label="Reserved Units" value={totals.reserved} icon={Boxes} tone="brand" />
        <MetricCard label="Low / Out of Stock SKUs" value={totals.lowStock} icon={PackageMinus} tone={totals.lowStock ? "warning" : "success"} />
        <MetricCard label="Requests Partially Backordered" value={backorderedRequests.length} icon={PackageX} tone={backorderedRequests.length ? "warning" : "success"} />
      </div>

      <Tabs
        tabs={[
          { key: "hardware", label: "Hardware", count: hardware.length },
          { key: "licenses", label: "Licenses", count: licenses.length },
        ]}
        active={tab}
        onChange={(k) => setTab(k as typeof tab)}
      />

      <Card>
        <CardHeader
          title={tab === "hardware" ? "Hardware Inventory" : "License Inventory"}
          subtitle={tab === "hardware" ? "Reorder point is a 10% of stock heuristic, not a stored reorder threshold" : "Utilisation is measured over rolling 30/60/90-day windows"}
        />
        <CardBody>
          {tab === "hardware" ? (
            <DataTable columns={hwColumns} rows={hardware} rowKey={(i) => i.id} loading={loading} emptyTitle="No hardware inventory configured" />
          ) : (
            <DataTable columns={licColumns} rows={licenses} rowKey={(l) => l.id} loading={loading} emptyTitle="No licenses tracked" />
          )}
        </CardBody>
      </Card>

      {backorderedRequests.length > 0 && (
        <Card>
          <CardHeader title="Partial Fulfillment" subtitle="Requests where demand exceeded available stock" />
          <CardBody className="flex flex-col gap-2">
            {backorderedRequests.map((r) => (
              <div key={r.id} className="flex items-center justify-between rounded-lg border border-warning-50 bg-warning-50/40 px-3.5 py-2.5 text-sm">
                <span className="text-slate-700 capitalize">{r.request_type} — {r.department}</span>
                <Badge tone="warning">Partial fulfillment available</Badge>
              </div>
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  );
}
