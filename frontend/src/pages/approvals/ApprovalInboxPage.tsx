import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { requestsApi } from "@/api/requests";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Badge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { APPROVER_ROLES } from "@/lib/constants";
import { formatCountdown, formatCurrency, formatDate } from "@/lib/format";
import type { InboxItem } from "@/types/api";

export function ApprovalInboxPage() {
  usePageHeader("Approval Inbox");
  const navigate = useNavigate();
  const [role, setRole] = useState<string>(APPROVER_ROLES[0].value);
  const { data: items, loading, error, reload } = useApi(() => requestsApi.inbox(role), [role]);

  const sorted = useMemo(() => [...(items ?? [])].sort((a, b) => (a.sla_deadline ?? "9999").localeCompare(b.sla_deadline ?? "9999")), [items]);

  const columns: Column<InboxItem>[] = [
    { key: "id", header: "Request", render: (r) => <span className="font-mono text-xs">{r.request_id.slice(0, 8)}</span> },
    { key: "requester", header: "Requester", render: (r) => r.requested_by },
    { key: "type", header: "Type", render: (r) => <span className="capitalize">{r.request_type}</span> },
    { key: "dept", header: "Department", render: (r) => r.department },
    { key: "amount", header: "Amount", render: (r) => formatCurrency(r.amount, r.currency), sortValue: (r) => r.amount },
    { key: "tier", header: "Tier", render: (r) => <span className="capitalize text-slate-500">{r.spend_tier}</span> },
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
      <div className="flex flex-wrap items-center gap-2">
        {APPROVER_ROLES.map((r) => (
          <button
            key={r.value}
            onClick={() => setRole(r.value)}
            className={`rounded-full border px-3 py-1.5 text-sm font-medium transition-colors ${
              role === r.value ? "border-brand-600 bg-brand-50 text-brand-700" : "border-surface-border text-slate-600 hover:border-slate-300"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>
      <Card>
        <CardBody>
          <DataTable
            columns={columns}
            rows={sorted}
            rowKey={(r) => r.request_id}
            loading={loading}
            onRowClick={(r) => navigate(`/app/requests/${r.request_id}`)}
            emptyTitle="Nothing pending for this role"
            emptyDescription="Requests routed to this approver role will appear here."
          />
        </CardBody>
      </Card>
    </div>
  );
}
