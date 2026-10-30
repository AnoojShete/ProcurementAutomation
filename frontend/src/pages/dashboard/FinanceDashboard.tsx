import { useMemo } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, IndianRupee, PieChart, RefreshCcw, ScrollText } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/hooks/usePageTitle";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { contractsApi } from "@/api/contracts";
import { Greeting } from "@/components/dashboard/Greeting";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { OrderStatusCard } from "@/components/dashboard/OrderStatusCard";
import { AttentionCard, type AttentionItem } from "@/components/dashboard/AttentionCard";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { CategoryBarChart } from "@/components/charts/CategoryBarChart";
import { formatCurrency, titleCase } from "@/lib/format";

export function FinanceDashboard() {
  usePageHeader("Dashboard");
  const { user } = useAuth();
  const { data: requests, loading: reqLoading } = useApi(() => requestsApi.list(200), []);
  const { data: vendors, loading: vendorsLoading } = useApi(() => vendorsApi.list(200), []);
  const { data: contracts } = useApi(() => contractsApi.list(200), []);
  const { data: renewals } = useApi(() => contractsApi.renewalsDue(60), []);
  const financeInbox = useApi(() => requestsApi.inbox("finance_head"), []);

  const pendingFinanceItems = useMemo(() => {
    return (financeInbox.data ?? []).filter((item) => {
      const fullReq = requests?.find((r) => r.id === item.request_id);
      if (fullReq?.approval_history?.some((h) => h.decided_by === user?.email && h.decision === "approved")) {
        return false;
      }
      return true;
    });
  }, [financeInbox.data, requests, user]);

  const highRiskVendors = useMemo(() => (vendors ?? []).filter((v) => v.risk_band === "High"), [vendors]);

  const monthlySpend = useMemo(() => {
    const now = new Date();
    return (requests ?? [])
      .filter((r) => ["approved", "ordered", "partially_received", "fulfilled"].includes(r.status ?? ""))
      .filter((r) => {
        if (!r.created_at) return false;
        const d = new Date(r.created_at);
        return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
      })
      .reduce((sum, r) => sum + (r.amount ?? 0), 0);
  }, [requests]);

  const spendByCategory = useMemo(() => {
    const map = new Map<string, number>();
    (requests ?? [])
      .filter((r) => ["approved", "ordered", "partially_received", "fulfilled"].includes(r.status ?? ""))
      .forEach((r) => {
        const key = r.request_type ?? "other";
        map.set(titleCase(key), (map.get(titleCase(key)) ?? 0) + (r.amount ?? 0));
      });
    return Array.from(map.entries()).map(([label, value]) => ({ label, value }));
  }, [requests]);

  const attentionItems: AttentionItem[] = useMemo(() => {
    const items: AttentionItem[] = [];
    const pending = pendingFinanceItems.length;
    if (pending > 0) {
      items.push({
        key: "finance-pending",
        message: (
          <>
            <strong>{pending}</strong> request{pending > 1 ? "s require" : " requires"} financial approval.
          </>
        ),
        cta: "Review",
        to: "/app/approvals?role=finance_head",
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
        to: "/app/contracts?renewal=60",
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
        to: "/app/vendors?risk=High",
      });
    }
    return items;
  }, [pendingFinanceItems, renewals, highRiskVendors]);

  const loading = reqLoading || vendorsLoading;

  return (
    <div className="flex flex-col gap-6">
      <Greeting />

      <AttentionCard items={attentionItems} />

      <LedgerStrip cols={5} loading={loading} label="Finance figures">
        <MetricCard
          label="Pending Financial Approval"
          value={pendingFinanceItems.length}
          icon={ScrollText}
          tone="warning"
          to="/app/approvals?role=finance_head"
        />
        <MetricCard label="Monthly Spend" value={formatCurrency(monthlySpend)} icon={IndianRupee} tone="brand" to="/app/spend" />
        <MetricCard
          label="High-Risk Vendors"
          value={highRiskVendors.length}
          icon={AlertTriangle}
          tone={highRiskVendors.length ? "danger" : "success"}
          to="/app/vendors?risk=High"
        />
        <MetricCard label="Contract Renewals (60d)" value={renewals?.length ?? 0} icon={RefreshCcw} tone="warning" to="/app/contracts?renewal=60" />
        <MetricCard label="Active Contracts" value={contracts?.filter((c) => c.status === "signed").length ?? 0} icon={PieChart} tone="brand" to="/app/contracts?status=signed" />
      </LedgerStrip>

      <OrderStatusCard />

      <Card>
        <CardHeader title="Spend by Request Type" action={<Link to="/app/spend" className="text-13 font-medium text-accent hover:underline">Spend analysis</Link>} />
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
