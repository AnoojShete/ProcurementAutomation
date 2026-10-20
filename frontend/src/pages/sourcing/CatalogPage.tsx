import { useMemo, useState } from "react";
import { catalogApi } from "@/api/catalog";
import { licensesApi } from "@/api/licenses";
import { vendorsApi } from "@/api/vendors";
import { AddCatalogItem, CatalogItemControls, OrderFromCatalog, type Basket } from "@/components/approvals/CatalogActions";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader, Section } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { ErrorState } from "@/components/ui/ErrorState";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/hooks/usePageTitle";
import { formatCurrency, formatDate } from "@/lib/format";
import type { CatalogItem } from "@/types/api";

const CATEGORY: Record<string, string> = { hardware: "Hardware", software: "Software licence", saas: "SaaS" };

/** Phase 3a: the IT catalog. Anyone orders from it; finance and admin keep it. */
export function CatalogPage() {
  usePageHeader("IT Catalog");
  const { user } = useAuth();
  const canManage = user?.role === "finance" || user?.role === "admin";
  const [q, setQ] = useState("");
  const [basket, setBasket] = useState<Basket>({});
  const { data: items, loading, error, reload } = useApi(() => catalogApi.list({ includeUnavailable: canManage }), [canManage]);
  const { data: vendors } = useApi(() => (canManage ? vendorsApi.list(200) : Promise.resolve({ data: [] })), [canManage]);
  const { data: inventory } = useApi(() => (canManage ? licensesApi.list() : Promise.resolve({ data: null })), [canManage]);

  const shown = useMemo(() => (items ?? []).filter((i) =>
    !q.trim() || `${i.name} ${i.sku} ${i.vendor_name ?? ""}`.toLowerCase().includes(q.trim().toLowerCase())), [items, q]);
  const orderable = (items ?? []).filter((i) => i.available);

  const columns: Column<CatalogItem>[] = [
    { key: "name", header: "Item", render: (i) => (
      <span className="flex flex-col">
        <span className="font-medium text-ink">{i.name}</span>
        <span className="text-13 text-ink-3">{i.sku}{Object.keys(i.spec).length ? ` · ${Object.entries(i.spec).map(([k, v]) => `${k} ${v}`).join(", ")}` : ""}</span>
      </span>), sortValue: (i) => i.name.toLowerCase() },
    { key: "category", header: "Category", render: (i) => <>{CATEGORY[i.category]}{i.seat_addon ? " · seat add-on" : ""}</>, sortValue: (i) => i.category, hideOnMobile: true },
    { key: "vendor", header: "Vendor", render: (i) => i.vendor_name ?? "—", sortValue: (i) => i.vendor_name ?? "", hideOnMobile: true },
    { key: "price", header: "Agreed price", render: (i) => <span className="tabular">{formatCurrency(i.unit_price)}</span>, sortValue: (i) => i.unit_price },
    { key: "terms", header: "Terms", render: (i) => [i.lead_time_days != null && `${i.lead_time_days} ${i.lead_time_days === 1 ? "day" : "days"}`, i.warranty_months && `${i.warranty_months} mo warranty`].filter(Boolean).join(" · ") || "—", hideOnMobile: true },
    { key: "state", header: "", render: (i) => i.available ? (
        <Button size="sm" variant={basket[i.id] ? "secondary" : "primary"} onClick={(e) => { e.stopPropagation(); setBasket({ ...basket, [i.id]: (basket[i.id] ?? 0) + 1 }); }}>
          {basket[i.id] ? `Added (${basket[i.id]})` : "Add"}
        </Button>
      ) : <Badge tone="neutral">{i.active ? `expired ${formatDate(i.valid_until)}` : "switched off"}</Badge> },
    ...(canManage ? [{ key: "manage", header: "", render: (i: CatalogItem) => <CatalogItemControls item={i} onChanged={reload} /> }] : []),
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader title="Your order" subtitle="One request per vendor. Catalog prices can't be changed on the request." />
        <CardBody><OrderFromCatalog items={orderable} basket={basket} setBasket={setBasket} /></CardBody>
      </Card>
      <Section title="Catalog" subtitle="Approved IT items with agreed prices. An item whose price has expired is hidden from requesters."
        action={<input aria-label="Search the catalog" className="h-9 w-64 rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search items, SKUs, vendors" />}>
        <DataTable columns={columns} rows={shown} rowKey={(i) => i.id} loading={loading && !items}
          emptyTitle="Nothing in the catalog yet" emptyDescription={canManage ? "Add the first item below." : "Finance adds approved items with agreed prices."} />
      </Section>
      {canManage && <AddCatalogItem vendors={vendors ?? []} licenses={inventory?.licenses ?? []} onChanged={reload} />}
    </div>
  );
}
