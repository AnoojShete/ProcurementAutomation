import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Clock, Inbox } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { usePageHeader } from "@/hooks/usePageTitle";
import { requestsApi } from "@/api/requests";
import { Greeting } from "@/components/dashboard/Greeting";
import { MetricCard } from "@/components/ui/MetricCard";
import { AttentionCard, type AttentionItem } from "@/components/dashboard/AttentionCard";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { SkeletonCard } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Badge } from "@/components/ui/Badge";
import { formatCountdown, formatCurrency, formatDate } from "@/lib/format";
import { APPROVER_ROLES } from "@/lib/constants";
import { useAuth } from "@/hooks/useAuth";

export function ApproverDashboard() {
  const { user } = useAuth();
  usePageHeader("Approval Center");
  const navigate = useNavigate();

  const inboxResults = APPROVER_ROLES.map((role) => useApi(() => requestsApi.inbox(role.value), [role.value]));
  const { data: allRequests } = useApi(() => requestsApi.list(200), []);

  const loading = inboxResults.some((r) => r.loading);
  const error = inboxResults.find((r) => r.error)?.error ?? null;
  const inboxItems = useMemo(() => inboxResults.flatMap((r) => r.data ?? []), [inboxResults]);

  const kpis = useMemo(() => {
    const now = Date.now();
    const dueToday = inboxItems.filter((i) => {
      if (!i.sla_deadline) return false;
      const diff = new Date(i.sla_deadline).getTime() - now;
      return diff > 0 && diff < 24 * 3600 * 1000;
    }).length;
    const escalated = inboxItems.filter((i) => {
      if (!i.sla_deadline) return false;
      return new Date(i.sla_deadline).getTime() < now;
    }).length;
    const approvedThisMonth = (allRequests ?? []).filter((r) => {
      if (r.status !== "approved" && r.status !== "fulfilled") return false;
      const decidedByMe = r.approval_history?.some((h) => h.decided_by === user?.email && h.decision === "approved");
      if (!decidedByMe) return false;
      const d = r.updated_at ? new Date(r.updated_at) : null;
      if (!d) return false;
      const now2 = new Date();
      return d.getMonth() === now2.getMonth() && d.getFullYear() === now2.getFullYear();
    }).length;
    return { pending: inboxItems.length, dueToday, escalated, approvedThisMonth };
  }, [inboxItems, allRequests, user]);

  const attentionItems: AttentionItem[] = useMemo(() => {
    const items: AttentionItem[] = [];
    if (kpis.pending > 0) {
      items.push({
        key: "pending",
        message: (
          <>
            <strong>{kpis.pending}</strong> request{kpis.pending > 1 ? "s are" : " is"} waiting for your decision.
          </>
        ),
        cta: "Open Approval Inbox",
        to: "/app/approvals",
      });
    }
    if (kpis.escalated > 0) {
      items.push({
        key: "escalated",
        message: (
          <>
            <strong>{kpis.escalated}</strong> request{kpis.escalated > 1 ? "s have" : " has"} passed their SLA deadline.
          </>
        ),
        cta: "Review escalations",
        to: "/app/approvals",
      });
    }
    return items;
  }, [kpis]);

  const urgent = [...inboxItems]
    .sort((a, b) => (a.sla_deadline ?? "9999").localeCompare(b.sla_deadline ?? "9999"))
    .slice(0, 6);

  if (error) return <ErrorState message={error} />;

  return (
    <div className="flex flex-col gap-6">
      <Greeting name={user?.email.split("@")[0] ?? "there"} subtitle="Requests routed to your approval roles, prioritized by SLA." />

      {loading ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricCard label="Pending Approval" value={kpis.pending} icon={Inbox} tone="brand" />
          <MetricCard label="Due Today" value={kpis.dueToday} icon={Clock} tone="warning" />
          <MetricCard label="Escalated" value={kpis.escalated} icon={AlertTriangle} tone="danger" />
          <MetricCard label="Approved This Month" value={kpis.approvedThisMonth} icon={CheckCircle2} tone="success" />
        </div>
      )}

      <AttentionCard items={attentionItems} />

      <Card>
        <CardHeader title="Approval Inbox" subtitle="Highest-priority requests across your approval roles" />
        <CardBody>
          {urgent.length === 0 ? (
            <EmptyState title="Nothing pending for your roles" description="You're all caught up — new requests will appear here as they're routed to you." />
          ) : (
            <div className="flex flex-col gap-2">
              {urgent.map((item) => {
                const countdown = formatCountdown(item.sla_deadline);
                const highPriority = countdown?.overdue || (item.amount ?? 0) > 100000;
                return (
                  <button
                    key={item.request_id}
                    onClick={() => navigate(`/app/requests/${item.request_id}`)}
                    className={`flex items-center justify-between gap-4 rounded-lg border px-4 py-3 text-left transition-colors hover:border-brand-300 ${
                      highPriority ? "border-danger-100 bg-danger-50/40" : "border-surface-border"
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        {highPriority && <Badge tone="danger">High Priority</Badge>}
                        <span className="truncate text-sm font-medium text-slate-800">
                          {item.request_type} — {item.department}
                        </span>
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {item.requested_by} · Submitted {formatDate(item.created_at)}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-sm font-semibold tabular text-slate-800">{formatCurrency(item.amount, item.currency)}</p>
                      {countdown && (
                        <p className={`text-xs ${countdown.overdue ? "font-medium text-danger-600" : "text-slate-500"}`}>
                          SLA: {countdown.label}
                        </p>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
