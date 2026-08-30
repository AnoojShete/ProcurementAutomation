import { useMemo } from "react";
import { AlertTriangle, Boxes, Building2, FileText, PackageSearch, ScrollText } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { usePageHeader } from "@/hooks/usePageTitle";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { contractsApi } from "@/api/contracts";
import { inventoryApi } from "@/api/inventory";
import { Greeting } from "@/components/dashboard/Greeting";
import { MetricCard } from "@/components/ui/MetricCard";
import { AttentionCard, type AttentionItem } from "@/components/dashboard/AttentionCard";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { useAuth } from "@/hooks/useAuth";
import { PLATFORM_SERVICES } from "@/lib/constants";

const AGENT_LABELS: Record<string, { agent: string; owns: string }> = {
  "document-vendor-agent": { agent: "Document & Vendor Intelligence", owns: "Ingestion, OCR, classification, vendor matching" },
  "approval-inventory-agent": { agent: "Approval & Inventory", owns: "Approval routing, escalation, reservations" },
  "contract-risk-agent": { agent: "Contract & Risk", owns: "Contract generation, e-sign, vendor risk scoring" },
  "notification-agent": { agent: "Notification", owns: "Email delivery, digest batching" },
  "auth-service": { agent: "Identity", owns: "Login, JWT issuance" },
};

export function AdminDashboard() {
  const { user } = useAuth();
  usePageHeader("Overview");
  const { data: requests, loading: reqLoading } = useApi(() => requestsApi.list(200), []);
  const { data: vendors, loading: vendorsLoading } = useApi(() => vendorsApi.list(200), []);
  const { data: contracts } = useApi(() => contractsApi.list(200), []);
  const { data: renewals } = useApi(() => contractsApi.renewalsDue(30), []);
  const { data: inventory } = useApi(() => inventoryApi.get(), []);

  const pendingApprovals = useMemo(() => (requests ?? []).filter((r) => r.status === "pending_approval").length, [requests]);
  const highRiskVendors = useMemo(() => (vendors ?? []).filter((v) => v.risk_band === "High").length, [vendors]);
  const lowStockItems = useMemo(
    () => (inventory?.hardware ?? []).filter((i) => i.available_quantity <= 0 || i.available_quantity < i.total_quantity * 0.1),
    [inventory],
  );

  const attentionItems: AttentionItem[] = useMemo(() => {
    const items: AttentionItem[] = [];
    if ((renewals?.length ?? 0) > 0) {
      items.push({
        key: "renewals",
        message: (
          <>
            <strong>{renewals!.length}</strong> contract{renewals!.length > 1 ? "s have" : " has"} a renewal deadline within 30 days.
          </>
        ),
        cta: "Review contracts",
        to: "/app/contracts",
      });
    }
    if (highRiskVendors > 0) {
      items.push({
        key: "risk",
        message: (
          <>
            <strong>{highRiskVendors}</strong> vendor{highRiskVendors > 1 ? "s are" : " is"} flagged high risk.
          </>
        ),
        cta: "Review risk",
        to: "/app/risk",
      });
    }
    if (lowStockItems.length > 0) {
      items.push({
        key: "stock",
        message: (
          <>
            <strong>{lowStockItems.length}</strong> hardware item{lowStockItems.length > 1 ? "s are" : " is"} low on stock.
          </>
        ),
        cta: "View inventory",
        to: "/app/inventory",
      });
    }
    return items;
  }, [renewals, highRiskVendors, lowStockItems]);

  const loading = reqLoading || vendorsLoading;

  return (
    <div className="flex flex-col gap-6">
      <Greeting name={user?.email.split("@")[0] ?? "there"} subtitle="Platform-wide procurement command center." />

      {loading ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
          <MetricCard label="Total Requests" value={requests?.length ?? 0} icon={FileText} tone="brand" />
          <MetricCard label="Active Vendors" value={vendors?.filter((v) => v.status === "active").length ?? 0} icon={Building2} tone="brand" />
          <MetricCard label="Pending Approvals" value={pendingApprovals} icon={ScrollText} tone="warning" />
          <MetricCard label="Contracts" value={contracts?.length ?? 0} icon={ScrollText} tone="brand" />
          <MetricCard label="High Risk Vendors" value={highRiskVendors} icon={AlertTriangle} tone={highRiskVendors ? "danger" : "success"} />
          <MetricCard label="Inventory Alerts" value={lowStockItems.length} icon={PackageSearch} tone={lowStockItems.length ? "warning" : "success"} />
        </div>
      )}

      <AttentionCard items={attentionItems} />

      <Card>
        <CardHeader title="Agent Activity" subtitle="Each domain service and what it owns in the pipeline" />
        <CardBody>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {PLATFORM_SERVICES.map((svc) => {
              const meta = AGENT_LABELS[svc.name];
              return (
                <div key={svc.name} className="flex items-start gap-3 rounded-lg border border-surface-border p-3.5">
                  <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
                    <Boxes className="size-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-800">{meta?.agent ?? svc.name}</p>
                    <p className="mt-0.5 text-xs text-slate-500">{meta?.owns ?? svc.owns}</p>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-xs text-slate-400">
            Detailed per-service throughput and error rates are in Grafana — see System Health.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
