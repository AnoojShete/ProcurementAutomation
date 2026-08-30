import { useMemo } from "react";
import { AlertTriangle, IndianRupee, PieChart, RefreshCcw, ScrollText } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { usePageHeader } from "@/hooks/usePageTitle";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { contractsApi } from "@/api/contracts";
import { Greeting } from "@/components/dashboard/Greeting";
import { MetricCard } from "@/components/ui/MetricCard";
import { AttentionCard, type AttentionItem } from "@/components/dashboard/AttentionCard";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { CategoryBarChart } from "@/components/charts/CategoryBarChart";
import { formatCurrency } from "@/lib/format";
import { APPROVER_ROLES } from "@/lib/constants";
import { useAuth } from "@/hooks/useAuth";

export function FinanceDashboard() {
  const { user } = useAuth();
  usePageHeader("Dashboard");
  const { data: requests, loading: reqLoading } = useApi(() => requestsApi.list(200), []);
  const { data: vendors, loading: vendorsLoading } = useApi(() => vendorsApi.list(200), []);
  const { data: contracts } = useApi(() => contractsApi.list(200), []);
  const { data: renewals } = useApi(() => contractsApi.renewalsDue(60), []);
  const financeInbox = useApi(() => requestsApi.inbox(APPROVER_ROLES[1].value), []);

  const highRiskVendors = useMemo(() => (vendors ?? []).filter((v) => v.risk_band === "High"), [vendors]);

  const monthlySpend = useMemo(() => {
    const now = new Date();
    return (requests ?? [])
      .filter((r) => (r.status === "approved" || r.status === "fulfilled") && r.created_at)
      .filter((r) => {
        const d = new Date(r.created_at!);
        return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
      })
      .reduce((sum, r) => sum + (r.amount ?? 0), 0);
  }, [requests]);

  const spendByCategory = useMemo(() => {
    const map = new Map<string, number>();
    (requests ?? [])
      .filter((r) => r.status === "approved" || r.status === "fulfilled")
      .forEach((r) => {
        const key = r.request_type ?? "other";
        map.set(key, (map.get(key) ?? 0) + (r.amount ?? 0));
      });
    return Array.from(map.entries()).map(([label, value]) => ({ label, value }));
  }, [requests]);

  const attentionItems: AttentionItem[] = useMemo(() => {
    const items: AttentionItem[] = [];
    const pending = financeInbox.data?.length ?? 0;
    if (pending > 0) {
      items.push({
        key: "finance-pending",
        message: (
          <>
            <strong>{pending}</strong> request{pending > 1 ? "s require" : " requires"} financial approval.
          </>
        ),
        cta: "Review",
        to: "/app/approvals",
      });
    }
    if ((renewals?.length ?? 0) > 0) {
      items.push({
        key: "renewals",
        message: (
          <>
            <strong>{renewals!.length}</strong> contract{renewals!.length > 1 ? "s are" : " is"} renewing within 60 days.
          </>
        ),
        cta: "View contracts",
        to: "/app/contracts",
      });
    }
    if (highRiskVendors.length > 0) {
      items.push({
        key: "high-risk",
        message: (
          <>
            <strong>{highRiskVendors.length}</strong> vendor{highRiskVendors.length > 1 ? "s are" : " is"} flagged high risk.
          </>
        ),
        cta: "Review vendors",
        to: "/app/vendors",
      });
    }
    return items;
  }, [financeInbox.data, renewals, highRiskVendors]);

  const loading = reqLoading || vendorsLoading;

  return (
    <div className="flex flex-col gap-6">
      <Greeting name={user?.email.split("@")[0] ?? "there"} subtitle="Spend, budget, and vendor risk across the organization." />

      {loading ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <MetricCard label="Pending Financial Approval" value={financeInbox.data?.length ?? 0} icon={ScrollText} tone="warning" />
          <MetricCard label="Monthly Spend" value={formatCurrency(monthlySpend)} icon={IndianRupee} tone="brand" />
          <MetricCard
            label="High-Risk Vendors"
            value={highRiskVendors.length}
            icon={AlertTriangle}
            tone={highRiskVendors.length ? "danger" : "success"}
          />
          <MetricCard label="Contract Renewals (60d)" value={renewals?.length ?? 0} icon={RefreshCcw} tone="warning" />
          <MetricCard label="Active Contracts" value={contracts?.filter((c) => c.status === "signed").length ?? 0} icon={PieChart} tone="brand" />
        </div>
      )}

      <AttentionCard items={attentionItems} />

      <Card>
        <CardHeader title="Spend by Request Type" subtitle="Approved and fulfilled requests, grouped by category" />
        <CardBody>
          {spendByCategory.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">No approved spend recorded yet.</p>
          ) : (
            <CategoryBarChart data={spendByCategory} valueFormatter={(v) => formatCurrency(v)} />
          )}
        </CardBody>
      </Card>
    </div>
  );
}
