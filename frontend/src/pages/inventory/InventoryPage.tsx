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
    { key: "app", header: "Application", render: (l) => <span className="font-medium text-slate-800">{l.app_name}</span> },
    { key: "seats", header: "Total Seats", render: (l) => l.total_seats },
    { key: "active30", header: "Active (30d)", render: (l) => l.active_seats_30d },
    { key: "util", header: "Utilisation", render: (l) => formatPercent(l.utilisation_score), sortValue: (l) => l.utilisation_score },
    { key: "cost", header: "Cost / Seat", render: (l) => formatCurrency(l.cost_per_seat) },
    {
      key: "status",
      header: "Status",
      render: (l) => (
        <Badge tone={l.utilisation_score < 0.3 ? "warning" : "success"}>
          {l.utilisation_score < 0.3 ? "Reclaim candidate" : "Healthy"}
        </Badge>
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
