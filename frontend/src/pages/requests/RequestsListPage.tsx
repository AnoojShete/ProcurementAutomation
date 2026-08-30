import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FilePlus2 } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { requestsApi } from "@/api/requests";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { Tabs } from "@/components/ui/Tabs";
import { formatCurrency, formatDate } from "@/lib/format";
import type { PurchaseRequest } from "@/types/api";

export function RequestsListPage() {
  usePageHeader("My Requests", "Requests");
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: requests, loading, error, reload } = useApi(() => requestsApi.list(200), []);
  const [scope, setScope] = useState<"mine" | "all">(user?.role === "requester" ? "mine" : "all");

  const rows = useMemo(() => {
    const all = requests ?? [];
    if (scope === "mine") return all.filter((r) => r.requested_by === user?.email);
    return all;
  }, [requests, scope, user]);

  const columns: Column<PurchaseRequest>[] = [
    { key: "id", header: "Request", render: (r) => <span className="font-mono text-xs">{r.id.slice(0, 8)}</span> },
    { key: "type", header: "Type", render: (r) => <span className="capitalize">{r.request_type ?? "—"}</span> },
    { key: "requester", header: "Requester", render: (r) => r.requested_by ?? "—", hideOnMobile: scope !== "all" },
    { key: "dept", header: "Department", render: (r) => r.department ?? "—" },
    { key: "amount", header: "Amount", render: (r) => formatCurrency(r.amount, r.currency ?? "INR"), sortValue: (r) => r.amount ?? 0 },
    { key: "tier", header: "Tier", render: (r) => <span className="capitalize text-slate-500">{r.spend_tier ?? "—"}</span> },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "created", header: "Submitted", render: (r) => formatDate(r.created_at), sortValue: (r) => r.created_at ?? "" },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {user?.role !== "requester" ? (
          <Tabs
            tabs={[
              { key: "all", label: "All Requests" },
              { key: "mine", label: "Created by me" },
            ]}
            active={scope}
            onChange={(k) => setScope(k as "mine" | "all")}
          />
        ) : (
          <div />
        )}
        {(user?.role === "requester" || user?.role === "admin") && (
          <Button icon={<FilePlus2 className="size-4" />} onClick={() => navigate("/app/requests/new")}>
            New Purchase Request
          </Button>
        )}
      </div>
      <Card>
        <CardBody>
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(r) => r.id}
            loading={loading}
            onRowClick={(r) => navigate(`/app/requests/${r.id}`)}
            emptyTitle="No requests to show"
            emptyDescription="Purchase requests you create or that are visible to your role will appear here."
          />
        </CardBody>
      </Card>
    </div>
  );
}
