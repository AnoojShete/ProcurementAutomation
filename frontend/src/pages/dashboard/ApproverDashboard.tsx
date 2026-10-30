import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Clock, Inbox } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { usePageHeader } from "@/hooks/usePageTitle";
import { requestsApi } from "@/api/requests";
import { Greeting } from "@/components/dashboard/Greeting";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { OrderStatusCard } from "@/components/dashboard/OrderStatusCard";
import { AttentionCard, type AttentionItem } from "@/components/dashboard/AttentionCard";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Badge } from "@/components/ui/Badge";
import { formatCountdown, formatCurrency, formatDate, titleCase } from "@/lib/format";
import { useAuth } from "@/hooks/useAuth";
import { usePeople } from "@/hooks/usePeople";
import { approvalItemPath } from "@/lib/routes";

export function ApproverDashboard() {
  const { user } = useAuth();
  const { nameFor } = usePeople();
  usePageHeader("Approval Center");
  const navigate = useNavigate();

  const { data: rawInbox, loading: inboxLoading, error: inboxError } = useApi(
    () => requestsApi.inbox("dept_manager"),
    []
  );
  const { data: allRequests, loading: reqLoading } = useApi(() => requestsApi.list(200), []);

  const loading = inboxLoading || reqLoading;
  const error = inboxError;

  // Filter out any requests that the current approver has already approved
  const inboxItems = useMemo(() => {
    return (rawInbox ?? []).filter((item) => {
      const fullReq = allRequests?.find((r) => r.id === item.request_id);
      if (fullReq?.approval_history?.some((h) => h.decided_by === user?.email && h.decision === "approved")) {
        return false;
      }
      return true;
    });
  }, [rawInbox, allRequests, user]);

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
      if (!["approved", "ordered", "partially_received", "fulfilled"].includes(r.status ?? "")) return false;
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
        to: "/app/approvals?role=dept_manager",
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
        to: "/app/approvals?role=dept_manager&due=overdue",
      });
    }
    return items;
  }, [kpis]);

  const urgent = [...inboxItems]
    .sort((a, b) => (a.sla_deadline ?? "9999").localeCompare(b.sla_deadline ?? "9999"))
    .slice(0, 6);

  return (
    <div className="flex flex-col gap-6">
      <Greeting />

      <AttentionCard items={attentionItems} />

      <LedgerStrip cols={4} loading={loading} label="Approval figures">
        <MetricCard label="Pending Approval" value={kpis.pending} icon={Inbox} tone="brand" to="/app/approvals?role=dept_manager" />
        <MetricCard label="Due Today" value={kpis.dueToday} icon={Clock} tone="warning" to="/app/approvals?role=dept_manager&due=today" />
        <MetricCard label="Escalated" value={kpis.escalated} icon={AlertTriangle} tone="danger" to="/app/approvals?role=dept_manager&due=overdue" />
        <MetricCard label="Approved This Month" value={kpis.approvedThisMonth} icon={CheckCircle2} tone="success" to="/app/requests?scope=approved" />
      </LedgerStrip>

      <OrderStatusCard />

      <Card>
        <CardHeader
          title="Approval Inbox"
          action={<Link to="/app/approvals?role=dept_manager" className="text-13 font-medium text-accent hover:underline">View all</Link>}
        />
        <CardBody>
          {urgent.length === 0 ? (
            <EmptyState title="Nothing waiting for you" />
          ) : (
            <ul className="-mx-4 divide-y divide-rule border-y border-rule sm:-mx-5">
              {urgent.map((item) => {
                const countdown = formatCountdown(item.sla_deadline);
                const highPriority = countdown?.overdue || (item.amount ?? 0) > 100000;
                return (
                  <li key={item.request_id}>
                    <button
                      onClick={() => navigate(approvalItemPath(item))}
                      className={`flex w-full items-center justify-between gap-4 px-4 py-3 text-left transition-colors duration-1 hover:bg-sheet-sunk focus-visible:ring-inset focus-visible:ring-offset-0 sm:px-5 ${
                        highPriority ? "shadow-[inset_3px_0_0_rgb(var(--danger))]" : ""
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          {highPriority && <Badge tone="danger">High priority</Badge>}
                          <span className="truncate text-sm font-medium text-ink">
                            {titleCase(item.request_type)} — {item.department}
                          </span>
                        </div>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {nameFor(item.requested_by)} · Submitted {formatDate(item.created_at)}
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
                  </li>
                );
              })}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
