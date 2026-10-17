import { useMemo, useState } from "react";
import { Boxes, PackageCheck, PackageMinus, PackageX, Pencil } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { inventoryApi } from "@/api/inventory";
import { requestsApi } from "@/api/requests";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Badge } from "@/components/ui/Badge";
import { Tabs } from "@/components/ui/Tabs";
import { ErrorState } from "@/components/ui/ErrorState";
import { ReorderSettings } from "@/components/inventory/ReorderSettings";
import { useAuth } from "@/hooks/useAuth";
import { formatCurrency, formatPercent, titleCase } from "@/lib/format";
import type { InventoryItem, LicenseItem } from "@/types/api";

export function InventoryPage() {
  usePageHeader("Inventory");
  const { data: snapshot, loading, error, reload } = useApi(() => inventoryApi.get(), []);
  const { data: requests } = useApi(() => requestsApi.list(200), []);
  const [tab, setTab] = useState<"hardware" | "licenses">("hardware");
  const [editing, setEditing] = useState<InventoryItem | null>(null);
  const { user } = useAuth();
  const canEdit = ["finance", "admin"].includes(user?.role ?? "");

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
      lowStock: hardware.filter((i) => i.reorder?.needs_reorder).length,
    }),
    [hardware],
  );
  const toReorder = hardware.filter((i) => i.reorder?.needs_reorder);

  const hwColumns: Column<InventoryItem>[] = [
    { key: "name", header: "Item", render: (i) => <span className="font-medium text-slate-800">{i.name}</span> },
    { key: "sku", header: "SKU", render: (i) => <span className="font-mono text-xs text-slate-500">{i.sku}</span> },
    { key: "category", header: "Category", render: (i) => <span className="capitalize">{i.category ?? "—"}</span> },
    { key: "available", header: "Available", render: (i) => i.available_quantity, sortValue: (i) => i.available_quantity },
    { key: "reserved", header: "Reserved", render: (i) => i.reserved_quantity, sortValue: (i) => i.reserved_quantity },
    {
      key: "reorder",
      header: "Reorder Point",
      render: (i) => (
        <span className="inline-flex items-center gap-1.5">
          {i.reorder?.reorder_point ?? "—"}
          {i.reorder?.point_source === "rule" && <span className="text-xs text-slate-400">default</span>}
          {canEdit && (
            <button type="button" aria-label={`Edit reorder settings for ${i.name}`} onClick={() => setEditing(i)}
              className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
              <Pencil className="size-3.5" />
            </button>
          )}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (i) => {
        if (i.available_quantity === 0) return <Badge tone="danger">Out of Stock</Badge>;
        if (i.reorder?.needs_reorder) return <Badge tone="warning">Reorder</Badge>;
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
          Details
        </a>
      ),
    },
  ];


  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-6">
      <LedgerStrip cols={4} label="Inventory figures">
        <MetricCard label="Available Units" value={totals.available} icon={PackageCheck} tone="success" />
        <MetricCard label="Reserved Units" value={totals.reserved} icon={Boxes} tone="brand" />
        <MetricCard label="SKUs to Reorder" value={totals.lowStock} icon={PackageMinus} tone={totals.lowStock ? "warning" : "success"} />
        <MetricCard label="Requests Partially Backordered" value={backorderedRequests.length} icon={PackageX} tone={backorderedRequests.length ? "warning" : "success"} />
      </LedgerStrip>

      {toReorder.length > 0 && (
        <Card>
          <CardHeader title="Reorder Suggestions" subtitle="From stock on the shelf and backordered requests" />
          <CardBody className="flex flex-col gap-2">
            {toReorder.map((i) => (
              <div key={i.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-surface-border px-3.5 py-2.5 text-sm">
                <div>
                  <p className="font-medium text-slate-800">
                    {i.name} <span className="font-mono text-xs text-slate-500">{i.sku}</span>
                  </p>
                  <p className="text-xs text-slate-600">{i.reorder!.explanation}</p>
                </div>
                <Badge tone="warning">Order {i.reorder!.suggested_quantity}</Badge>
              </div>
            ))}
          </CardBody>
        </Card>
      )}

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
          subtitle={tab === "hardware" ? "Reorder point and quantity are set per item, or default to a share of total stock (Business Rules)" : "Utilisation is measured over rolling 30/60/90-day windows"}
        />
        <CardBody>
          {tab === "hardware" ? (
            <DataTable columns={hwColumns} rows={hardware} rowKey={(i) => i.id} loading={loading} emptyTitle="No hardware inventory configured" />
          ) : (
            <DataTable columns={licColumns} rows={licenses} rowKey={(l) => l.id} loading={loading} emptyTitle="No licenses tracked" />
          )}
        </CardBody>
      </Card>

      {editing && (
        <ReorderSettings item={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />
      )}

      {backorderedRequests.length > 0 && (
        <Card>
          <CardHeader title="Partial Fulfillment" subtitle="Requests where demand exceeded available stock" />
          <CardBody className="flex flex-col gap-2">
            {backorderedRequests.map((r) => (
              <div key={r.id} className="flex items-center justify-between rounded-lg border border-warning-50 bg-warning-50/40 px-3.5 py-2.5 text-sm">
                <span className="text-ink">{titleCase(r.request_type)} — {r.department}</span>
                <Badge tone="warning">Partial fulfillment available</Badge>
              </div>
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  );
}
