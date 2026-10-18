import { useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { requestsApi } from "@/api/requests";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Badge } from "@/components/ui/Badge";
import { Tabs } from "@/components/ui/Tabs";
import { ErrorState } from "@/components/ui/ErrorState";
import { FilterChip } from "@/components/ui/FilterChip";
import { PersonName } from "@/components/people/PersonName";
import { APPROVER_ROLES } from "@/lib/constants";
import { formatCountdown, formatCurrency, formatDate, titleCase } from "@/lib/format";
import type { InboxItem } from "@/types/api";
import { approvalItemPath } from "@/lib/routes";

const DAY_MS = 24 * 3600 * 1000;
const DUE_LABEL: Record<string, string> = { today: "Due within 24 hours", overdue: "Past SLA" };

/** ?role=<approver role> picks one inbox (default: all of them);
 * ?due=today|overdue narrows to the SLA figures on the dashboard. */
export function ApprovalInboxPage() {
  usePageHeader("Approval Inbox");
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const role = params.get("role") ?? "all";
  const due = params.get("due");
  const roles = role === "all" ? APPROVER_ROLES.map((r) => r.value) : [role];
  const { data: items, loading, error, reload } = useApi(
    () => Promise.all(roles.map((r) => requestsApi.inbox(r))).then((res) => ({ data: res.flatMap((r) => r.data) })),
    [role],
  );

  const sorted = useMemo(() => {
    const now = Date.now();
    return [...(items ?? [])]
      .filter((i) => {
        if (!due) return true;
        if (!i.sla_deadline) return false;
        const left = new Date(i.sla_deadline).getTime() - now;
        return due === "overdue" ? left < 0 : left > 0 && left < DAY_MS;
      })
      .sort((a, b) => (a.sla_deadline ?? "9999").localeCompare(b.sla_deadline ?? "9999"));
  }, [items, due]);

  const setRole = (k: string) => {
    const next = new URLSearchParams(params);
    if (k === "all") next.delete("role");
    else next.set("role", k);
    setParams(next, { replace: true });
  };
  const clearDue = () => {
    const next = new URLSearchParams(params);
    next.delete("due");
    setParams(next, { replace: true });
  };

  const columns: Column<InboxItem>[] = [
    { key: "id", header: "Request", render: (r) => <span className="font-mono text-caption text-ink-2">PR-{r.request_id.slice(0, 8)}</span> },
    { key: "requester", header: "Requester", render: (r) => <PersonName email={r.requested_by} /> },
    { key: "type", header: "Type", render: (r) => titleCase(r.request_type) },
    { key: "dept", header: "Department", render: (r) => r.department },
    { key: "amount", header: "Amount", render: (r) => formatCurrency(r.amount, r.currency), sortValue: (r) => r.amount, className: "text-right tabular" },
    { key: "tier", header: "Tier", render: (r) => <span className="text-ink-2">{titleCase(r.spend_tier)}</span> },
    { key: "submitted", header: "Submitted", render: (r) => formatDate(r.created_at) },
    {
      key: "sla",
      header: "SLA",
      render: (r) => {
        const countdown = formatCountdown(r.sla_deadline);
        if (!countdown) return "—";
        return <Badge tone={countdown.overdue ? "danger" : "warning"}>{countdown.label}</Badge>;
      },
      sortValue: (r) => r.sla_deadline ?? "9999",
    },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-4">
      {due && DUE_LABEL[due] && (
        <div>
          <FilterChip label={DUE_LABEL[due]} onClear={clearDue} />
        </div>
      )}
      <Card>
        <div className="px-2 pt-1 sm:px-3">
          <Tabs
            tabs={[{ key: "all", label: "All roles" }, ...APPROVER_ROLES.map((r) => ({ key: r.value, label: r.label }))]}
            active={role}
            onChange={setRole}
          />
        </div>
        <CardBody>
          <DataTable
            columns={columns}
            rows={sorted}
            rowKey={(r) => r.request_id}
            loading={loading}
            onRowClick={(r) => navigate(approvalItemPath(r))}
            emptyTitle="Nothing waiting for a decision"
          />
        </CardBody>
      </Card>
    </div>
  );
}
